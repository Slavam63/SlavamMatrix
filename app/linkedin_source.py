from __future__ import annotations

import hashlib
import re
from typing import Any

from app.config import Config
from app.linkedin_bridge import build_linkedin_bridge_request, fetch_linkedin_jobs_via_bridge


LINKEDIN_SOURCE_NAME = "linkedin"

# Приоритет «худшей» причины при объединении нескольких сценариев / jobs (все пустые).
LINKEDIN_ZERO_REASON_PRIORITY = (
    "parse_error",
    "blocked_or_challenge",
    "not_authenticated",
    "empty_query",
    "cards_parse_failed",
    "layout_no_recognized_cards",
    "selector_no_cards",
    "real_no_results",
)


def _pick_worst_linkedin_zero_reason(reasons: list[str]) -> str:
    cleaned = [r for r in reasons if r]
    if not cleaned:
        return "real_no_results"
    best_rank = len(LINKEDIN_ZERO_REASON_PRIORITY) + 1
    chosen = "real_no_results"
    for r in cleaned:
        try:
            rank = LINKEDIN_ZERO_REASON_PRIORITY.index(r)
        except ValueError:
            rank = len(LINKEDIN_ZERO_REASON_PRIORITY)
        if rank < best_rank:
            best_rank = rank
            chosen = r
    return chosen


def merge_linkedin_search_metas(metas: list[dict[str, Any]]) -> dict[str, Any]:
    if not metas:
        return {
            "linkedin_zero_reason": "real_no_results",
            "raw_bridge_items": 0,
            "per_job": [],
        }
    per_job: list[dict[str, Any]] = []
    raw_bridge_items = 0
    reason_candidates: list[str] = []
    for m in metas:
        per_job.extend(m.get("per_job") or [])
        raw_bridge_items += int(m.get("raw_bridge_items") or 0)
        zr = m.get("linkedin_zero_reason")
        if zr:
            reason_candidates.append(str(zr))
    for job in per_job:
        zr = job.get("zero_reason")
        if zr:
            reason_candidates.append(str(zr))
    return {
        "linkedin_zero_reason": _pick_worst_linkedin_zero_reason(reason_candidates),
        "raw_bridge_items": raw_bridge_items,
        "per_job": per_job,
    }


def _clean_text(value: Any) -> str:
    if value is None:
        return ""

    text = str(value).strip()
    text = re.sub(r"\s+", " ", text)
    return text.strip(" ,;.-")


