#!/usr/bin/env python3
"""Self-test suite for CASTDEV Op9: classify, stats EXPECTED vs ACTUAL, API, security."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

# Ensure repo root on path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

os.environ["CASTDEV_DATA_DIR"] = str(ROOT / "data")
os.environ["CASTDEV_ADMIN_ACTIVATION_TOKEN"] = "test-activation-token-op9"
os.environ["CASTDEV_ADMIN_SESSION_SECRET"] = "test-session-secret-op9"
os.environ["CASTDEV_ALLOW_TEST_SUBMIT"] = "1"
# Force fresh paths under temp for isolation of some tests — use project data for integration

from castdev import classify, config, db, stats, analyst  # noqa: E402
from castdev.seed_test import seed_test, TEST_RESPONSES  # noqa: E402
from castdev.app import create_app  # noqa: E402


def check(name: str, cond: bool, detail: str = "") -> dict:
    return {"name": name, "pass": bool(cond), "detail": detail}


def expected_hh_stances():
    """Manual EXPECTED from TEST_RESPONSES semantic reading."""
    # Index 0: positive_use HH
    # Index 1: negative_while_using HH
    # Index 2: abandoned HH
    # Index 3: LinkedIn positive, HH almost not — may not count as HH stance
    # Index 8: positive in q1, abandoned in q4 (cross contradiction)
    return {
        "total": len(TEST_RESPONSES),
        "hh_positive_use_min": 1,  # at least resp 0
        "hh_negative_while_using_min": 1,  # resp 1
        "hh_abandoned_min": 1,  # resp 2 (and possibly 8 in q4)
        "distinct_stances": True,
    }


def run() -> dict:
    results = []
    config.ensure_dirs()
    db.init_all()

    # --- Classification: NOT keyword-only ---
    a = classify.classify_channel_stances(
        "HH использую и получаю отклики", "q1"
    )
    b = classify.classify_channel_stances(
        "HH использую, но считаю бесполезным", "q1"
    )
    c = classify.classify_channel_stances(
        "HH больше вообще не использую", "q1"
    )
    va = a[0]["feature_value"] if a else None
    vb = b[0]["feature_value"] if b else None
    vc = c[0]["feature_value"] if c else None
    results.append(
        check(
            "semantic_hh_three_stances_differ",
            va == "positive_use"
            and vb == "negative_while_using"
            and vc == "abandoned"
            and len({va, vb, vc}) == 3,
            f"{va=} {vb=} {vc=}",
        )
    )

    # --- Seed TEST ---
    seeded = seed_test(wipe=True)
    results.append(check("seed_test_count", seeded["count"] == 10, str(seeded["count"])))

    with db.session("test") as conn:
        total = stats.total_count(conn, "test")
        results.append(check("stats_total", total == 10, str(total)))

        exp = expected_hh_stances()
        opp = stats.opposing_stances(conn, "hh", "test")
        results.append(
            check(
                "hh_positive_use",
                opp["positive_use"]["numerator"] >= exp["hh_positive_use_min"],
                opp["positive_use"]["display"],
            )
        )
        results.append(
            check(
                "hh_negative_while_using",
                opp["negative_while_using"]["numerator"] >= exp["hh_negative_while_using_min"],
                opp["negative_while_using"]["display"],
            )
        )
        results.append(
            check(
                "hh_abandoned",
                opp["abandoned"]["numerator"] >= exp["hh_abandoned_min"],
                opp["abandoned"]["display"],
            )
        )
        # Opposite stances must not collapse into one keyword bucket
        results.append(
            check(
                "hh_stances_not_collapsed",
                opp["positive_use"]["numerator"] != total
                or opp["abandoned"]["numerator"] > 0,
                json.dumps(
                    {
                        k: opp[k]["numerator"]
                        for k in (
                            "positive_use",
                            "negative_while_using",
                            "abandoned",
                            "mentioned_neutral",
                        )
                    }
                ),
            )
        )

        # Every percentage has numerator+denominator
        feat = stats.feature_stats(conn, "test")
        all_have_denom = all(
            "numerator" in f and "denominator" in f and f["denominator"] == total
            for f in feat["features"]
        )
        results.append(check("pct_has_numerator_denominator", all_have_denom, f"features={len(feat['features'])}"))

        # Intersection example: wants_change ∩ wants_keep possible
        inter = stats.intersection(
            conn,
            a=("intent", "wants_change"),
            b=("intent", "wants_keep"),
            dataset="test",
        )
        results.append(
            check(
                "intersection_shape",
                "numerator" in inter["intersection"]
                and "denominator" in inter["intersection"],
                inter["intersection"]["display"],
            )
        )

        # Period count
        pc = stats.period_count(conn, "test", days=30)
        results.append(check("period_count_30d", pc["count"] == 10, str(pc)))

        # Analyst QA types
        for q, kind_hint in [
            ("Сколько всего анкет?", "quantitative"),
            ("Как относятся к HH?", "channel"),
            ("Покажи характерные цитаты по q1", "quotes"),
            ("Какая динамика поступления?", "trend"),
            ("Есть ли противоречия?", "contradiction"),
            ("Сколько респондентов с Марса?", "insufficient"),
        ]:
            ans = analyst.answer(conn, q, dataset="test")
            results.append(
                check(
                    f"analyst_{kind_hint}",
                    ans.get("ok") and ans.get("total_responses") == 10,
                    (ans.get("answer_text") or "")[:120],
                )
            )
            if kind_hint == "insufficient":
                results.append(
                    check(
                        "analyst_insufficient_honest",
                        "недостаточно" in (ans.get("answer_text") or "").lower()
                        or "нет данных" in (ans.get("answer_text") or "").lower(),
                        ans.get("answer_text", "")[:160],
                    )
                )
            if kind_hint == "channel":
                # Must mention different stances / numerator
                text = ans.get("answer_text") or ""
                results.append(
                    check(
                        "analyst_hh_has_denom",
                        "из" in text and "%" in text,
                        text[:200],
                    )
                )
            quotes = ans.get("quotes") or []
            if kind_hint == "quotes":
                raw_ok = True
                responses = db.fetch_all_responses(conn, "test")
                raw_map = {r["response_id"]: r for r in responses}
                for qt in quotes:
                    r = raw_map.get(qt["response_id"])
                    if not r or qt["quote"] not in r[qt["question"]]:
                        raw_ok = False
                results.append(check("quotes_exist_in_raw", raw_ok, f"n={len(quotes)}"))

    # --- Flask API ---
    app = create_app()
    client = app.test_client()

    # Health
    h = client.get("/api/castdev/health")
    results.append(check("health", h.status_code == 200 and h.get_json()["ok"], str(h.status_code)))

    # Reject extra fields
    bad = client.post(
        "/api/castdev",
        json={"q1": "a", "q2": "b", "q3": "c", "q4": "d", "email": "x@y.z"},
    )
    results.append(check("reject_extra_fields", bad.status_code == 400, bad.get_json()))

    # Reject empty
    empty = client.post("/api/castdev", json={"q1": " ", "q2": "b", "q3": "c", "q4": "d"})
    results.append(check("reject_empty", empty.status_code == 400, empty.get_json()))

    # Accept unicode
    ok = client.post(
        "/api/castdev",
        json={
            "q1": "Ищу через знакомых — «сарафан» работает.",
            "q2": "Ориентир — содержание роли.",
            "q3": "Сложность в первом контакте.",
            "q4": "Менял бы активность; сеть сохраню.",
            "dataset": "test",
            "submit_token": "e2e-token-1",
        },
    )
    results.append(
        check(
            "accept_unicode_submit",
            ok.status_code == 201 and ok.get_json().get("ok") and "q1" not in (ok.get_json() or {}),
            ok.get_json(),
        )
    )

    # Double submit same token → same/success without new duplicate flood
    ok2 = client.post(
        "/api/castdev",
        json={
            "q1": "Ищу через знакомых — «сарафан» работает.",
            "q2": "Ориентир — содержание роли.",
            "q3": "Сложность в первом контакте.",
            "q4": "Менял бы активность; сеть сохраню.",
            "dataset": "test",
            "submit_token": "e2e-token-1",
        },
    )
    results.append(
        check(
            "dedup_submit_token",
            ok2.status_code == 201
            and ok2.get_json().get("response_id") == ok.get_json().get("response_id"),
            ok2.get_json(),
        )
    )

    # Admin API closed
    s = client.get("/api/admin/summary")
    results.append(check("admin_summary_unauthorized", s.status_code == 401, s.get_json()))
    ask = client.post("/api/admin/ask", json={"question": "Сколько анкет?"})
    results.append(check("admin_ask_unauthorized", ask.status_code == 401, ask.get_json()))

    # Activate
    act_bad = client.post("/api/admin/activate", json={"token": "wrong"})
    results.append(
        check(
            "activate_rejects_bad_token",
            act_bad.status_code == 403 and act_bad.get_json().get("error") == "invalid_token",
            act_bad.get_json(),
        )
    )
    # Wrong length must not become generic server_error (hmac.compare_digest ValueError on <3.12)
    act_short = client.post("/api/admin/activate", json={"token": "x"})
    results.append(
        check(
            "activate_rejects_short_token",
            act_short.status_code == 403
            and act_short.get_json().get("error") == "invalid_token",
            act_short.get_json(),
        )
    )
    act_empty = client.post("/api/admin/activate", json={"token": ""})
    results.append(
        check(
            "activate_rejects_empty_token",
            act_empty.status_code == 403
            and act_empty.get_json().get("error") == "invalid_token",
            act_empty.get_json(),
        )
    )
    act = client.post(
        "/api/admin/activate",
        json={"token": os.environ["CASTDEV_ADMIN_ACTIVATION_TOKEN"]},
    )
    results.append(check("activate_ok", act.status_code == 200 and act.get_json().get("ok"), act.get_json()))

    # Session cookie present
    sess = client.get("/api/admin/session")
    results.append(check("session_authenticated", sess.get_json().get("authenticated") is True, sess.get_json()))

    # CSRF required
    ask_nocsrf = client.post("/api/admin/ask", json={"question": "Сколько анкет?", "dataset": "test"})
    results.append(check("ask_requires_csrf", ask_nocsrf.status_code == 403, ask_nocsrf.get_json()))

    csrf = None
    # Flask 3 / Werkzeug: use get_cookie
    try:
        cobj = client.get_cookie(config.ADMIN_CSRF_COOKIE)
        if cobj is not None:
            csrf = cobj.value
    except Exception:
        csrf = None
    if not csrf:
        # Fallback: parse Set-Cookie from activate response
        for h in act.headers.getlist("Set-Cookie"):
            if config.ADMIN_CSRF_COOKIE + "=" in h:
                csrf = h.split(config.ADMIN_CSRF_COOKIE + "=", 1)[1].split(";", 1)[0]
    ask_ok = client.post(
        "/api/admin/ask",
        json={"question": "Как относятся к HH? Дай доли.", "dataset": "test"},
        headers={"X-CSRF-Token": csrf or ""},
    )
    body = ask_ok.get_json() or {}
    results.append(
        check(
            "ask_with_csrf",
            ask_ok.status_code == 200 and body.get("ok") and "из" in (body.get("answer_text") or ""),
            (body.get("answer_text") or "")[:180],
        )
    )

    # Snapshot
    snap = client.get("/api/admin/snapshot?dataset=test")
    results.append(
        check(
            "snapshot",
            snap.status_code == 200 and snap.get_json().get("total", 0) >= 10,
            {"total": (snap.get_json() or {}).get("total")},
        )
    )

    # Logout
    client.post("/api/admin/logout")
    sess2 = client.get("/api/admin/session")
    results.append(
        check(
            "logout_revokes",
            sess2.get_json().get("authenticated") is False,
            sess2.get_json(),
        )
    )

    # Public pages
    results.append(check("index_html", client.get("/").status_code == 200))
    results.append(check("admin_page", client.get("/admin").status_code == 200))
    html = client.get("/").get_data(as_text=True)
    results.append(
        check(
            "no_chess_alt_class",
            "question-layout--alt" not in html,
            "alt class removed",
        )
    )
    results.append(
        check(
            "approved_q1_text",
            "Как Вы сейчас ищете новую работу?" in html,
        )
    )
    results.append(
        check(
            "admin_entry_hidden_by_default",
            'id="admin-entry" hidden' in html or 'id="admin-entry"\n        hidden' in html or 'admin-entry" hidden' in html,
        )
    )

    # Backup / restore on test copy
    backup_dir = ROOT / "backups" / "selftest"
    backup_dir.mkdir(parents=True, exist_ok=True)
    src = config.TEST_DB_PATH
    bak = backup_dir / "castdev0926_test.sqlite"
    import sqlite3

    sqlite3.connect(str(src)).backup(sqlite3.connect(str(bak)))
    restore_dest = backup_dir / "castdev0926_test_restored.sqlite"
    if restore_dest.exists():
        restore_dest.unlink()
    sqlite3.connect(str(bak)).backup(sqlite3.connect(str(restore_dest)))
    conn_r = sqlite3.connect(str(restore_dest))
    n = conn_r.execute("SELECT COUNT(*) FROM responses").fetchone()[0]
    conn_r.close()
    results.append(check("backup_restore_test_copy", n >= 10, f"restored_count={n}"))

    # No IP columns in schema
    conn_s = sqlite3.connect(str(config.TEST_DB_PATH))
    cols = [r[1] for r in conn_s.execute("PRAGMA table_info(responses)").fetchall()]
    conn_s.close()
    results.append(
        check(
            "no_ip_in_research_schema",
            "ip" not in cols and "user_agent" not in cols and "referrer" not in cols,
            str(cols),
        )
    )

    passed = sum(1 for r in results if r["pass"])
    failed = [r for r in results if not r["pass"]]
    report = {
        "ok": len(failed) == 0,
        "passed": passed,
        "failed_count": len(failed),
        "total": len(results),
        "failed": failed,
        "results": results,
        "llm_available": analyst.llm_available(),
        "classification_note": classify.explain_not_keyword_only(),
        "expected_vs_actual": {
            "total_expected": 10,
            "total_actual": total,
            "hh_stances_actual": {
                k: opp[k]["display"]
                for k in (
                    "positive_use",
                    "negative_while_using",
                    "abandoned",
                    "mentioned_neutral",
                )
            },
        },
    }
    return report


if __name__ == "__main__":
    report = run()
    out = ROOT / "data" / "op9-selftest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "passed": report["passed"], "failed_count": report["failed_count"], "out": str(out)}, ensure_ascii=False))
    if report["failed"]:
        print("FAILED:", json.dumps(report["failed"], ensure_ascii=False, indent=2))
    sys.exit(0 if report["ok"] else 1)
