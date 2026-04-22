from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from app.config import Config


HH_SOURCE_NAME = "hh"
HH_SEARCH_URL = "https://hh.ru/search/vacancy"


class HHBrowserSourceError(RuntimeError):
    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _clean_text(value: Any) -> str:
    if value is None:
        return ""

    text = str(value)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" ,;.-")


def _build_search_text(payload: dict[str, Any]) -> str:
    parts = []

    for key in ("position", "query_text"):
        value = _clean_text(payload.get(key))
        if value and value.lower() not in {item.lower() for item in parts}:
            parts.append(value)

    keywords = payload.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [item.strip() for item in keywords.split(",") if item.strip()]

    for item in keywords[:4]:
        value = _clean_text(item)
        if value and value.lower() not in {part.lower() for part in parts}:
            parts.append(value)

    return " ".join(parts).strip()


def _build_hh_url(payload: dict[str, Any]) -> str:
    params = {
        "text": _build_search_text(payload),
        "area": "1" if _clean_text(payload.get("location")).lower() in {"москва", "moscow"} else "",
        "from": "suggest_post",
    }

    if payload.get("remote"):
        params["schedule"] = "remote"

    params = {key: value for key, value in params.items() if value}
    return f"{HH_SEARCH_URL}?{urlencode(params)}"


def _profile_dir(payload: dict[str, Any]) -> str:
    base_dir = _clean_text(getattr(Config, "HH_BROWSER_PROFILE_BASE_DIR", ""))
    if not base_dir:
        base_dir = "/var/www/matrix-parser/browser_profiles/hh"

    job_request_id = _clean_text(payload.get("job_request_id")) or "default"
    digest = hashlib.md5(job_request_id.encode("utf-8")).hexdigest()[:12]
    path = Path(base_dir) / f"user_{digest}"
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def _playwright_proxy_settings() -> dict[str, str] | None:
    if not bool(getattr(Config, "HH_PROXY_ENABLED", False)):
        return None

    host = _clean_text(getattr(Config, "HH_PROXY_HOST", ""))
    port = int(getattr(Config, "HH_PROXY_PORT", 0) or 0)
    if not host or not port:
        return None

    scheme = _clean_text(getattr(Config, "HH_PROXY_SCHEME", "")) or "http"
    settings = {"server": f"{scheme}://{host}:{port}"}

    username = _clean_text(getattr(Config, "HH_PROXY_USERNAME", ""))
    password = _clean_text(getattr(Config, "HH_PROXY_PASSWORD", ""))
    if username:
        settings["username"] = username
    if password:
        settings["password"] = password

    return settings


def _page_text(page, limit: int = 2500) -> str:
    try:
        text = page.text_content("body") or ""
    except Exception:
        return ""
    return _clean_text(text)[:limit]


def _detect_hh_state(page) -> str:
    url = _clean_text(page.url).lower()
    title = ""
    try:
        title = _clean_text(page.title()).lower()
    except Exception:
        pass
    body = _page_text(page).lower()
    haystack = f"{url} {title} {body}"

    blocked_markers = [
        "ddos-guard",
        "captcha",
        "подтвердите, что вы не робот",
        "access denied",
        "доступ ограничен",
        "проверяем ваш браузер",
    ]
    auth_markers = [
        "/account/login",
        "войти в личный кабинет",
        "войти на сайт",
        "авторизация",
    ]

    if any(marker in haystack for marker in blocked_markers):
        return "blocked"
    if any(marker in haystack for marker in auth_markers):
        return "auth_required"
    return "ready"


def _first_text(locator, selectors: list[str]) -> str:
    for selector in selectors:
        try:
            item = locator.locator(selector).first
            if item.count() > 0:
                value = _clean_text(item.inner_text(timeout=1500))
                if value:
                    return value
        except Exception:
            continue
    return ""


def _first_attr(locator, selectors: list[str], attr_name: str) -> str:
    for selector in selectors:
        try:
            item = locator.locator(selector).first
            if item.count() > 0:
                value = _clean_text(item.get_attribute(attr_name, timeout=1500))
                if value:
                    return value
        except Exception:
            continue
    return ""


def _normalize_hh_url(url: str) -> str:
    url = _clean_text(url)
    if not url:
        return ""
    if url.startswith("/"):
        return f"https://hh.ru{url}"
    return re.sub(r"\?.*$", "", url)


