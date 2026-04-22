from __future__ import annotations

import json
import logging
import re
import socket
import ssl
import time
import urllib.error
import urllib.request
from urllib.parse import quote_plus
from typing import Any

from playwright.sync_api import sync_playwright

from app.config import Config

logger = logging.getLogger(__name__)

PROXY_SMOKE_TEST_URL = "https://api.ipify.org?format=json"
PLAYWRIGHT_SMOKE_TEST_URL = "https://api.ipify.org?format=json"
LINKEDIN_HOME_URL = "https://www.linkedin.com/"
LINKEDIN_FEED_URL = "https://www.linkedin.com/feed/"
LINKEDIN_JOBS_URL = "https://www.linkedin.com/jobs/"

# Порядок: от более специфичных к запасным (берём селектор с максимальным count).
LINKEDIN_JOB_CARD_SELECTORS_ORDERED = [
    "li.jobs-search-results__list-item",
    "ul.jobs-search__results-list > li",
    "[data-view-name='job-search-card']",
    "li[data-occludable-job-id]",
    "div.job-card-container",
    "li[class*='jobs-search-results__list-item']",
    "main .jobs-search-results__list > li",
    "main ul.scaffold-layout__list > li",
    "div[class*='jobs-search-results'] li[class*='job-card']",
    "main a[href*='/jobs/view/']",
]


def _linkedin_pick_first_matching_cards_locator(page: Any) -> tuple[Any, str, int]:
    """Берём первый селектор по приоритету с ненулевым count (не max — иначе «все a» перебьёт список)."""
    fallback_loc = page.locator(LINKEDIN_JOB_CARD_SELECTORS_ORDERED[0])
    fallback_sel = LINKEDIN_JOB_CARD_SELECTORS_ORDERED[0]
    for sel in LINKEDIN_JOB_CARD_SELECTORS_ORDERED:
        loc = page.locator(sel)
        try:
            n = int(loc.count())
        except Exception:
            n = 0
        if n > 0:
            return loc, sel, n
    return fallback_loc, fallback_sel, 0


def _linkedin_body_checkpoint_or_challenge(body: str) -> bool:
    b = _clean_text(body).lower()
    markers = (
        "checkpoint",
        "security verification",
        "unusual activity",
        "captcha",
        "verify it's you",
        "verify it’s you",
        "challenge",
        "automated access",
        "robot",
    )
    return any(m in b for m in markers)


def _linkedin_body_suggests_gated_login(body: str, url: str) -> bool:
    u = _clean_text(url).lower()
    b = _clean_text(body).lower()
    if "/login" in u or "/checkpoint" in u or "authwall" in u:
        return True
    if ("sign in" in b or "join linkedin" in b or "войти" in b) and "jobs" in u:
        return True
    return False


def _linkedin_layout_hints_job_links(page: Any) -> bool:
    try:
        return int(page.locator("a[href*='/jobs/view/']").count()) >= 2
    except Exception:
        return False


