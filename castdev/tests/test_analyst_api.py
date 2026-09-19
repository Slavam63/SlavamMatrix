#!/usr/bin/env python3
"""Operation 11 — Analyst API security and contract tests."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

os.environ["CASTDEV_DATA_DIR"] = str(ROOT / "data")
os.environ["CASTDEV_ADMIN_ACTIVATION_TOKEN"] = "test-activation-token-op9"
os.environ["CASTDEV_ADMIN_SESSION_SECRET"] = "test-session-secret-op9"
os.environ["CASTDEV_ALLOW_TEST_SUBMIT"] = "1"
os.environ["CASTDEV_ANALYST_API_TOKEN"] = "test-analyst-token-op11-not-for-prod"
os.environ["CASTDEV_ANALYST_FLOOD_MAX_PER_WINDOW"] = "200"
os.environ["CASTDEV_ANALYST_FLOOD_WINDOW_SECONDS"] = "60"

# Reload config after env set
import importlib

import castdev.config as config_mod

importlib.reload(config_mod)

from castdev import config, db  # noqa: E402
from castdev.app import create_app  # noqa: E402
from castdev.seed_test import seed_test, TEST_RESPONSES  # noqa: E402

TOKEN = os.environ["CASTDEV_ANALYST_API_TOKEN"]
AUTH = {"Authorization": f"Bearer {TOKEN}"}
WRONG = {"Authorization": "Bearer wrong-token-definitely-not"}


def check(name: str, cond: bool, detail: str = "") -> dict:
    return {"name": name, "pass": bool(cond), "detail": str(detail)[:300]}


def _body_has_token(resp) -> bool:
    text = resp.get_data(as_text=True) or ""
    # Only the secret value — env var *name* may appear in OpenAPI docs.
    return TOKEN in text


def run() -> dict:
    results = []
    config.ensure_dirs()
    db.init_all()
    seeded = seed_test(wipe=True)
    results.append(check("seed_ok", seeded["count"] == len(TEST_RESPONSES), seeded))

    app = create_app()
    client = app.test_client()

    # OpenAPI public (no auth) — GPT schema fetch
    oa = client.get("/api/analyst/v1/openapi.json")
    oa_json = oa.get_json() or {}
    results.append(
        check(
            "openapi_public",
            oa.status_code == 200
            and oa_json.get("openapi", "").startswith("3.")
            and "/api/analyst/v1/status" in oa_json.get("paths", {})
            and not _body_has_token(oa),
            {"keys": list(oa_json.keys())[:6]},
        )
    )
    results.append(
        check(
            "openapi_no_cors_star",
            oa.headers.get("Access-Control-Allow-Origin") not in ("*",),
            oa.headers.get("Access-Control-Allow-Origin"),
        )
    )

    # No auth denied
    noauth = client.get("/api/analyst/v1/status?dataset=test")
    results.append(
        check("no_auth_denied", noauth.status_code == 401, noauth.get_json())
    )

    # Wrong token
    bad = client.get("/api/analyst/v1/status?dataset=test", headers=WRONG)
    results.append(check("wrong_token_denied", bad.status_code == 401, bad.get_json()))

    # Query-string token rejected
    qtok = client.get(f"/api/analyst/v1/status?dataset=test&token={TOKEN}")
    results.append(
        check("query_token_rejected", qtok.status_code == 401, qtok.get_json())
    )

    # Correct token
    st = client.get("/api/analyst/v1/status?dataset=test", headers=AUTH)
    stj = st.get_json() or {}
    results.append(
        check(
            "correct_token_status",
            st.status_code == 200
            and stj.get("ok")
            and stj.get("count") == len(TEST_RESPONSES)
            and stj.get("derived", {}).get("derived_present") is True
            and stj.get("read_only") is True
            and not _body_has_token(st),
            {"count": stj.get("count"), "api_version": stj.get("api_version")},
        )
    )

    # Token not returned in any successful body
    for path in (
        "/api/analyst/v1/responses?dataset=test&limit=5",
        "/api/analyst/v1/derived?dataset=test",
        "/api/analyst/v1/aggregates?dataset=test",
        "/api/analyst/v1/rules",
    ):
        r = client.get(path, headers=AUTH)
        results.append(
            check(
                f"no_token_leak:{path.split('?',1)[0].rsplit('/',1)[-1]}",
                r.status_code == 200 and not _body_has_token(r),
                r.status_code,
            )
        )

    # Prod/test isolation: production count independent of test seed
    with db.session("production") as conn:
        prod_n = db.count_responses(conn, "production")
    st_prod = client.get("/api/analyst/v1/status?dataset=production", headers=AUTH)
    st_test = client.get("/api/analyst/v1/status?dataset=test", headers=AUTH)
    results.append(
        check(
            "prod_test_isolation",
            st_prod.get_json().get("count") == prod_n
            and st_test.get_json().get("count") == len(TEST_RESPONSES)
            and st_prod.get_json().get("count") != st_test.get_json().get("count"),
            {
                "prod": st_prod.get_json().get("count"),
                "test": st_test.get_json().get("count"),
            },
        )
    )

    # Pagination
    page1 = client.get(
        "/api/analyst/v1/responses?dataset=test&limit=3&offset=0", headers=AUTH
    )
    page2 = client.get(
        "/api/analyst/v1/responses?dataset=test&limit=3&offset=3", headers=AUTH
    )
    p1 = page1.get_json() or {}
    p2 = page2.get_json() or {}
    ids1 = {x["survey_id"] for x in p1.get("items", [])}
    ids2 = {x["survey_id"] for x in p2.get("items", [])}
    results.append(
        check(
            "pagination",
            page1.status_code == 200
            and len(p1.get("items", [])) == 3
            and len(p2.get("items", [])) == 3
            and ids1.isdisjoint(ids2)
            and p1.get("total") == len(TEST_RESPONSES)
            and "q1" in (p1["items"][0] if p1.get("items") else {}),
            {"n1": len(ids1), "n2": len(ids2)},
        )
    )

    # Filter by ids
    one_id = next(iter(ids1))
    by_id = client.get(
        f"/api/analyst/v1/responses?dataset=test&ids={one_id}", headers=AUTH
    )
    bij = by_id.get_json() or {}
    results.append(
        check(
            "filter_by_ids",
            by_id.status_code == 200
            and bij.get("total") == 1
            and bij["items"][0]["survey_id"] == one_id,
            bij.get("total"),
        )
    )

    # Aggregates + cross
    agg = client.get("/api/analyst/v1/aggregates?dataset=test&cross=1", headers=AUTH)
    agj = agg.get_json() or {}
    results.append(
        check(
            "aggregates_cross",
            agg.status_code == 200
            and agj.get("total") == len(TEST_RESPONSES)
            and "themes" in agj
            and "cross" in agj
            and agj["cross"]
            and "links" in agj["cross"]
            and "share" in (agj["themes"]["q1"]["themes"][0] if agj["themes"]["q1"]["themes"] else {"share": 1}),
            {"themes_q1": len(agj.get("themes", {}).get("q1", {}).get("themes", []))},
        )
    )

    # Feature filter on aggregates
    fkey = "channel_stance:hh"
    fval = "positive_use"
    filt = client.get(
        f"/api/analyst/v1/aggregates?dataset=test&feature_key={fkey}&feature_value={fval}&question=q1",
        headers=AUTH,
    )
    fj = filt.get_json() or {}
    results.append(
        check(
            "aggregates_feature_filter",
            filt.status_code == 200
            and fj.get("filter")
            and isinstance(fj["filter"].get("response_ids"), list)
            and len(fj["filter"]["response_ids"]) >= 1,
            fj.get("filter"),
        )
    )

    # Evidence
    ev = client.get(
        f"/api/analyst/v1/evidence?dataset=test&feature_key={fkey}&feature_value={fval}&question=q1&limit=5",
        headers=AUTH,
    )
    evj = ev.get_json() or {}
    results.append(
        check(
            "evidence",
            ev.status_code == 200
            and evj.get("returned", 0) >= 1
            and "q1" in evj["items"][0]
            and evj["items"][0].get("survey_id"),
            {"returned": evj.get("returned")},
        )
    )

    # Derived
    der = client.get("/api/analyst/v1/derived?dataset=test", headers=AUTH)
    dj = der.get_json() or {}
    results.append(
        check(
            "derived",
            der.status_code == 200
            and dj.get("data_kind") == "derived"
            and len(dj.get("classifications", [])) > 0
            and dj.get("multi_label") is True,
            {"n": len(dj.get("classifications", []))},
        )
    )

    # Read-only
    for method in ("post", "put", "patch", "delete"):
        r = getattr(client, method)(
            "/api/analyst/v1/status?dataset=test", headers=AUTH, json={}
        )
        results.append(
            check(
                f"read_only_{method}",
                r.status_code == 405 and (r.get_json() or {}).get("error") == "read_only",
                r.status_code,
            )
        )

    # Malformed
    mal = client.get(
        "/api/analyst/v1/responses?dataset=test&limit=abc", headers=AUTH
    )
    results.append(check("malformed_limit", mal.status_code == 400, mal.get_json()))

    bad_ds = client.get("/api/analyst/v1/status?dataset=mixed", headers=AUTH)
    results.append(check("invalid_dataset", bad_ds.status_code == 400, bad_ds.get_json()))

    # Rate limit (dedicated fake client IP + temporary low ceiling)
    old_max = config.ANALYST_FLOOD_MAX_PER_WINDOW
    config.ANALYST_FLOOD_MAX_PER_WINDOW = 3
    limited = False
    rl_headers = {**AUTH, "X-Forwarded-For": "203.0.113.77"}
    try:
        for _ in range(10):
            rr = client.get("/api/analyst/v1/status?dataset=test", headers=rl_headers)
            if rr.status_code == 429:
                limited = True
                break
    finally:
        config.ANALYST_FLOOD_MAX_PER_WINDOW = old_max
    results.append(check("rate_limit", limited, "expected 429 within burst"))

    # Security headers on analyst response
    # Use wrong token to avoid rate-limit after burst — still gets headers via after_request
    hdr = client.get("/api/analyst/v1/openapi.json")
    results.append(
        check(
            "security_headers",
            hdr.headers.get("X-Content-Type-Options") == "nosniff"
            and hdr.headers.get("X-Frame-Options") == "DENY",
            dict(hdr.headers),
        )
    )

    # Admin + public regression (light)
    health = client.get("/api/castdev/health")
    results.append(
        check(
            "public_health",
            health.status_code == 200 and health.get_json().get("ok"),
            health.get_json(),
        )
    )
    pub_denied = client.get("/api/admin/summary")
    results.append(check("admin_still_requires_session", pub_denied.status_code == 401))
    act = client.post(
        "/api/admin/activate", json={"token": os.environ["CASTDEV_ADMIN_ACTIVATION_TOKEN"]}
    )
    results.append(check("admin_activate_ok", act.status_code == 200, act.get_json()))
    summ = client.get("/api/admin/summary?dataset=test")
    results.append(
        check(
            "admin_summary_regression",
            summ.status_code == 200 and (summ.get_json() or {}).get("total") == len(TEST_RESPONSES),
            (summ.get_json() or {}).get("total"),
        )
    )
    admin_html = client.get("/admin").get_data(as_text=True)
    results.append(
        check(
            "op10_cabinet_intact",
            "Кабинет аналитика" in admin_html and "Сводка" in admin_html,
            "cabinet chrome",
        )
    )
    index = client.get("/")
    results.append(check("public_survey_ok", index.status_code == 200))

    # Fail-closed when token empty: reload path checked via consteq — covered by no_auth
    # Audit table exists
    with db.session("production") as conn:
        try:
            n = conn.execute("SELECT COUNT(*) AS n FROM analyst_audit_log").fetchone()["n"]
            audit_ok = True
        except Exception as e:
            n = 0
            audit_ok = False
            detail = str(e)
        else:
            detail = str(n)
    results.append(check("audit_table", audit_ok and n >= 1, detail))

    passed = sum(1 for r in results if r["pass"])
    failed = [r for r in results if not r["pass"]]
    return {
        "ok": len(failed) == 0,
        "passed": passed,
        "failed_count": len(failed),
        "total": len(results),
        "failed": failed,
        "results": results,
    }


if __name__ == "__main__":
    report = run()
    out = ROOT / "data" / "op11-analyst-selftest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "passed": report["passed"],
                "failed_count": report["failed_count"],
                "out": str(out),
            },
            ensure_ascii=False,
        )
    )
    if report["failed"]:
        print("FAILED:", json.dumps(report["failed"], ensure_ascii=False, indent=2))
    sys.exit(0 if report["ok"] else 1)
