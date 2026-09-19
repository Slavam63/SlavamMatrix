"""Protected READ-ONLY Analytics API for Главный Аналитик (ChatGPT / Ёжик).

Auth: Authorization: Bearer <CASTDEV_ANALYST_API_TOKEN> (header only).
OpenAPI schema at /api/analyst/v1/openapi.json is public (no secrets) so Custom GPT
Actions can Import from URL; all data endpoints require Bearer.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

from flask import Flask, Response, jsonify, request

from . import cabinet, config, db, stats
from .db import Dataset

ANALYST_RULES_SHORT = [
    "1. Источник истины — RAW ответы q1–q4 в базе CASTDEV09.26; не подменять рыночными знаниями.",
    "2. Derived (признаки/темы) — интерпретация правил классификации, не замена RAW.",
    "3. Явно различать raw vs derived в формулировках.",
    "4. Multi-label: у одной анкеты может быть несколько признаков на вопрос.",
    "5. Единица анализа — целая анонимная анкета (q1–q4 вместе), не изолированный ответ.",
    "6. Числа всегда с N и долей (числитель/знаменатель/%).",
    "7. Малая выборка: не обобщать на рынок; указывать ограничения.",
    "8. Гипотезы отделять от фактов словами «можно предположить».",
    "9. Утверждения подтверждать evidence (RAW цитаты / survey_id).",
    "10. Production и test никогда не смешивать.",
    "11. Сначала aggregates → группы → evidence; полный dump — только по необходимости.",
    "12. READ ONLY: не мутировать данные, админку Татьяны и публичный опрос.",
]


def _consteq(a: str | None, b: str | None) -> bool:
    if a is None or b is None:
        return False
    try:
        return hmac.compare_digest(str(a), str(b))
    except (TypeError, ValueError):
        return False


def _bearer_token() -> str | None:
    """Extract Bearer token from Authorization header only (never query string)."""
    # Reject query-string token attempts explicitly
    if request.args.get("token") or request.args.get("api_key") or request.args.get("access_token"):
        return None
    auth = request.headers.get("Authorization") or ""
    parts = auth.split(None, 1)
    if len(parts) != 2:
        return None
    scheme, value = parts[0], parts[1].strip()
    if scheme.lower() != "bearer" or not value:
        return None
    return value


def register_analyst_routes(app: Flask, flood_buckets: dict[str, list[float]]) -> None:
    """Wire /api/analyst/v1/* onto the Flask app. Does not touch admin UI routes."""

    def _audit(op_type: str, endpoint: str, success: bool, note: str | None = None) -> None:
        try:
            with db.session("production") as conn:
                db.log_analyst_audit(
                    conn, op_type=op_type, endpoint=endpoint, success=success, note=note
                )
        except Exception:
            app.logger.exception("analyst_audit_failed")

    def _rate_limit() -> Response | None:
        key = "analyst:" + hashlib.sha256(
            (request.headers.get("X-Forwarded-For", request.remote_addr or "x")).encode()
        ).hexdigest()[:16]
        now = time.time()
        window = config.ANALYST_FLOOD_WINDOW_SECONDS
        flood_buckets[key] = [t for t in flood_buckets[key] if now - t < window]
        if len(flood_buckets[key]) >= config.ANALYST_FLOOD_MAX_PER_WINDOW:
            _audit("rate_limit", request.path, False, "429")
            return jsonify({"ok": False, "error": "too_many_requests"}), 429
        flood_buckets[key].append(now)
        return None

    def _require_analyst() -> Response | None:
        limited = _rate_limit()
        if limited:
            return limited
        expected = config.ANALYST_API_TOKEN or ""
        if not expected:
            _audit("auth", request.path, False, "token_not_configured")
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        provided = _bearer_token()
        if provided is None:
            # Query-string token attempt or missing/malformed header
            if request.args.get("token") or request.args.get("api_key") or request.args.get(
                "access_token"
            ):
                _audit("auth", request.path, False, "query_token_rejected")
                return jsonify({"ok": False, "error": "unauthorized"}), 401
            _audit("auth", request.path, False, "missing_bearer")
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        if not _consteq(provided, expected):
            _audit("auth", request.path, False, "invalid_token")
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        return None

    def _dataset_param() -> Dataset | Response:
        ds = (request.args.get("dataset") or "production").strip().lower()
        if ds == "production":
            return "production"
        if ds == "test":
            # Allow reading test dataset when ALLOW_TEST_SUBMIT or explicit env;
            # production ops may still query test DB file if it exists (isolated file).
            return "test"
        return jsonify({"ok": False, "error": "invalid_dataset"}), 400

    def _envelope(**extra: Any) -> dict[str, Any]:
        body = {
            "ok": True,
            "api_version": config.ANALYST_API_VERSION,
            "service": "castdev0926-analyst",
            "layer_note": "raw=q1-q4 verbatim; derived=classifications/themes",
        }
        body.update(extra)
        return body

    def _strip_token_leak(payload: dict[str, Any]) -> dict[str, Any]:
        """Defense: never echo Authorization or env token keys."""
        banned = {
            "token",
            "authorization",
            "CASTDEV_ANALYST_API_TOKEN",
            "api_token",
            "bearer",
        }
        return {k: v for k, v in payload.items() if k not in banned}

    # ----- OpenAPI (public schema — no secrets; GPT Actions can Import from URL) -----
    @app.get("/api/analyst/v1/openapi.json")
    def analyst_openapi():
        path = config.ANALYST_OPENAPI_PATH
        if not path.is_file():
            return jsonify({"ok": False, "error": "openapi_missing"}), 500
        data = json.loads(path.read_text(encoding="utf-8"))
        resp = jsonify(data)
        resp.headers["Cache-Control"] = "public, max-age=300"
        # Explicitly no CORS * (ChatGPT Actions call server-side)
        return resp

    @app.get("/api/analyst/v1/rules")
    def analyst_rules():
        denied = _require_analyst()
        if denied:
            return denied
        text = ""
        if config.ANALYST_RULES_PATH.is_file():
            text = config.ANALYST_RULES_PATH.read_text(encoding="utf-8")
        payload = _envelope(
            rules=ANALYST_RULES_SHORT,
            rules_document=text[:8000] if text else None,
        )
        _audit("rules", request.path, True)
        return jsonify(_strip_token_leak(payload))

    @app.get("/api/analyst/v1/status")
    def analyst_status():
        denied = _require_analyst()
        if denied:
            return denied
        ds = _dataset_param()
        if not isinstance(ds, str):
            return ds
        with db.session(ds) as conn:
            total = db.count_responses(conn, ds)
            latest = db.latest_created_at(conn, ds)
            derived = db.derived_status(conn, ds)
            schema_v = db.meta_get(conn, "schema_version") or "1"
        payload = _envelope(
            dataset=ds,
            count=total,
            last_answer=latest,
            last_answer_display=stats.format_msk(latest),
            schema_version=schema_v,
            api_version=config.ANALYST_API_VERSION,
            derived=derived,
            rules_summary=ANALYST_RULES_SHORT,
            read_only=True,
        )
        _audit("status", request.path, True, f"dataset={ds};n={total}")
        return jsonify(_strip_token_leak(payload))

    @app.get("/api/analyst/v1/responses")
    def analyst_responses():
        denied = _require_analyst()
        if denied:
            return denied
        ds = _dataset_param()
        if not isinstance(ds, str):
            return ds
        try:
            limit = int(request.args.get("limit") or config.ANALYST_DEFAULT_PAGE_LIMIT)
            offset = int(request.args.get("offset") or 0)
        except ValueError:
            return jsonify({"ok": False, "error": "malformed_params"}), 400
        limit = max(1, min(limit, config.ANALYST_MAX_PAGE_LIMIT))
        offset = max(0, offset)
        since = request.args.get("since") or None
        until = request.args.get("until") or None
        ids_raw = request.args.get("ids") or ""
        ids = [x.strip() for x in ids_raw.split(",") if x.strip()] if ids_raw else None
        if ids and len(ids) > 200:
            return jsonify({"ok": False, "error": "too_many_ids"}), 400
        with db.session(ds) as conn:
            items, total = db.fetch_responses_page(
                conn,
                ds,
                limit=limit,
                offset=offset,
                since=since,
                until=until,
                ids=ids,
            )
        payload = _envelope(
            dataset=ds,
            total=total,
            limit=limit,
            offset=offset,
            count=len(items),
            items=items,
            data_kind="raw",
        )
        _audit("responses", request.path, True, f"dataset={ds};n={len(items)}")
        return jsonify(_strip_token_leak(payload))

    @app.get("/api/analyst/v1/derived")
    def analyst_derived():
        denied = _require_analyst()
        if denied:
            return denied
        ds = _dataset_param()
        if not isinstance(ds, str):
            return ds
        rid = request.args.get("response_id") or request.args.get("survey_id") or None
        question = request.args.get("question") or None
        feature_key = request.args.get("feature_key") or None
        feature_value = request.args.get("feature_value") or None
        if question and question not in ("q1", "q2", "q3", "q4", "cross"):
            return jsonify({"ok": False, "error": "invalid_question"}), 400
        with db.session(ds) as conn:
            rows = db.fetch_classifications_filtered(
                conn,
                ds,
                response_id=rid,
                question=question,
                feature_key=feature_key,
                feature_value=feature_value,
            )
            themes = cabinet.theme_summaries(conn, ds)
            # Strip heavy sources from themes here — evidence endpoint owns citations
            themes_light = {}
            for qn, block in themes.items():
                themes_light[qn] = {
                    "question": block["question"],
                    "title": block["title"],
                    "total": block["total"],
                    "themes": [
                        {
                            "feature_key": t["feature_key"],
                            "feature_value": t["feature_value"],
                            "label": t["label"],
                            "count": t["count"],
                            "share": t["share"],
                            "response_ids": t["response_ids"],
                        }
                        for t in block["themes"]
                    ],
                }
        payload = _envelope(
            dataset=ds,
            data_kind="derived",
            multi_label=True,
            classifications=rows,
            themes=themes_light,
            note="classifications=derived features; themes=aggregated derived; RAW not mutated",
        )
        _audit("derived", request.path, True, f"dataset={ds};n={len(rows)}")
        return jsonify(_strip_token_leak(payload))

    @app.get("/api/analyst/v1/aggregates")
    def analyst_aggregates():
        denied = _require_analyst()
        if denied:
            return denied
        ds = _dataset_param()
        if not isinstance(ds, str):
            return ds
        include_cross = (request.args.get("cross") or "1").lower() not in ("0", "false", "no")
        feature_key = request.args.get("feature_key") or None
        feature_value = request.args.get("feature_value") or None
        question = request.args.get("question") or None
        with db.session(ds) as conn:
            total = stats.total_count(conn, ds)
            features = stats.feature_stats(conn, ds)
            themes = cabinet.theme_summaries(conn, ds)
            themes_agg = {
                qn: {
                    "question": block["question"],
                    "title": block["title"],
                    "total": block["total"],
                    "themes": [
                        {
                            "feature_key": t["feature_key"],
                            "feature_value": t["feature_value"],
                            "label": t["label"],
                            "count": t["count"],
                            "share": t["share"],
                            "display": t["display"],
                            "response_ids": t["response_ids"],
                        }
                        for t in block["themes"]
                    ],
                }
                for qn, block in themes.items()
            }
            hh = stats.opposing_stances(conn, "hh", ds)
            period_7d = stats.period_count(conn, ds, days=7)
            inflow = stats.inflow_dynamics(conn, ds)
            cross = cabinet.cross_questionnaire(conn, ds) if include_cross else None
            if cross:
                # Drop nested RAW sources from aggregates (use /evidence)
                cross = {
                    "total": cross["total"],
                    "note": cross["note"],
                    "contradiction": cross["contradiction"],
                    "links": [
                        {
                            "a": ln["a"],
                            "b": ln["b"],
                            "count": ln["count"],
                            "share": ln["share"],
                            "display": ln["display"],
                            "response_ids": ln["response_ids"],
                        }
                        for ln in cross["links"]
                    ],
                }
            filtered_ids: list[str] | None = None
            if feature_key and feature_value:
                filtered_ids = sorted(
                    {
                        c["response_id"]
                        for c in db.fetch_classifications_filtered(
                            conn,
                            ds,
                            question=question,
                            feature_key=feature_key,
                            feature_value=feature_value,
                        )
                    }
                )
                filter_share = stats.pct(len(filtered_ids), total)
            else:
                filter_share = None
        payload = _envelope(
            dataset=ds,
            data_kind="aggregates",
            total=total,
            features=features,
            themes=themes_agg,
            hh_stances=hh,
            period_7d=period_7d,
            inflow=inflow,
            cross=cross,
            filter={
                "feature_key": feature_key,
                "feature_value": feature_value,
                "question": question,
                "response_ids": filtered_ids,
                "share": filter_share,
            }
            if feature_key and feature_value
            else None,
            analytical_hint="Prefer aggregates first; request /evidence for confirming RAW.",
        )
        _audit("aggregates", request.path, True, f"dataset={ds};total={total}")
        return jsonify(_strip_token_leak(payload))

    @app.get("/api/analyst/v1/evidence")
    def analyst_evidence():
        denied = _require_analyst()
        if denied:
            return denied
        ds = _dataset_param()
        if not isinstance(ds, str):
            return ds
        feature_key = request.args.get("feature_key")
        feature_value = request.args.get("feature_value")
        question = request.args.get("question") or None
        ids_raw = request.args.get("ids") or ""
        ids = [x.strip() for x in ids_raw.split(",") if x.strip()] if ids_raw else None
        try:
            limit = int(request.args.get("limit") or 20)
        except ValueError:
            return jsonify({"ok": False, "error": "malformed_params"}), 400
        limit = max(1, min(limit, 100))
        if not feature_key and not feature_value and not ids:
            return jsonify(
                {
                    "ok": False,
                    "error": "need_feature_or_ids",
                    "message": "Provide feature_key+feature_value and/or ids=",
                }
            ), 400
        with db.session(ds) as conn:
            responses = {r["response_id"]: r for r in db.fetch_all_responses(conn, ds)}
            match_ids: set[str] = set()
            if feature_key and feature_value:
                for c in db.fetch_classifications_filtered(
                    conn,
                    ds,
                    question=question,
                    feature_key=feature_key,
                    feature_value=feature_value,
                ):
                    match_ids.add(c["response_id"])
            if ids:
                if match_ids:
                    match_ids &= set(ids)
                else:
                    match_ids = set(ids)
            ordered = sorted(match_ids)[:limit]
            items = []
            for rid in ordered:
                r = responses.get(rid)
                if not r:
                    continue
                items.append(
                    {
                        "survey_id": rid,
                        "response_id": rid,
                        "submitted_at": r["created_at"],
                        "submitted_at_display": stats.format_msk(r["created_at"]),
                        "q1": r["q1"],
                        "q2": r["q2"],
                        "q3": r["q3"],
                        "q4": r["q4"],
                        "focus_text": r[question] if question in ("q1", "q2", "q3", "q4") else None,
                    }
                )
        payload = _envelope(
            dataset=ds,
            data_kind="evidence",
            feature_key=feature_key,
            feature_value=feature_value,
            question=question,
            matched=len(match_ids),
            returned=len(items),
            items=items,
            note="Confirming anonymous RAW answers for conclusions; not PII.",
        )
        _audit("evidence", request.path, True, f"dataset={ds};n={len(items)}")
        return jsonify(_strip_token_leak(payload))

    # Explicit read-only: reject mutating methods on analyst namespace
    @app.route(
        "/api/analyst/v1/<path:subpath>",
        methods=["POST", "PUT", "PATCH", "DELETE"],
    )
    def analyst_mutate_blocked(subpath: str):
        _audit("mutate_blocked", request.path, False, request.method)
        return jsonify({"ok": False, "error": "read_only", "method": request.method}), 405