def _linkedin_probe_selector_counts(page: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for sel in LINKEDIN_JOB_CARD_SELECTORS_ORDERED:
        try:
            n = int(page.locator(sel).count())
        except Exception:
            n = 0
        if n > 0:
            out[sel] = n
    return out


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _mask_proxy_url(proxy_url: str) -> str:
    proxy_url = _clean_text(proxy_url)
    if not proxy_url:
        return ""

    if "@" not in proxy_url or "://" not in proxy_url:
        return proxy_url

    scheme, rest = proxy_url.split("://", 1)
    credentials, host_part = rest.split("@", 1)

    if ":" in credentials:
        return f"{scheme}://***:***@{host_part}"

    return f"{scheme}://***@{host_part}"


def get_linkedin_proxy_config() -> dict[str, Any]:
    proxy_url = _clean_text(getattr(Config, "EFFECTIVE_LINKEDIN_PROXY_URL", ""))

    return {
        "enabled": bool(getattr(Config, "LINKEDIN_PROXY_ENABLED", False) and proxy_url),
        "url": proxy_url,
        "url_masked": _mask_proxy_url(proxy_url),
        "scheme": _clean_text(getattr(Config, "LINKEDIN_PROXY_SCHEME", "")),
        "host": _clean_text(getattr(Config, "LINKEDIN_PROXY_HOST", "")),
        "port": int(getattr(Config, "LINKEDIN_PROXY_PORT", 0) or 0),
        "username": _clean_text(getattr(Config, "LINKEDIN_PROXY_USERNAME", "")),
        "password": _clean_text(getattr(Config, "LINKEDIN_PROXY_PASSWORD", "")),
    }


def get_linkedin_browser_profile_config() -> dict[str, Any]:
    return {
        "enabled": bool(getattr(Config, "LINKEDIN_BROWSER_PROFILE_ENABLED", False)),
        "profile_dir": _clean_text(getattr(Config, "LINKEDIN_BROWSER_PROFILE_DIR", "")),
        "headless": bool(getattr(Config, "LINKEDIN_HEADLESS", True)),
        "navigation_timeout_ms": int(getattr(Config, "LINKEDIN_NAVIGATION_TIMEOUT_MS", 45000) or 45000),
    }


def build_linkedin_bridge_request(job: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    proxy = get_linkedin_proxy_config()
    browser_profile = get_linkedin_browser_profile_config()

    return {
        "source": "linkedin",
        "job_request_id": payload.get("job_request_id"),
        "scenario_name": _clean_text(job.get("scenario_name") or payload.get("scenario_name") or "primary"),
        "query_text": _clean_text(job.get("query_text") or payload.get("query_text") or ""),
        "role": _clean_text(job.get("role") or payload.get("position") or ""),
        "industry": _clean_text(job.get("industry") or ""),
        "location": _clean_text(job.get("location") or payload.get("location") or ""),
        "keywords": job.get("keywords") or payload.get("keywords") or [],
        "remote": bool(job.get("remote") if job.get("remote") is not None else payload.get("remote")),
        "employment_type": _clean_text(job.get("employment_type") or payload.get("employment_type") or ""),
        "proxy": proxy,
        "browser_profile": {
            "enabled": browser_profile["enabled"],
            "profile_dir": browser_profile["profile_dir"],
            "headless": browser_profile["headless"],
            "navigation_timeout_ms": browser_profile["navigation_timeout_ms"],
        },
    }


def _build_proxy_opener(proxy: dict[str, Any]) -> urllib.request.OpenerDirector:
    proxy_url = proxy.get("url") or ""
    handlers: list[urllib.request.BaseHandler] = []

    if proxy.get("enabled") and proxy_url:
        handlers.append(
            urllib.request.ProxyHandler(
                {
                    "http": proxy_url,
                    "https": proxy_url,
                }
            )
        )
    else:
        handlers.append(urllib.request.ProxyHandler({}))

    ssl_context = ssl.create_default_context()
    handlers.append(urllib.request.HTTPSHandler(context=ssl_context))

    return urllib.request.build_opener(*handlers)


def _build_playwright_proxy_settings(proxy: dict[str, Any]) -> dict[str, str] | None:
    if not proxy.get("enabled"):
        return None

    scheme = proxy.get("scheme") or "http"
    host = proxy.get("host") or ""
    port = proxy.get("port") or 0

    if not host or not port:
        return None

    settings = {
        "server": f"{scheme}://{host}:{port}",
    }

    username = proxy.get("username") or ""
    password = proxy.get("password") or ""

    if username:
        settings["username"] = username
    if password:
        settings["password"] = password

    return settings


def _safe_get_title(page) -> str:
    try:
        return _clean_text(page.title())
    except Exception:
        return ""


def _safe_get_body_text(page, limit: int = 1000) -> str:
    try:
        body_text = page.text_content("body") or ""
        return _clean_text(body_text)[:limit]
    except Exception:
        return ""


def _wait_for_page_stability(page, total_timeout_ms: int) -> None:
    checkpoints = [
        min(3000, total_timeout_ms),
        min(6000, total_timeout_ms),
        min(10000, total_timeout_ms),
    ]

    for timeout in checkpoints:
        if timeout <= 0:
            continue
        try:
            page.wait_for_load_state("domcontentloaded", timeout=timeout)
        except Exception:
            pass
        try:
            page.wait_for_load_state("networkidle", timeout=timeout)
        except Exception:
            pass
        time.sleep(0.4)


def _capture_page_state(page, status_code: int | None = None) -> dict[str, Any]:
    final_url = _clean_text(page.url)
    title = _safe_get_title(page)
    body_preview = _safe_get_body_text(page, limit=1000)

    return {
        "final_url": final_url,
        "status_code": status_code,
        "title": title,
        "body_preview": body_preview,
    }


def _detect_linkedin_auth_state(final_url: str, title: str, body_preview: str) -> dict[str, Any]:
    url = _clean_text(final_url).lower()
    title_l = _clean_text(title).lower()
    body_l = _clean_text(body_preview).lower()

    authwall_markers = [
        "/authwall",
        "signup",
        "join linkedin",
        "sign up",
    ]
    login_markers = [
        "/login",
        "sign in",
        "forgot password",
        "keep me logged in",
    ]
    authenticated_url_markers = [
        "/feed",
        "/jobs",
        "/mynetwork",
        "/messaging",
        "/notifications",
    ]

    if any(marker in url for marker in authwall_markers) or any(marker in title_l for marker in authwall_markers):
        return {
            "auth_state": "authwall",
            "is_authenticated": False,
            "reason": "authwall_detected",
        }

    if any(marker in url for marker in login_markers) or any(marker in title_l for marker in login_markers):
        return {
            "auth_state": "login_required",
            "is_authenticated": False,
            "reason": "login_page_detected",
        }

    if "captcha" in url or "captcha" in title_l or "security verification" in title_l:
        return {
            "auth_state": "challenge",
            "is_authenticated": False,
            "reason": "captcha_or_security_challenge",
        }

    if any(marker in url for marker in authenticated_url_markers):
        return {
            "auth_state": "authenticated",
            "is_authenticated": True,
            "reason": "authenticated_url_detected",
        }

    if "feed" in body_l and "linkedin" in body_l:
        return {
            "auth_state": "authenticated",
            "is_authenticated": True,
            "reason": "feed_content_detected",
        }

    if "sign in" in body_l and "linkedin" in body_l:
        return {
            "auth_state": "login_required",
            "is_authenticated": False,
            "reason": "login_text_detected",
        }

    return {
        "auth_state": "unknown",
        "is_authenticated": False,
        "reason": "state_not_classified",
    }


def _linkedin_empty_serp_heuristic(body_preview: str) -> bool:
    b = _clean_text(body_preview).lower()
    if not b:
        return False
    markers = (
        "no results match",
        "no results found",
        "no jobs found",
        "nothing matches",
        "ничего не найдено",
        "нет ваканс",
        "0 results",
        "we couldn't find",
        "we could not find",
        "try a different",
    )
    return any(m in b for m in markers)


def run_linkedin_proxy_smoke_test(test_url: str = PROXY_SMOKE_TEST_URL, timeout: int = 20) -> dict[str, Any]:
    proxy = get_linkedin_proxy_config()

    if not proxy["enabled"]:
        return {
            "ok": False,
            "stage": "config",
            "error": "proxy_disabled",
            "proxy_enabled": False,
            "proxy_url_masked": proxy["url_masked"],
            "test_url": test_url,
        }

    opener = _build_proxy_opener(proxy)
    request = urllib.request.Request(
        test_url,
        headers={
            "User-Agent": "MatrixParser/1.0 LinkedInBridgeSmokeTest",
            "Accept": "application/json,text/plain,*/*",
        },
    )

    try:
        with opener.open(request, timeout=timeout) as response:
            raw_body = response.read().decode("utf-8", errors="replace")
            content_type = response.headers.get("Content-Type", "")
            status_code = getattr(response, "status", None) or response.getcode()

        try:
            parsed_body: Any = json.loads(raw_body)
        except json.JSONDecodeError:
            parsed_body = raw_body

        return {
            "ok": True,
            "stage": "request",
            "status_code": status_code,
            "content_type": content_type,
            "proxy_enabled": True,
            "proxy_url_masked": proxy["url_masked"],
            "test_url": test_url,
            "response": parsed_body,
        }

    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {
            "ok": False,
            "stage": "http",
            "error": str(exc),
            "status_code": exc.code,
            "proxy_enabled": True,
            "proxy_url_masked": proxy["url_masked"],
            "test_url": test_url,
            "response": body,
        }

    except urllib.error.URLError as exc:
        return {
            "ok": False,
            "stage": "network",
            "error": str(exc.reason),
            "proxy_enabled": True,
            "proxy_url_masked": proxy["url_masked"],
            "test_url": test_url,
        }

    except socket.timeout:
        return {
            "ok": False,
            "stage": "timeout",
            "error": "socket timeout",
            "proxy_enabled": True,
            "proxy_url_masked": proxy["url_masked"],
            "test_url": test_url,
        }

    except Exception as exc:
        return {
            "ok": False,
            "stage": "exception",
            "error": repr(exc),
            "proxy_enabled": True,
            "proxy_url_masked": proxy["url_masked"],
            "test_url": test_url,
        }


def run_linkedin_playwright_smoke_test(
    test_url: str = PLAYWRIGHT_SMOKE_TEST_URL,
    timeout_ms: int = 30000,
) -> dict[str, Any]:
    proxy = get_linkedin_proxy_config()

    if not proxy["enabled"]:
        return {
            "ok": False,
            "stage": "config",
            "error": "proxy_disabled",
            "proxy_enabled": False,
            "proxy_url_masked": proxy["url_masked"],
            "test_url": test_url,
        }

    proxy_settings = _build_playwright_proxy_settings(proxy)
    if not proxy_settings:
        return {
            "ok": False,
            "stage": "config",
            "error": "proxy_settings_invalid",
            "proxy_enabled": True,
            "proxy_url_masked": proxy["url_masked"],
            "test_url": test_url,
        }

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                proxy=proxy_settings,
            )
            page = browser.new_page()
            response = page.goto(test_url, wait_until="domcontentloaded", timeout=timeout_ms)
            _wait_for_page_stability(page, timeout_ms)
            state = _capture_page_state(page, status_code=response.status if response else None)
            browser.close()

        parsed_body: Any
        try:
            parsed_body = json.loads(state["body_preview"])
        except json.JSONDecodeError:
            parsed_body = state["body_preview"]

        return {
            "ok": True,
            "stage": "playwright",
            "proxy_enabled": True,
            "proxy_url_masked": proxy["url_masked"],
            "test_url": test_url,
            "response": parsed_body,
            "final_url": state["final_url"],
            "title": state["title"],
        }

    except Exception as exc:
        return {
            "ok": False,
            "stage": "playwright",
            "error": repr(exc),
            "proxy_enabled": True,
            "proxy_url_masked": proxy["url_masked"],
            "test_url": test_url,
        }


def open_linkedin_home_via_playwright(
    target_url: str = LINKEDIN_HOME_URL,
    timeout_ms: int = 45000,
) -> dict[str, Any]:
    proxy = get_linkedin_proxy_config()

    if not proxy["enabled"]:
        return {
            "ok": False,
            "stage": "config",
            "error": "proxy_disabled",
            "proxy_enabled": False,
            "proxy_url_masked": proxy["url_masked"],
            "target_url": target_url,
        }

    proxy_settings = _build_playwright_proxy_settings(proxy)
    if not proxy_settings:
        return {
            "ok": False,
            "stage": "config",
            "error": "proxy_settings_invalid",
            "proxy_enabled": True,
            "proxy_url_masked": proxy["url_masked"],
            "target_url": target_url,
        }

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                proxy=proxy_settings,
            )
            page = browser.new_page()
            response = page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_ms)
            _wait_for_page_stability(page, timeout_ms)
            state = _capture_page_state(page, status_code=response.status if response else None)
            browser.close()

        return {
            "ok": True,
            "stage": "linkedin_open",
            "proxy_enabled": True,
            "proxy_url_masked": proxy["url_masked"],
            "target_url": target_url,
            **state,
        }

    except Exception as exc:
        return {
            "ok": False,
            "stage": "linkedin_open",
            "error": repr(exc),
            "proxy_enabled": True,
            "proxy_url_masked": proxy["url_masked"],
            "target_url": target_url,
        }