def _clean_html(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""

    text = re.sub(r"<br\s*/?>", " | ", text, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", " | ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" |,;.-")


def _normalize_location(value: Any) -> str:
    return _clean_text(value)


def _normalize_url(value: Any) -> str:
    url = _clean_text(value)
    if not url:
        return ""

    url = re.sub(r"#.*$", "", url)
    return url


def _normalize_salary(value: Any) -> str | None:
    salary = _clean_text(value)
    return salary or None


def _normalize_employment_type(value: Any) -> str | None:
    employment_type = _clean_text(value)
    return employment_type or None


def _detect_remote_flag(text: str, location: str = "") -> bool:
    haystack = f"{text} {location}".lower()

    remote_markers = [
        "remote",
        "удален",
        "удалён",
        "work from home",
        "home office",
        "distributed team",
    ]

    return any(marker in haystack for marker in remote_markers)


def _build_external_id(url: str, title: str, company: str) -> str:
    url = _normalize_url(url)
    if url:
        return hashlib.md5(url.encode("utf-8")).hexdigest()

    seed = f"{title}::{company}".lower().strip()
    return hashlib.md5(seed.encode("utf-8")).hexdigest()


def _get_linkedin_proxy_settings() -> dict[str, Any]:
    proxy_enabled = bool(Config.LINKEDIN_PROXY_ENABLED)
    proxy_url = _clean_text(Config.EFFECTIVE_LINKEDIN_PROXY_URL)

    return {
        "enabled": proxy_enabled and bool(proxy_url),
        "url": proxy_url,
        "scheme": _clean_text(Config.LINKEDIN_PROXY_SCHEME),
        "host": _clean_text(Config.LINKEDIN_PROXY_HOST),
        "port": int(Config.LINKEDIN_PROXY_PORT or 0),
        "username": _clean_text(Config.LINKEDIN_PROXY_USERNAME),
        "password": _clean_text(Config.LINKEDIN_PROXY_PASSWORD),
    }


def _mask_proxy_url(proxy_url: str) -> str:
    proxy_url = _clean_text(proxy_url)
    if not proxy_url:
        return ""

    return re.sub(r"//([^:@/]+):([^@/]+)@", r"//***:***@", proxy_url)


def _make_vacancy(
    *,
    title: str,
    company: str,
    location: str,
    url: str,
    description: str,
    salary: str | None = None,
    employment_type: str | None = None,
    remote: bool | None = None,
    scenario_name: str | None = None,
    source_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    title = _clean_text(title)
    company = _clean_text(company)
    location = _normalize_location(location)
    url = _normalize_url(url)
    description = _clean_html(description)
    salary = _normalize_salary(salary)
    employment_type = _normalize_employment_type(employment_type)

    if remote is None:
        remote = _detect_remote_flag(description, location)

    return {
        "source": LINKEDIN_SOURCE_NAME,
        "external_id": _build_external_id(url=url, title=title, company=company),
        "title": title,
        "company": company,
        "location": location,
        "salary": salary,
        "url": url,
        "description": description,
        "employment_type": employment_type,
        "remote": bool(remote),
        "scenario_name": _clean_text(scenario_name or ""),
        "source_meta": source_meta or {},
    }


def _get_payload_keywords(payload: dict[str, Any]) -> list[str]:
    keywords = payload.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [item.strip() for item in keywords.split(",") if item.strip()]

    cleaned = []
    seen = set()

    for item in keywords:
        value = _clean_text(item).lower()
        if not value or value in seen:
            continue
        seen.add(value)
        cleaned.append(value)

    return cleaned[:8]


def _build_search_terms(payload: dict[str, Any]) -> list[str]:
    terms = []
    seen = set()

    def add(value: str):
        value = _clean_text(value)
        lowered = value.lower()
        if not value or lowered in seen:
            return
        seen.add(lowered)
        terms.append(value)

    add(payload.get("query_text") or "")
    add(payload.get("position") or "")

    for item in payload.get("query_variants") or []:
        add(str(item))

    for item in payload.get("role_variants") or []:
        add(str(item))

    for item in payload.get("industry_variants") or []:
        add(str(item))

    for item in _get_payload_keywords(payload):
        add(item)

    return terms[:12]


def build_linkedin_search_jobs(payload: dict[str, Any]) -> list[dict[str, Any]]:
    scenarios = payload.get("scenarios") or []
    jobs = []

    if scenarios:
        for scenario in scenarios:
            scenario_name = _clean_text(scenario.get("name") or "scenario")
            scenario_query = _clean_text(scenario.get("query") or payload.get("query_text") or "")
            scenario_keywords = scenario.get("keywords") or payload.get("keywords") or []

            jobs.append(
                {
                    "source": LINKEDIN_SOURCE_NAME,
                    "scenario_name": scenario_name,
                    "query_text": scenario_query,
                    "keywords": scenario_keywords,
                    "location": _clean_text(payload.get("location") or ""),
                    "role": _clean_text(scenario.get("role") or payload.get("position") or ""),
                    "industry": _clean_text(scenario.get("industry") or ""),
                    "remote": bool(payload.get("remote")),
                    "employment_type": _clean_text(payload.get("employment_type") or ""),
                }
            )
    else:
        jobs.append(
            {
                "source": LINKEDIN_SOURCE_NAME,
                "scenario_name": _clean_text(payload.get("scenario_name") or "primary"),
                "query_text": _clean_text(payload.get("query_text") or ""),
                "keywords": payload.get("keywords") or [],
                "location": _clean_text(payload.get("location") or ""),
                "role": _clean_text(payload.get("position") or ""),
                "industry": "",
                "remote": bool(payload.get("remote")),
                "employment_type": _clean_text(payload.get("employment_type") or ""),
            }
        )

    return jobs


def normalize_linkedin_vacancy(raw_item: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    scenario_name = raw_item.get("scenario_name") or payload.get("scenario_name") or "linkedin"

    title = raw_item.get("title") or raw_item.get("job_title") or ""
    company = raw_item.get("company") or raw_item.get("company_name") or ""
    location = raw_item.get("location") or raw_item.get("job_location") or payload.get("location") or ""
    url = raw_item.get("url") or raw_item.get("job_url") or ""
    description = (
        raw_item.get("description")
        or raw_item.get("summary")
        or raw_item.get("snippet")
        or ""
    )
    salary = raw_item.get("salary") or raw_item.get("compensation")
    employment_type = raw_item.get("employment_type") or raw_item.get("job_type")
    remote = raw_item.get("remote")

    proxy = _get_linkedin_proxy_settings()

    source_meta = {
        "raw_source": LINKEDIN_SOURCE_NAME,
        "scenario_name": scenario_name,
        "search_terms": _build_search_terms(payload),
        "proxy_enabled": proxy["enabled"],
        "proxy_url_masked": _mask_proxy_url(proxy["url"]),
    }

    return _make_vacancy(
        title=title,
        company=company,
        location=location,
        url=url,
        description=description,
        salary=salary,
        employment_type=employment_type,
        remote=remote,
        scenario_name=scenario_name,
        source_meta=source_meta,
    )


def _mock_linkedin_results_for_job(job: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, Any]]:
    role = _clean_text(job.get("role") or payload.get("position") or "Product Manager")
    location = _clean_text(job.get("location") or payload.get("location") or "Remote")
    scenario_name = _clean_text(job.get("scenario_name") or "primary")
    query_text = _clean_text(job.get("query_text") or payload.get("query_text") or role)
    bridge_context = build_linkedin_bridge_request(job, payload)

    variants = [
        {
            "title": role or "Head of Product",
            "company": "LinkedIn Mock Company",
            "location": location,
            "url": f"https://www.linkedin.com/jobs/view/{hashlib.md5((scenario_name + role).encode('utf-8')).hexdigest()[:12]}",
            "description": (
                f"Mock LinkedIn vacancy for scenario '{scenario_name}'. "
                f"Search query: {query_text}. "
                "Digital product management, customer journey, transformation, innovation."
            ),
            "employment_type": payload.get("employment_type") or "Full-time",
            "remote": bool(payload.get("remote")),
            "scenario_name": scenario_name,
            "source_meta": {
                "mode": "mock",
                "proxy_enabled": bridge_context["proxy"]["enabled"],
                "proxy_url_masked": bridge_context["proxy"]["url_masked"],
            },
        }
    ]

    normalized = []
    for item in variants:
        vacancy = normalize_linkedin_vacancy(item, payload)
        vacancy["source_meta"].update(item.get("source_meta") or {})
        normalized.append(vacancy)

    return normalized


def search_linkedin_vacancies(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    LinkedIn-источник: сценарные задания → bridge (Playwright) → нормализация.

    Возвращает (vacancies, meta), meta содержит:
    - linkedin_zero_reason: если vacancies пустой — код причины, иначе None
    - raw_bridge_items: суммарное число сырых записей с bridge до нормализации
    - per_job: список dict с полями zero_reason, raw_locator_count, … по каждому job
    """
    jobs = build_linkedin_search_jobs(payload)
    vacancies: list[dict[str, Any]] = []
    per_job: list[dict[str, Any]] = []
    raw_bridge_items = 0

    for job in jobs:
        raw_results, fetch_meta = fetch_linkedin_jobs_via_bridge(job, payload)
        per_job.append(fetch_meta)
        raw_bridge_items += len(raw_results)

        if raw_results:
            for raw_item in raw_results:
                normalized = normalize_linkedin_vacancy(raw_item, payload)
                vacancies.append(normalized)

    meta: dict[str, Any] = {
        "linkedin_zero_reason": None,
        "raw_bridge_items": raw_bridge_items,
        "per_job": per_job,
    }
    if not vacancies:
        reasons = [m.get("zero_reason") for m in per_job if m.get("zero_reason")]
        meta["linkedin_zero_reason"] = _pick_worst_linkedin_zero_reason([str(r) for r in reasons])

    return vacancies, meta