def _external_id(url: str, title: str, company: str) -> str:
    match = re.search(r"/vacancy/(\d+)", url)
    if match:
        return match.group(1)
    seed = f"{url}::{title}::{company}".lower()
    return hashlib.md5(seed.encode("utf-8")).hexdigest()


def _extract_vacancies(page, payload: dict[str, Any]) -> list[dict[str, Any]]:
    selectors = [
        "[data-qa='vacancy-serp__vacancy']",
        ".vacancy-serp-item",
        "[class*='vacancy-card']",
    ]

    cards = None
    for selector in selectors:
        found = page.locator(selector)
        if found.count() > 0:
            cards = found
            break

    if cards is None:
        return []

    vacancies = []
    max_cards = int(getattr(Config, "HH_JOBS_MAX_CARDS", 20) or 20)

    for index in range(min(cards.count(), max_cards)):
        card = cards.nth(index)
        title = _first_text(card, [
            "[data-qa='serp-item__title']",
            "a[data-qa='vacancy-serp__vacancy-title']",
            "a[href*='/vacancy/']",
        ])
        url = _normalize_hh_url(_first_attr(card, [
            "[data-qa='serp-item__title']",
            "a[data-qa='vacancy-serp__vacancy-title']",
            "a[href*='/vacancy/']",
        ], "href"))
        company = _first_text(card, [
            "[data-qa='vacancy-serp__vacancy-employer-text']",
            "[data-qa='vacancy-serp__vacancy-employer']",
            "[class*='company']",
        ])
        location = _first_text(card, [
            "[data-qa='vacancy-serp__vacancy-address']",
            "[data-qa='vacancy-serp__vacancy-address-text']",
            "[class*='address']",
        ]) or _clean_text(payload.get("location"))
        salary = _first_text(card, [
            "[data-qa='vacancy-serp__vacancy-compensation']",
            "[data-qa='vacancy-serp__vacancy-salary']",
            "[class*='compensation']",
        ])
        description = _first_text(card, [
            "[data-qa='vacancy-serp__vacancy_snippet_responsibility']",
            "[data-qa='vacancy-serp__vacancy_snippet_requirement']",
            "[class*='snippet']",
        ])

        if not title:
            continue

        vacancies.append(
            {
                "source": HH_SOURCE_NAME,
                "external_id": _external_id(url, title, company),
                "title": title,
                "company": company,
                "location": location,
                "salary": salary or None,
                "url": url,
                "description": description or None,
                "employment_type": None,
                "remote": bool(payload.get("remote", False)),
                "ai_score": 50.0,
                "scenario_name": payload.get("scenario_name") or "hh_browser",
                "source_meta": {
                    "mode": "browser",
                    "status": "completed",
                },
            }
        )

    return vacancies


def search_hh_vacancies_via_browser(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not bool(getattr(Config, "HH_BROWSER_SOURCE_ENABLED", True)):
        raise HHBrowserSourceError("failed", "HH browser source is disabled")

    search_url = _build_hh_url(payload)
    timeout = int(getattr(Config, "HH_NAVIGATION_TIMEOUT_MS", 45000) or 45000)

    try:
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=_profile_dir(payload),
                headless=bool(getattr(Config, "HH_HEADLESS", True)),
                proxy=_playwright_proxy_settings(),
                viewport={"width": 1366, "height": 900},
                locale="ru-RU",
            )
            page = context.new_page()
            page.goto(search_url, wait_until="domcontentloaded", timeout=timeout)
            try:
                page.wait_for_load_state("networkidle", timeout=min(timeout, 10000))
            except Exception:
                pass

            state = _detect_hh_state(page)
            if state == "auth_required":
                context.close()
                raise HHBrowserSourceError("auth_required", "HH требует авторизацию пользователя.")
            if state == "blocked":
                context.close()
                raise HHBrowserSourceError("blocked", "HH временно ограничил доступ, поиск продолжен по другим источникам.")

            vacancies = _extract_vacancies(page, payload)
            context.close()
            return vacancies

    except HHBrowserSourceError:
        raise
    except PlaywrightTimeoutError as exc:
        raise HHBrowserSourceError("failed", f"HH browser timeout: {exc}") from exc
    except Exception as exc:
        raise HHBrowserSourceError("failed", f"HH browser source failed: {exc}") from exc