def open_linkedin_home_with_persistent_profile(
    target_url: str = LINKEDIN_HOME_URL,
) -> dict[str, Any]:
    proxy = get_linkedin_proxy_config()
    browser_profile = get_linkedin_browser_profile_config()

    if not proxy["enabled"]:
        return {
            "ok": False,
            "stage": "config",
            "error": "proxy_disabled",
            "proxy_enabled": False,
            "proxy_url_masked": proxy["url_masked"],
            "target_url": target_url,
        }

    if not browser_profile["enabled"]:
        return {
            "ok": False,
            "stage": "config",
            "error": "browser_profile_disabled",
            "proxy_enabled": True,
            "proxy_url_masked": proxy["url_masked"],
            "target_url": target_url,
        }

    if not browser_profile["profile_dir"]:
        return {
            "ok": False,
            "stage": "config",
            "error": "browser_profile_dir_missing",
            "proxy_enabled": True,
            "proxy_url_masked": proxy["url_masked"],
            "target_url": target_url,
        }

    proxy_settings = _build_playwright_proxy_settings(proxy)
    if not proxy_settings:
        return {
            "ok": False,
            "stage": "config",
            "error": "proxy_settings_invalid",
            "proxy_enabled": True,
            "proxy_url_masked": proxy["url_masked"],
            "target_url": target_url,
        }

    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=browser_profile["profile_dir"],
                headless=browser_profile["headless"],
                proxy=proxy_settings,
            )

            page = context.new_page()
            response = page.goto(
                target_url,
                wait_until="domcontentloaded",
                timeout=browser_profile["navigation_timeout_ms"],
            )

            _wait_for_page_stability(page, browser_profile["navigation_timeout_ms"])
            state = _capture_page_state(page, status_code=response.status if response else None)
            auth_state = _detect_linkedin_auth_state(
                final_url=state["final_url"],
                title=state["title"],
                body_preview=state["body_preview"],
            )
            pages_count = len(context.pages)

            context.close()

        return {
            "ok": True,
            "stage": "linkedin_persistent_open",
            "proxy_enabled": True,
            "proxy_url_masked": proxy["url_masked"],
            "profile_enabled": True,
            "profile_dir": browser_profile["profile_dir"],
            "headless": browser_profile["headless"],
            "target_url": target_url,
            "pages_count": pages_count,
            **auth_state,
            **state,
        }

    except Exception as exc:
        return {
            "ok": False,
            "stage": "linkedin_persistent_open",
            "error": repr(exc),
            "proxy_enabled": True,
            "proxy_url_masked": proxy["url_masked"],
            "profile_enabled": True,
            "profile_dir": browser_profile["profile_dir"],
            "headless": browser_profile["headless"],
            "target_url": target_url,
        }


