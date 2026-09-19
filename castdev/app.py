"""CASTDEV09.26 Flask application: public API + closed admin."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import defaultdict
from pathlib import Path

from flask import (
    Flask,
    Response,
    jsonify,
    make_response,
    request,
    send_from_directory,
    render_template,
)

from . import analyst, analyst_api, cabinet, classify, config, db, stats, validate
from .db import Dataset

# In-memory flood buckets — NOT written to research DB (no IP profiling in research).
_flood_buckets: dict[str, list[float]] = defaultdict(list)


def create_app() -> Flask:
    config.ensure_dirs()
    db.init_all()

    app = Flask(
        __name__,
        static_folder=None,
        template_folder=str(config.ADMIN_TEMPLATES),
    )
    app.config["SECRET_KEY"] = config.ADMIN_SESSION_SECRET
    app.config["TEMPLATES_AUTO_RELOAD"] = True

    # ----- Security headers -----
    @app.after_request
    def security_headers(resp: Response):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Permissions-Policy"] = "interest-cohort=()"
        # Never advertise CORS * (ChatGPT Actions call server-side with Bearer).
        resp.headers.pop("Access-Control-Allow-Origin", None)
        # CSP: same-origin API allowed; no third-party scripts
        if not request.path.startswith("/api/"):
            resp.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; "
                "connect-src 'self'; "
                "frame-ancestors 'none'; "
                "base-uri 'self'; "
                "form-action 'self'"
            )
        return resp

    # ----- Public static survey -----
    @app.get("/")
    def index():
        return send_from_directory(config.STATIC_ROOT, "index.html")

    @app.get("/assets/<path:filename>")
    def assets(filename: str):
        return send_from_directory(config.STATIC_ROOT / "assets", filename)

    @app.get("/favicon.ico")
    def favicon():
        path = config.STATIC_ROOT / "favicon.ico"
        if path.exists():
            return send_from_directory(config.STATIC_ROOT, "favicon.ico")
        return ("", 404)

    # ----- Public submit -----
    @app.post("/api/castdev")
    def api_castdev():
        # Flood soft-limit: hash of remote addr kept ONLY in process memory, never DB.
        bucket_key = hashlib.sha256(
            (request.headers.get("X-Forwarded-For", request.remote_addr or "local")).encode()
        ).hexdigest()[:16]
        now = time.time()
        bucket = _flood_buckets[bucket_key]
        _flood_buckets[bucket_key] = [t for t in bucket if now - t < config.FLOOD_WINDOW_SECONDS]
        if len(_flood_buckets[bucket_key]) >= config.FLOOD_MAX_PER_WINDOW:
            return jsonify({"ok": False, "error": "too_many_requests"}), 429
        _flood_buckets[bucket_key].append(now)

        try:
            raw = request.get_json(force=True, silent=False)
        except Exception:
            return jsonify({"ok": False, "error": "invalid_json"}), 400

        try:
            answers = validate.validate_payload(raw)
            # Public production path: ignore client dataset unless CASTDEV_ALLOW_TEST_SUBMIT=1
            import os

            if os.environ.get("CASTDEV_ALLOW_TEST_SUBMIT", "").lower() in ("1", "true"):
                dataset: Dataset = validate.resolve_dataset(raw)  # type: ignore[assignment]
            else:
                dataset = "production"
            submit_token = raw.get("submit_token") if isinstance(raw, dict) else None
            if submit_token is not None and not isinstance(submit_token, str):
                submit_token = None
            if submit_token and len(submit_token) > 128:
                submit_token = submit_token[:128]
        except validate.ValidationError as e:
            return jsonify({"ok": False, "error": e.code, "message": e.message}), 400

        content_hash = hashlib.sha256(
            "|".join([answers["q1"], answers["q2"], answers["q3"], answers["q4"]]).encode(
                "utf-8"
            )
        ).hexdigest()
        features = classify.classify_response(
            answers["q1"], answers["q2"], answers["q3"], answers["q4"]
        )

        try:
            with db.session(dataset) as conn:
                # Note: production and test are separate files; dataset column still set.
                rid = db.insert_response(
                    conn,
                    q1=answers["q1"],
                    q2=answers["q2"],
                    q3=answers["q3"],
                    q4=answers["q4"],
                    dataset=dataset,
                    content_hash=content_hash,
                    client_submit_token=submit_token,
                    classifications=features,
                )
        except Exception:
            app.logger.exception("submit_failed")
            return jsonify({"ok": False, "error": "server_error"}), 500

        # Never echo answer texts back
        return jsonify({"ok": True, "response_id": rid}), 201

    @app.get("/api/castdev/health")
    def health():
        from . import __version__

        return jsonify({"ok": True, "service": "castdev0926", "version": __version__})

    # ----- Analyst API (ChatGPT / Ёжик) — Bearer token, read-only -----
    analyst_api.register_analyst_routes(app, _flood_buckets)

    # ----- Admin session helpers -----
    def _admin_conn():
        return db.connect(config.DB_PATH)

    def _is_admin() -> bool:
        sid = request.cookies.get(config.ADMIN_COOKIE_NAME)
        conn = _admin_conn()
        try:
            return db.validate_admin_session(conn, sid)
        finally:
            conn.close()

    def _require_admin():
        if not _is_admin():
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        return None

    def _set_session_cookie(resp, session_id: str, csrf: str):
        resp.set_cookie(
            config.ADMIN_COOKIE_NAME,
            session_id,
            httponly=True,
            secure=request.is_secure,
            samesite="Strict",
            max_age=config.ADMIN_SESSION_HOURS * 3600,
            path="/",
        )
        resp.set_cookie(
            config.ADMIN_CSRF_COOKIE,
            csrf,
            httponly=False,
            secure=request.is_secure,
            samesite="Strict",
            max_age=config.ADMIN_SESSION_HOURS * 3600,
            path="/",
        )

    def _consteq(a: str | None, b: str | None) -> bool:
        """Constant-time compare; never raise on length/type mismatch (pre-3.12 ValueError)."""
        if a is None or b is None:
            return False
        try:
            return hmac.compare_digest(str(a), str(b))
        except (TypeError, ValueError):
            return False

    def _check_csrf() -> bool:
        cookie = request.cookies.get(config.ADMIN_CSRF_COOKIE)
        header = request.headers.get("X-CSRF-Token")
        if not cookie or not header:
            return False
        return _consteq(cookie, header)

    # Soft presence check for admin button (does not leak data)
    @app.get("/api/admin/session")
    def admin_session_status():
        # Optional force source for local/dev smoke (never exposes English "production")
        import os

        forced = (os.environ.get("CASTDEV_ADMIN_FORCE_DATASET") or "").strip()
        data_source = "test" if forced == "test" else "production"
        show_test = bool(config.ALLOW_TEST_SUBMIT) or forced == "test"
        return jsonify(
            {
                "ok": True,
                "authenticated": _is_admin(),
                "data_source": data_source,
                "show_test_toggle": show_test,
            }
        )

    # One-time browser activation for Tatiana
    @app.post("/api/admin/activate")
    def admin_activate():
        # Brute-force soft limit
        key = "activate:" + hashlib.sha256(
            (request.remote_addr or "x").encode()
        ).hexdigest()[:12]
        now = time.time()
        _flood_buckets[key] = [t for t in _flood_buckets[key] if now - t < 300]
        if len(_flood_buckets[key]) >= 8:
            return jsonify({"ok": False, "error": "too_many_attempts"}), 429
        _flood_buckets[key].append(now)

        try:
            raw = request.get_json(force=True, silent=True) or {}
        except Exception:
            raw = {}
        token = raw.get("token") or request.args.get("token") or ""
        conn = _admin_conn()
        try:
            ok = _consteq(str(token), config.ADMIN_ACTIVATION_TOKEN)
            try:
                conn.execute(
                    "INSERT INTO admin_activation_log(created_at, ok, note) VALUES (?, ?, ?)",
                    (
                        __import__("datetime")
                        .datetime.now(__import__("datetime").timezone.utc)
                        .replace(microsecond=0)
                        .isoformat(),
                        1 if ok else 0,
                        "activate",
                    ),
                )
            except Exception:
                app.logger.exception("admin_activation_log_failed")
                # Do not fail closed on logging alone when token is invalid
                if not ok:
                    return jsonify({"ok": False, "error": "invalid_token"}), 403
                return jsonify({"ok": False, "error": "server_error"}), 500
            if not ok:
                return jsonify({"ok": False, "error": "invalid_token"}), 403
            try:
                sess = db.create_admin_session(conn)
            except Exception:
                app.logger.exception("admin_activate_session_failed")
                return jsonify({"ok": False, "error": "server_error"}), 500
            csrf = secrets.token_urlsafe(24)
            resp = make_response(
                jsonify(
                    {
                        "ok": True,
                        "expires_at": sess["expires_at"],
                        "message": "Браузер активирован для административного доступа.",
                    }
                )
            )
            _set_session_cookie(resp, sess["session_id"], csrf)
            return resp
        finally:
            conn.close()

    @app.post("/api/admin/logout")
    def admin_logout():
        sid = request.cookies.get(config.ADMIN_COOKIE_NAME)
        conn = _admin_conn()
        try:
            db.revoke_admin_session(conn, sid)
        finally:
            conn.close()
        resp = make_response(jsonify({"ok": True}))
        resp.set_cookie(config.ADMIN_COOKIE_NAME, "", expires=0, path="/")
        resp.set_cookie(config.ADMIN_CSRF_COOKIE, "", expires=0, path="/")
        return resp

    @app.post("/api/admin/revoke-all")
    def admin_revoke_all():
        denied = _require_admin()
        if denied:
            return denied
        if not _check_csrf():
            return jsonify({"ok": False, "error": "csrf"}), 403
        conn = _admin_conn()
        try:
            n = db.revoke_all_admin_sessions(conn)
            return jsonify({"ok": True, "revoked": n})
        finally:
            conn.close()

    def _dataset_from_request() -> Dataset:
        import os

        forced = (os.environ.get("CASTDEV_ADMIN_FORCE_DATASET") or "").strip()
        if forced == "test":
            return "test"
        ds = request.args.get("dataset") or (request.get_json(silent=True) or {}).get(
            "dataset"
        )
        # Test source only when explicitly allowed (dev/selftest) or forced
        if ds == "test" and (config.ALLOW_TEST_SUBMIT or forced == "test"):
            return "test"
        return "production"

    @app.get("/api/admin/summary")
    def admin_summary():
        denied = _require_admin()
        if denied:
            return denied
        dataset = _dataset_from_request()
        with db.session(dataset) as conn:
            sm = cabinet.build_cabinet(conn, dataset)
            sm["ok"] = True
            return jsonify(sm)

    @app.get("/api/admin/answers")
    def admin_answers():
        denied = _require_admin()
        if denied:
            return denied
        dataset = _dataset_from_request()
        qf = request.args.get("question") or "all"
        with db.session(dataset) as conn:
            table = cabinet.answers_table(conn, dataset, question=qf)
            table["ok"] = True
            return jsonify(table)

    @app.post("/api/admin/ask")
    def admin_ask():
        denied = _require_admin()
        if denied:
            return denied
        if not _check_csrf():
            return jsonify({"ok": False, "error": "csrf"}), 403
        raw = request.get_json(silent=True) or {}
        question = raw.get("question", "")
        dataset = _dataset_from_request()
        if raw.get("dataset") == "test" and config.ALLOW_TEST_SUBMIT:
            dataset = "test"
        with db.session(dataset) as conn:
            result = analyst.answer(conn, question, dataset=dataset)
            return jsonify(result)

    @app.get("/api/admin/export")
    def admin_export():
        """Protected analyst data export (auth required). Not a public raw endpoint."""
        denied = _require_admin()
        if denied:
            return denied
        dataset = _dataset_from_request()
        fmt = (request.args.get("format") or "json").lower()
        with db.session(dataset) as conn:
            if fmt == "csv":
                text = cabinet.export_csv_text(conn, dataset)
                resp = make_response(text)
                resp.headers["Content-Type"] = "text/csv; charset=utf-8"
                resp.headers["Content-Disposition"] = (
                    'attachment; filename="castdev0926-export.csv"'
                )
                return resp
            payload = cabinet.export_payload(conn, dataset, fmt="json")
            return jsonify(payload)

    @app.get("/api/admin/snapshot")
    def admin_snapshot():
        """Backward-compatible alias → export (no Cursor/LLM integration fields)."""
        denied = _require_admin()
        if denied:
            return denied
        dataset = _dataset_from_request()
        with db.session(dataset) as conn:
            payload = cabinet.export_payload(conn, dataset, fmt="json")
            return jsonify(payload)

    # Admin UI pages — no data without session; page shell may load but APIs 401
    @app.get("/admin")
    def admin_page():
        return render_template("admin.html")

    @app.get("/admin/activate")
    def admin_activate_page():
        return render_template("activate.html")

    @app.get("/admin/static/<path:filename>")
    def admin_static(filename: str):
        return send_from_directory(config.ADMIN_STATIC, filename)

    # Error handlers — no stack traces
    @app.errorhandler(404)
    def not_found(_e):
        return jsonify({"ok": False, "error": "not_found"}), 404

    @app.errorhandler(500)
    def server_error(_e):
        return jsonify({"ok": False, "error": "server_error"}), 500

    return app
