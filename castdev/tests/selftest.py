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
os.environ.setdefault(
    "CASTDEV_ANALYST_API_TOKEN", "test-analyst-token-op11-selftest-only"
)

from castdev import classify, config, db, stats, analyst  # noqa: E402
from castdev.seed_test import seed_test, TEST_RESPONSES  # noqa: E402
from castdev.app import create_app  # noqa: E402
from castdev import cabinet  # noqa: E402

TEST_N = len(TEST_RESPONSES)

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
    results.append(check("seed_test_count", seeded["count"] == TEST_N, str(seeded["count"])))

    with db.session("test") as conn:
        total = stats.total_count(conn, "test")
        results.append(check("stats_total", total == TEST_N, str(total)))

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
        results.append(check("period_count_30d", pc["count"] == TEST_N, str(pc)))

        # MSK display
        latest = db.latest_created_at(conn, "test")
        latest_disp = stats.format_msk(latest)
        results.append(
            check(
                "format_msk_shape",
                bool(latest_disp)
                and " в " in latest_disp
                and "(мск)" in latest_disp
                and "T" not in latest_disp,
                str(latest_disp),
            )
        )
        cab = cabinet.build_cabinet(conn, "test")
        results.append(
            check(
                "cabinet_themes_and_answers",
                isinstance(cab.get("themes"), dict)
                and "q1" in cab["themes"]
                and cab["themes"]["q1"]["themes"]
                and cab.get("answers_all", {}).get("rows")
                and len(cab["answers_all"]["rows"]) == TEST_N
                and cab.get("cross", {}).get("links") is not None
                and cab.get("latest_display")
                and "(мск)" in (cab.get("latest_display") or ""),
                f"themes={len(cab.get('themes',{}))} rows={len(cab.get('answers_all',{}).get('rows',[]))}",
            )
        )
        # Dynamic columns from data for q1
        q1_table = cabinet.answers_table(conn, "test", question="q1")
        results.append(
            check(
                "dynamic_feature_columns",
                len(q1_table.get("columns") or []) >= 1
                and any(
                    row.get("cells") and any(row["cells"].values())
                    for row in q1_table.get("rows") or []
                ),
                f"cols={len(q1_table.get('columns') or [])}",
            )
        )
        q2_title = (cab.get("question_titles") or {}).get("q2", "")
        results.append(
            check(
                "no_voopros_typo",
                "Воопрос" not in q2_title and q2_title == "Вопрос 2",
                q2_title,
            )
        )

        # Analyst QA types
        for q, kind_hint in [
            ("Сколько всего анкет?", "quantitative"),
            ("Как относятся к HH?", "channel"),
            ("Покажи характерные цитаты по q1", "quotes"),
            ("Какая динамика поступления?", "trend"),
            ("Есть ли противоречия?", "contradiction"),
            ("Какие сочетания признаков между вопросами?", "cross"),
            ("Сколько респондентов с Марса?", "insufficient"),
        ]:
            ans = analyst.answer(conn, q, dataset="test")
            text = ans.get("answer_text") or ""
            results.append(
                check(
                    f"analyst_{kind_hint}",
                    ans.get("ok") and ans.get("total_responses") == TEST_N,
                    text[:120],
                )
            )
            results.append(
                check(
                    f"analyst_{kind_hint}_memo",
                    "Короткий вывод" in text
                    and "Что видно в данных" in text
                    and "Сколько человек" in text
                    and "Характерные ответы" in text
                    and "Что можно предположить" in text
                    and "Ограничения" in text,
                    text[:280],
                )
            )
            results.append(
                check(
                    f"analyst_{kind_hint}_no_llm_junk",
                    "CASTDEV_LLM_API_KEY" not in text
                    and "_llm_enrich" not in text
                    and "/api/admin/snapshot" not in text
                    and "Cursor" not in text
                    and not ans.get("capability_note"),
                    str(ans.get("capability_note")),
                )
            )
            if kind_hint == "insufficient":
                results.append(
                    check(
                        "analyst_insufficient_honest",
                        "недостаточно" in text.lower()
                        or "нет данных" in text.lower()
                        or "данных нет" in text.lower(),
                        text[:160],
                    )
                )
            if kind_hint == "channel":
                results.append(
                    check(
                        "analyst_hh_has_denom",
                        "из" in text and "%" in text,
                        text[:200],
                    )
                )
                results.append(
                    check(
                        "analyst_hh_russian_stances",
                        "позитив" in text.lower()
                        or "негатив" in text.lower()
                        or "отказал" in text.lower(),
                        text[:240],
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

    # Snapshot / export (protected)
    snap = client.get("/api/admin/snapshot?dataset=test")
    snap_body = snap.get_json() or {}
    results.append(
        check(
            "snapshot_alias_export",
            snap.status_code == 200
            and snap_body.get("total", 0) >= TEST_N
            and "integration_point" not in snap_body
            and "CASTDEV_LLM" not in json.dumps(snap_body),
            {"total": snap_body.get("total"), "keys": list(snap_body.keys())[:12]},
        )
    )
    exp = client.get("/api/admin/export?format=json&dataset=test")
    exp_body = exp.get_json() or {}
    results.append(
        check(
            "admin_export_json",
            exp.status_code == 200
            and exp_body.get("ok")
            and exp_body.get("total", 0) >= TEST_N
            and "themes" in exp_body
            and "responses" in exp_body,
            {"total": exp_body.get("total")},
        )
    )
    exp_csv = client.get("/api/admin/export?format=csv&dataset=test")
    results.append(
        check(
            "admin_export_csv",
            exp_csv.status_code == 200
            and "text/csv" in (exp_csv.headers.get("Content-Type") or "")
            and b"q1" in exp_csv.data,
            exp_csv.headers.get("Content-Type"),
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
    admin_html = client.get("/admin").get_data(as_text=True)
    results.append(
        check(
            "admin_ui_cabinet_labels",
            "Кабинет аналитика" in admin_html
            and "Массив" not in admin_html
            and "Сводка" in admin_html
            and "Темы по вопросам" in admin_html
            and "Ответы и признаки" in admin_html
            and "Связи между вопросами" in admin_html
            and "Спросить Кастдева" in admin_html
            and "Выгрузить данные" in admin_html
            and "snapshot" not in admin_html.lower()
            and "Воопрос" not in admin_html,
            "cabinet chrome",
        )
    )
    results.append(
        check(
            "admin_ui_no_capability_note_slot",
            "capability-note" not in admin_html
            and "_llm_enrich" not in admin_html
            and "LLM API" not in admin_html,
            "junk removed from template",
        )
    )
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

    # --- Op11 Analyst API smoke (full matrix in test_analyst_api.py) ---
    analyst_token = os.environ.get("CASTDEV_ANALYST_API_TOKEN") or ""
    oa = client.get("/api/analyst/v1/openapi.json")
    results.append(
        check(
            "analyst_openapi_public",
            oa.status_code == 200
            and (oa.get_json() or {}).get("openapi", "").startswith("3."),
            oa.status_code,
        )
    )
    no_a = client.get("/api/analyst/v1/status?dataset=test")
    results.append(check("analyst_no_auth_401", no_a.status_code == 401))
    ok_a = client.get(
        "/api/analyst/v1/status?dataset=test",
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    okj = ok_a.get_json() or {}
    with db.session("test") as _ac:
        test_n_now = db.count_responses(_ac, "test")
    results.append(
        check(
            "analyst_bearer_status",
            ok_a.status_code == 200
            and okj.get("ok")
            and okj.get("count") == test_n_now
            and okj.get("count") >= TEST_N
            and analyst_token not in (ok_a.get_data(as_text=True) or ""),
            {"count": okj.get("count"), "db": test_n_now},
        )
    )
    agg_a = client.get(
        "/api/analyst/v1/aggregates?dataset=test",
        headers={"Authorization": f"Bearer {analyst_token}"},
    )
    results.append(
        check(
            "analyst_aggregates",
            agg_a.status_code == 200 and (agg_a.get_json() or {}).get("cross") is not None,
            agg_a.status_code,
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
    results.append(check("backup_restore_test_copy", n >= TEST_N, f"restored_count={n}"))

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
            "total_expected": TEST_N,
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