def check_linkedin_auth_state_with_persistent_profile(
    target_url: str = LINKEDIN_HOME_URL,
) -> dict[str, Any]:
    result = open_linkedin_home_with_persistent_profile(target_url=target_url)
    result["stage"] = "linkedin_auth_state_check"
    return result


def open_linkedin_manual_auth_session(
    target_url: str = LINKEDIN_HOME_URL,
    session_wait_seconds: int = 600,
    poll_interval_seconds: int = 3,
) -> dict[str, Any]:
    proxy = get_linkedin_proxy_config()
    browser_profile = get_linkedin_browser_profile_config()

    if not proxy["enabled"]:
        return {
            "ok": False,
            "stage": "config",
            "error": "proxy_disabled",
            "proxy_enabled": False,
            "proxy_url_masked": proxy["url_masked"],
            "target_url": target_url,
        }

    if not browser_profile["enabled"]:
        return {
            "ok": False,
            "stage": "config",
            "error": "browser_profile_disabled",
            "proxy_enabled": True,
            "proxy_url_masked": proxy["url_masked"],
            "target_url": target_url,
        }

    if not browser_profile["profile_dir"]:
        return {
            "ok": False,
            "stage": "config",
            "error": "browser_profile_dir_missing",
            "proxy_enabled": True,
            "proxy_url_masked": proxy["url_masked"],
            "target_url": target_url,
        }

    proxy_settings = _build_playwright_proxy_settings(proxy)
    if not proxy_settings:
        return {
            "ok": False,
            "stage": "config",
            "error": "proxy_settings_invalid",
            "proxy_enabled": True,
            "proxy_url_masked": proxy["url_masked"],
            "target_url": target_url,
        }

    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=browser_profile["profile_dir"],
                headless=False,
                proxy=proxy_settings,
            )

            page = context.new_page()
            response = page.goto(
                target_url,
                wait_until="domcontentloaded",
                timeout=browser_profile["navigation_timeout_ms"],
            )

            _wait_for_page_stability(page, browser_profile["navigation_timeout_ms"])
            initial_state = _capture_page_state(page, status_code=response.status if response else None)
            initial_auth_state = _detect_linkedin_auth_state(
                final_url=initial_state["final_url"],
                title=initial_state["title"],
                body_preview=initial_state["body_preview"],
            )

            started_at = time.time()
            final_state = initial_state
            final_auth_state = initial_auth_state

            while time.time() - started_at < session_wait_seconds:
                time.sleep(max(1, poll_interval_seconds))

                if page.is_closed():
                    break

                final_state = _capture_page_state(page)
                final_auth_state = _detect_linkedin_auth_state(
                    final_url=final_state["final_url"],
                    title=final_state["title"],
                    body_preview=final_state["body_preview"],
                )

                if final_auth_state["is_authenticated"]:
                    break

            pages_count = len(context.pages)
            context.close()

        return {
            "ok": True,
            "stage": "linkedin_manual_auth_session",
            "proxy_enabled": True,
            "proxy_url_masked": proxy["url_masked"],
            "profile_enabled": True,
            "profile_dir": browser_profile["profile_dir"],
            "headless": False,
            "target_url": target_url,
            "pages_count": pages_count,
            "session_wait_seconds": session_wait_seconds,
            "initial_auth_state": initial_auth_state["auth_state"],
            "initial_auth_reason": initial_auth_state["reason"],
            **final_auth_state,
            **final_state,
        }

    except Exception as exc:
        return {
            "ok": False,
            "stage": "linkedin_manual_auth_session",
            "error": repr(exc),
            "proxy_enabled": True,
            "proxy_url_masked": proxy["url_masked"],
            "profile_enabled": True,
            "profile_dir": browser_profile["profile_dir"],
            "headless": False,
            "target_url": target_url,
        }


