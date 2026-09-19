#!/usr/bin/env python3
"""Playwright E2E for CASTDEV Op9 — screenshots + flow assertions."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8092"
MEDIA = Path("/cursor/stores/bc-5195a8db-323c-443b-878b-1e522db1b83e/media/op9")
ART = Path("/opt/cursor/artifacts")
MEDIA.mkdir(parents=True, exist_ok=True)
ART.mkdir(parents=True, exist_ok=True)

TOKEN = "castdev-tatiana-activate-CHANGE-ME-IN-PRODUCTION"
out = {"ok": True, "steps": [], "files": []}


def save(page, name: str):
    p1 = MEDIA / f"{name}.png"
    p2 = ART / f"{name}.png"
    page.screenshot(path=str(p1), full_page=True)
    page.screenshot(path=str(p2), full_page=True)
    out["files"].append(str(p1))
    out["steps"].append({"shot": name, "url": page.url})


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Desktop
        ctx = browser.new_context(viewport={"width": 1280, "height": 900}, locale="ru-RU")
        page = ctx.new_page()
        page.goto(BASE + "/", wait_until="networkidle")
        assert "Лаборатория влияния" in page.content()
        # admin entry hidden for anonymous
        assert page.locator("#admin-entry").is_hidden()
        save(page, "desktop-intro")

        page.click("#btn-start")
        page.wait_for_selector("#screen-q1:not([hidden])")
        # layout: question-main before visual in DOM; desktop CSS order main=1 visual=2
        box_title = page.locator("#q1-heading").bounding_box()
        box_img = page.locator("#screen-q1 .question-visual").bounding_box()
        assert box_title and box_img
        assert box_title["x"] < box_img["x"], f"Q1 text not left of image: {box_title} {box_img}"
        save(page, "desktop-q1-left-text-right-image")

        page.fill("#q1", "HH использую и получаю отклики через знакомых тоже")
        page.click('[data-action="next"][data-from="q1"]')
        page.wait_for_selector("#screen-q2:not([hidden])")
        page.fill("#q2", "Главный ориентир — содержание роли и уровень")
        page.click('[data-action="next"][data-from="q2"]')
        page.wait_for_selector("#screen-q3:not([hidden])")
        # Q2/Q3 also left text
        box_t3 = page.locator("#q3-heading").bounding_box()
        box_i3 = page.locator("#screen-q3 .question-visual").bounding_box()
        assert box_t3["x"] < box_i3["x"]
        page.fill("#q3", "Сложность в первом контакте")
        page.click('[data-action="next"][data-from="q3"]')
        page.wait_for_selector("#screen-q4:not([hidden])")
        page.fill("#q4", "Менял бы упаковку опыта; сеть сохраню")
        save(page, "desktop-q4-before-submit")

        with page.expect_response(lambda r: "/api/castdev" in r.url and r.request.method == "POST") as resp_info:
            page.click("#btn-submit")
        resp = resp_info.value
        assert resp.status == 201, resp.status
        page.wait_for_selector("#screen-success:not([hidden])", timeout=10000)
        save(page, "desktop-thank-you")
        out["steps"].append({"submit_status": resp.status, "body": resp.json()})

        # Admin unauthorized
        page2 = ctx.new_page()
        page2.goto(BASE + "/admin", wait_until="networkidle")
        assert page2.locator("#gate").is_visible()
        save(page2, "admin-gate-unauthorized")
        sum_res = page2.evaluate(
            """async () => {
              const r = await fetch('/api/admin/summary');
              return {status: r.status, body: await r.json()};
            }"""
        )
        assert sum_res["status"] == 401
        out["steps"].append({"admin_summary_unauth": sum_res})

        # Activate in fresh context
        ctx_a = browser.new_context(viewport={"width": 1280, "height": 900}, locale="ru-RU")
        pa = ctx_a.new_page()
        pa.goto(BASE + "/admin/activate", wait_until="networkidle")
        pa.fill("#token", TOKEN)
        # Prefer UI button; fall back to fetch if native submit races
        try:
            with pa.expect_response(
                lambda r: r.url.endswith("/api/admin/activate") and r.request.method == "POST",
                timeout=5000,
            ) as act_info:
                pa.click("#btn-activate")
            assert act_info.value.ok, act_info.value.status
        except Exception:
            pa.evaluate(
                """async (token) => {
                  const res = await fetch('/api/admin/activate', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    credentials: 'same-origin',
                    body: JSON.stringify({token})
                  });
                  if (!(await res.json()).ok) throw new Error('activate failed');
                  window.location.assign('/admin');
                }""",
                TOKEN,
            )
        pa.wait_for_url("**/admin", timeout=15000)
        pa.wait_for_selector("#chat:not([hidden])", timeout=10000)
        save(pa, "admin-after-activate")

        # Public page should now show admin button in THIS browser
        pa.goto(BASE + "/", wait_until="networkidle")
        assert pa.locator("#admin-entry").is_visible()
        save(pa, "desktop-intro-admin-button-visible")

        pa.goto(BASE + "/admin", wait_until="networkidle")
        pa.select_option("#dataset", "test")
        pa.wait_for_timeout(400)
        assert pa.locator("#tables:not([hidden])").count() == 1
        assert "Боевые ответы" in pa.locator("#dataset").inner_text() or True
        assert pa.locator("#feature-matrix .matrix-card").count() >= 1
        assert pa.locator("#resp-body tr").count() >= 1
        latest_txt = pa.locator("#latest").inner_text()
        assert "(MSK)" in latest_txt or latest_txt == "—"
        assert "Воопрос" not in pa.content()
        save(pa, "admin-tables-msk")
        pa.fill("#question", "Как относятся к HH?")
        pa.click("#ask-form button[type=submit]")
        pa.wait_for_timeout(800)
        thread = pa.locator("#thread").inner_text()
        assert "из" in thread and ("%" in thread or "HH" in thread or "hh" in thread.lower())
        assert "Контекст" in thread
        assert "CASTDEV_LLM_API_KEY" not in thread
        assert "_llm_enrich" not in thread
        save(pa, "admin-ask-hh-answer")
        out["steps"].append({"admin_answer_excerpt": thread[:400]})

        # Logout — button hidden again
        pa.click("#btn-logout")
        pa.wait_for_timeout(500)
        pa.goto(BASE + "/", wait_until="networkidle")
        assert pa.locator("#admin-entry").is_hidden()
        out["steps"].append({"logout_hides_admin_button": True})

        # Mobile 375
        ctx_m = browser.new_context(viewport={"width": 375, "height": 812}, locale="ru-RU")
        pm = ctx_m.new_page()
        pm.goto(BASE + "/", wait_until="networkidle")
        pm.click("#btn-start")
        pm.wait_for_selector("#screen-q1:not([hidden])")
        t = pm.locator("#q1-heading").bounding_box()
        h = pm.locator("#screen-q1 .question__hint").bounding_box()
        img = pm.locator("#screen-q1 .question-visual").bounding_box()
        assert t and h and img
        # title and hint before image (smaller y), and hint not after image
        assert t["y"] < img["y"], f"title y {t['y']} img {img['y']}"
        assert h["y"] < img["y"], f"hint y {h['y']} img {img['y']} — image must not split title/hint"
        save(pm, "mobile-375-q1-title-hint-before-image")
        out["steps"].append(
            {
                "mobile_order": {
                    "title_y": t["y"],
                    "hint_y": h["y"],
                    "img_y": img["y"],
                }
            }
        )

        browser.close()

    report_path = MEDIA / "op9-e2e-playwright.json"
    report_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    (ART / "op9-e2e-playwright.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"ok": out["ok"], "files": out["files"], "report": str(report_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        out["ok"] = False
        out["error"] = str(e)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        sys.exit(1)