def fetch_linkedin_jobs_via_bridge(
    job: dict[str, Any], payload: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Playwright bridge: поиск вакансий LinkedIn Jobs.

    Возвращает (vacancies, meta), где meta всегда содержит диагностику:
    - zero_reason: причина пустой выдачи (если vacancies пустой), иначе None
    - raw_locator_count: сколько узлов нашёл основной локатор карточек
    - raw_items_returned: len(vacancies)
    - auth_state, auth_reason: снимок классификации страницы (если применимо)
    - error_repr: текст исключения при parse_error
    """
    request_context = build_linkedin_bridge_request(job, payload)
    proxy = request_context.get("proxy") or {}
    browser_profile = request_context.get("browser_profile") or {}

    scenario_name = _clean_text(request_context.get("scenario_name") or job.get("scenario_name") or "primary")
    query_text = _clean_text(request_context.get("query_text") or "")
    location = _clean_text(request_context.get("location") or "")
    keywords = request_context.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [item.strip() for item in keywords.split(",") if item.strip()]

    query_parts = [query_text]
    for item in keywords[:2]:
        cleaned = _clean_text(item)
        if cleaned and cleaned.lower() not in _clean_text(query_text).lower():
            query_parts.append(cleaned)
    effective_query = _clean_text(" ".join([part for part in query_parts if part]))

    if not effective_query:
        logger.info(
            "LinkedIn bridge: empty_query (no effective query) scenario=%s job_request_id=%s",
            scenario_name,
            payload.get("job_request_id"),
        )
        return [], {
            "zero_reason": "empty_query",
            "raw_locator_count": 0,
            "raw_items_returned": 0,
            "auth_state": None,
            "auth_reason": None,
            "error_repr": None,
            "scenario_name": scenario_name,
        }

    search_url = (
        "https://www.linkedin.com/jobs/search/"
        f"?keywords={quote_plus(effective_query)}"
        + (f"&location={quote_plus(location)}" if location else "")
    )

    max_cards = int(getattr(Config, "LINKEDIN_JOBS_MAX_CARDS", 18) or 18)
    max_details = int(getattr(Config, "LINKEDIN_JOBS_MAX_DETAILS", 10) or 10)
    scroll_steps = int(getattr(Config, "LINKEDIN_JOBS_SCROLL_STEPS", 4) or 4)
    scroll_delay_ms = int(getattr(Config, "LINKEDIN_JOBS_SCROLL_DELAY_MS", 650) or 650)
    slowmo_ms = int(getattr(Config, "LINKEDIN_JOBS_SLOWMO_MS", 0) or 0)

    proxy_settings = _build_playwright_proxy_settings(proxy) if proxy.get("enabled") else None

    def safe_text(value: Any) -> str:
        return _clean_text(value)

    def safe_attr(locator, name: str) -> str:
        try:
            return safe_text(locator.get_attribute(name))
        except Exception:
            return ""

    def pick_first(locator, selectors: list[str]):
        for sel in selectors:
            try:
                item = locator.locator(sel)
                if item.count() > 0:
                    return item.first
            except Exception:
                continue
        return None

    def extract_from_card(card) -> dict[str, Any]:
        title_loc = pick_first(
            card,
            [
                "h3 a span[aria-hidden='true']",
                "h3",
                "a span[aria-hidden='true']",
                "a.job-card-list__title",
                ".job-card-list__title",
                "[data-test-job-card-title]",
                "span.artdeco-entity-lockup__title",
                "a[aria-label]",
                ".job-card-container__link span",
            ],
        )
        company_loc = pick_first(
            card,
            [
                "h4",
                ".job-search-card__subtitle",
                ".artdeco-entity-lockup__subtitle",
                "span.job-card-container__primary-description",
                ".job-card-container__company-name",
                "h4 a",
            ],
        )
        location_loc = pick_first(
            card,
            [
                ".job-search-card__location",
                ".artdeco-entity-lockup__caption",
                "span[class*='location']",
                ".job-card-container__metadata-item",
            ],
        )
        link_loc = pick_first(
            card,
            [
                "a[href*='/jobs/view/']",
                "a[href*='/jobs/collection']",
                "a[href*='linkedin.com/jobs/view']",
            ],
        )

        title = safe_text(title_loc.inner_text()) if title_loc else ""
        company = safe_text(company_loc.inner_text()) if company_loc else ""
        loc_text = safe_text(location_loc.inner_text()) if location_loc else ""
        url = safe_attr(link_loc, "href") if link_loc else ""

        if not url:
            try:
                tag = str(card.evaluate("el => (el.tagName || '').toUpperCase()")).upper()
                if tag == "A":
                    url = safe_attr(card, "href")
            except Exception:
                pass

        if not title and link_loc:
            title = safe_text(safe_attr(link_loc, "aria-label"))

        if not title and url:
            try:
                title = safe_text(card.inner_text())[:220]
            except Exception:
                title = ""

        if url and url.startswith("/"):
            url = f"https://www.linkedin.com{url}"
        url = re.sub(r"[?#].*$", "", url).strip()

        return {
            "scenario_name": scenario_name,
            "title": title,
            "company": company,
            "location": loc_text,
            "url": url,
        }

    def extract_details_from_panel(page) -> dict[str, Any]:
        description = ""
        try:
            container = page.locator(
                "div.jobs-description__content, div.jobs-description-content__text, div#job-details, section[class*='description']"
            ).first
            if container.count() > 0:
                raw = safe_text(container.inner_text())
                description = raw
        except Exception:
            description = ""

        if description:
            description = re.sub(r"\s+\n", "\n", description)
            description = re.sub(r"\n{3,}", "\n\n", description).strip()

        return {
            "description": description,
        }

    results: list[dict[str, Any]] = []

    def _meta(
        zero_reason: str | None,
        raw_locator_count: int,
        auth: dict[str, Any] | None = None,
        error_repr: str | None = None,
        *,
        card_selector_used: str | None = None,
        parsed_from_cards: int | None = None,
        probe_counts: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        row: dict[str, Any] = {
            "zero_reason": zero_reason,
            "raw_locator_count": raw_locator_count,
            "raw_items_returned": len(results),
            "auth_state": (auth or {}).get("auth_state"),
            "auth_reason": (auth or {}).get("reason"),
            "error_repr": error_repr,
            "scenario_name": scenario_name,
        }
        if card_selector_used is not None:
            row["card_selector_used"] = card_selector_used
        if parsed_from_cards is not None:
            row["parsed_from_cards"] = parsed_from_cards
        if probe_counts is not None:
            row["selector_probe_counts"] = probe_counts
        return row

    def _scroll_results(steps: int, delay_ms: int) -> None:
        for _ in range(max(0, steps)):
            try:
                page.mouse.wheel(0, 1400)
            except Exception:
                try:
                    page.evaluate("window.scrollBy(0, 1400)")
                except Exception:
                    pass
            page.wait_for_timeout(max(200, delay_ms))

    def _classify_zero_cards(body_preview: str, url_now: str, page_ref: Any) -> str:
        if _linkedin_body_checkpoint_or_challenge(body_preview):
            return "blocked_or_challenge"
        if _linkedin_body_suggests_gated_login(body_preview, url_now):
            return "not_authenticated"
        if _linkedin_empty_serp_heuristic(body_preview):
            return "real_no_results"
        if _linkedin_layout_hints_job_links(page_ref):
            return "layout_no_recognized_cards"
        return "selector_no_cards"

    try:
        with sync_playwright() as p:
            launch_kwargs: dict[str, Any] = {"headless": bool(browser_profile.get("headless", True))}
            if slowmo_ms:
                launch_kwargs["slow_mo"] = slowmo_ms

            if browser_profile.get("enabled") and browser_profile.get("profile_dir"):
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(browser_profile["profile_dir"]),
                    proxy=proxy_settings,
                    **launch_kwargs,
                )
            else:
                browser = p.chromium.launch(proxy=proxy_settings, **launch_kwargs)
                context = browser.new_context()

            page = context.new_page()
            page.set_default_navigation_timeout(int(browser_profile.get("navigation_timeout_ms") or 45000))
            page.goto(search_url, wait_until="domcontentloaded")
            _wait_for_page_stability(page, int(browser_profile.get("navigation_timeout_ms") or 45000))

            state = _capture_page_state(page)
            auth = _detect_linkedin_auth_state(
                state.get("final_url") or "",
                state.get("title") or "",
                state.get("body_preview") or "",
            )
            if not auth.get("is_authenticated"):
                try:
                    page.close()
                except Exception:
                    pass
                context.close()
                auth_state = auth.get("auth_state") or ""
                if auth_state == "challenge" or "captcha" in str(auth.get("reason") or "").lower():
                    reason = "blocked_or_challenge"
                else:
                    reason = "not_authenticated"
                logger.warning(
                    "LinkedIn bridge: %s auth_state=%s auth_reason=%s scenario=%s",
                    reason,
                    auth_state,
                    auth.get("reason"),
                    scenario_name,
                )
                return [], _meta(reason, 0, auth=auth)

            _scroll_results(scroll_steps, scroll_delay_ms)

            state = _capture_page_state(page)
            auth = _detect_linkedin_auth_state(
                state.get("final_url") or "",
                state.get("title") or "",
                state.get("body_preview") or "",
            )
            if not auth.get("is_authenticated"):
                try:
                    page.close()
                except Exception:
                    pass
                context.close()
                auth_state = auth.get("auth_state") or ""
                if auth_state == "challenge" or "captcha" in str(auth.get("reason") or "").lower():
                    reason = "blocked_or_challenge"
                else:
                    reason = "not_authenticated"
                logger.warning(
                    "LinkedIn bridge: %s (after scroll) auth_state=%s auth_reason=%s scenario=%s",
                    reason,
                    auth_state,
                    auth.get("reason"),
                    scenario_name,
                )
                return [], _meta(reason, 0, auth=auth)

            cards, card_sel, raw_locator_count = _linkedin_pick_first_matching_cards_locator(page)
            probe_counts = _linkedin_probe_selector_counts(page)
            logger.info(
                "LinkedIn bridge: after scroll1 selector=%s count=%s probe=%s scenario=%s",
                card_sel,
                raw_locator_count,
                probe_counts,
                scenario_name,
            )

            if raw_locator_count == 0:
                logger.info("LinkedIn bridge: empty card probe, extra scroll+wait scenario=%s", scenario_name)
                for _ in range(3):
                    try:
                        page.mouse.wheel(0, 1800)
                    except Exception:
                        try:
                            page.evaluate("window.scrollBy(0, 1800)")
                        except Exception:
                            pass
                    page.wait_for_timeout(1100)
                page.wait_for_timeout(1400)
                cards, card_sel, raw_locator_count = _linkedin_pick_first_matching_cards_locator(page)
                probe_counts = _linkedin_probe_selector_counts(page)
                logger.info(
                    "LinkedIn bridge: after scroll2 selector=%s count=%s probe=%s scenario=%s",
                    card_sel,
                    raw_locator_count,
                    probe_counts,
                    scenario_name,
                )

            if raw_locator_count == 0:
                body_preview = _safe_get_body_text(page, 4000) or (state.get("body_preview") or "")
                url_now = _clean_text(page.url)
                zr = _classify_zero_cards(body_preview, url_now, page)
                logger.warning(
                    "LinkedIn bridge: zero cards classified=%s url=%s probe=%s scenario=%s",
                    zr,
                    url_now,
                    probe_counts,
                    scenario_name,
                )
                try:
                    page.close()
                except Exception:
                    pass
                context.close()
                return [], _meta(
                    zr,
                    0,
                    auth=auth,
                    card_selector_used=card_sel,
                    parsed_from_cards=0,
                    probe_counts=probe_counts,
                )

            total = min(raw_locator_count, max_cards)
            skipped = 0
            for idx in range(total):
                card = cards.nth(idx)
                item = extract_from_card(card)
                if not item.get("title") and not item.get("url"):
                    skipped += 1
                    continue

                if idx < max_details:
                    try:
                        clickable = card.locator("a[href*='/jobs/view/']").first
                        if clickable.count() > 0:
                            clickable.click(timeout=5000)
                        else:
                            card.click(timeout=5000)
                        page.wait_for_timeout(900)
                        details = extract_details_from_panel(page)
                        if details.get("description"):
                            item.update(details)
                    except Exception:
                        pass

                results.append(item)

            try:
                page.close()
            except Exception:
                pass
            context.close()

        logger.info(
            "LinkedIn bridge: selector=%s nodes=%s parsed=%s skipped_empty=%s scenario=%s",
            card_sel,
            raw_locator_count,
            len(results),
            skipped,
            scenario_name,
        )

        if not results and raw_locator_count > 0:
            logger.warning(
                "LinkedIn bridge: cards_parse_failed selector=%s nodes=%s scenario=%s",
                card_sel,
                raw_locator_count,
                scenario_name,
            )
            return [], _meta(
                "cards_parse_failed",
                raw_locator_count,
                auth=auth,
                card_selector_used=card_sel,
                parsed_from_cards=0,
                probe_counts=probe_counts,
            )

        return results, _meta(
            None,
            raw_locator_count,
            auth=auth,
            card_selector_used=card_sel,
            parsed_from_cards=len(results),
            probe_counts=probe_counts,
        )

    except Exception as exc:
        logger.exception("LinkedIn bridge: parse_error scenario=%s", scenario_name)
        return [], {
            "zero_reason": "parse_error",
            "raw_locator_count": 0,
            "raw_items_returned": 0,
            "auth_state": None,
            "auth_reason": None,
            "error_repr": repr(exc),
            "scenario_name": scenario_name,
        }