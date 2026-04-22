from __future__ import annotations

from typing import Any
import re

from app.resume_form_mapper import map_resume_to_form_data


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _clean_lower(value: Any) -> str:
    return _clean_text(value).lower()


def _split_keywords(value: Any) -> list[str]:
    if not value:
        return []

    if isinstance(value, list):
        raw_items = value
    else:
        text = str(value).replace(";", ",")
        raw_items = [item.strip() for item in text.split(",")]

    result: list[str] = []
    seen: set[str] = set()

    for item in raw_items:
        cleaned = _clean_text(item)
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        result.append(cleaned)

    return result


def _first_non_empty(*values: Any) -> str:
    for value in values:
        cleaned = _clean_text(value)
        if cleaned:
            return cleaned
    return ""


def _normalize_role_family(position: str, keywords: list[str]) -> str:
    blob = " ".join([position] + keywords).lower()

    finance_markers = [
        "fp&a",
        "fpa",
        "finance",
        "financial",
        "финанс",
        "ifrs",
        "budget",
        "budgeting",
        "forecast",
        "forecasting",
        "cash flow",
        "p&l",
        "management reporting",
        "controlling",
        "controller",
        "accounting",
        "бюджет",
        "отчет",
        "отчёт",
        "казнач",
        "экономист",
        "финансовый",
        "аналитик",
    ]
    sales_markers = [
        "sales",
        "commercial",
        "business development",
        "продаж",
        "коммерчес",
        "b2b",
        "revenue",
    ]
    product_markers = [
        "product",
        "roadmap",
        "backlog",
        "ux",
        "cx",
        "продукт",
    ]
    operations_markers = [
        "operations",
        "coo",
        "operational",
        "операцион",
    ]
    it_markers = [
        "python",
        "developer",
        "engineer",
        "backend",
        "frontend",
        "data",
        "sql",
        "devops",
        "разработ",
        "инженер",
    ]

    if any(marker in blob for marker in finance_markers):
        return "finance"
    if any(marker in blob for marker in sales_markers):
        return "sales"
    if any(marker in blob for marker in product_markers):
        return "product"
    if any(marker in blob for marker in operations_markers):
        return "operations"
    if any(marker in blob for marker in it_markers):
        return "it"

    return "unknown"


def _normalize_seniority(position: str, history_roles: list[str], extracted: dict[str, Any]) -> str:
    explicit = _clean_lower(extracted.get("seniority_level") or extracted.get("inferred_seniority_level"))
    if explicit in {"junior", "middle", "senior", "executive"}:
        return explicit

    blob = " ".join([position] + history_roles).lower()

    executive_markers = [
        "chief",
        "cfo",
        "ceo",
        "coo",
        "director",
        "head of",
        "vice president",
        "vp",
        "директор",
        "руководител",
        "начальник",
        "финансовый директор",
    ]
    senior_markers = [
        "senior",
        "lead",
        "principal",
        "ведущ",
        "старш",
        "главн",
    ]
    junior_markers = [
        "junior",
        "intern",
        "trainee",
        "стажер",
        "стажёр",
        "младш",
    ]

    if any(marker in blob for marker in executive_markers):
        return "executive"
    if any(marker in blob for marker in senior_markers):
        return "senior"
    if any(marker in blob for marker in junior_markers):
        return "junior"
    if position:
        return "middle"

    return "unknown"


def _build_query_variants(position: str, keywords: list[str], location: str, role_family: str) -> list[str]:
    variants: list[str] = []
    seen: set[str] = set()

    def add_variant(text: str) -> None:
        cleaned = re.sub(r"\s+", " ", _clean_text(text))
        if not cleaned:
            return
        key = cleaned.lower()
        if key in seen:
            return
        seen.add(key)
        variants.append(cleaned)

    if position and location:
        add_variant(f"{position} {location}")
    if position:
        add_variant(position)

    if role_family == "finance":
        finance_variants = [
            "Finance Analyst",
            "FP&A Specialist",
            "FP&A Analyst",
            "Financial Analyst",
            "Management Reporting Analyst",
            "Finance Manager",
            "Financial Controller",
            "Finance Director",
            "CFO",
        ]
        for item in finance_variants:
            if location:
                add_variant(f"{item} {location}")
            else:
                add_variant(item)

    for keyword in keywords[:3]:
        if position:
            add_variant(f"{position} {keyword}")
        elif location:
            add_variant(f"{keyword} {location}")
        else:
            add_variant(keyword)

    return variants[:8]


def _build_source_priority(role_family: str) -> list[str]:
    if role_family == "finance":
        return ["hh", "linkedin", "manual", "mock"]
    return ["hh", "linkedin", "manual", "mock"]


def _build_diagnostics(extracted: dict[str, Any], position: str, location: str, keywords: list[str]) -> dict[str, Any]:
    warnings = extracted.get("warnings") or []
    explanations: list[str] = []

    if position:
        explanations.append("Primary role resolved from resume/form mapping.")
    else:
        explanations.append("Primary role was not resolved from the resume.")

    if location:
        explanations.append("Location signal was detected.")
    else:
        explanations.append("Location signal was not detected.")

    if keywords:
        explanations.append("Keywords extracted for search planning.")
    else:
        explanations.append("No keywords extracted for search planning.")

    ambiguity_score = 0.2
    if not position:
        ambiguity_score += 0.4
    if not location:
        ambiguity_score += 0.15
    if len(keywords) < 3:
        ambiguity_score += 0.15
    if warnings:
        ambiguity_score += min(len(warnings) * 0.05, 0.2)

    if ambiguity_score > 1.0:
        ambiguity_score = 1.0

    return {
        "warnings": warnings,
        "recommendations": explanations,
        "ambiguity_score": round(ambiguity_score, 2),
    }


def _build_management(diagnostics: dict[str, Any], seniority_level: str) -> dict[str, Any]:
    ambiguity = float(diagnostics.get("ambiguity_score") or 0.0)

    if ambiguity >= 0.7:
        search_mode = "safe"
        risk_level = "high"
    elif ambiguity >= 0.45:
        search_mode = "balanced"
        risk_level = "medium"
    else:
        search_mode = "broad"
        risk_level = "low"

    if seniority_level == "executive" and search_mode == "broad":
        search_mode = "balanced"

    return {
        "search_mode": search_mode,
        "risk_level": risk_level,
    }


def build_agent_plan(
    *,
    resume_text: str = "",
    form_data: dict[str, Any] | None = None,
    job_request: Any = None,
) -> dict[str, Any]:
    """
    Minimal, stable search planner.

    This is a recovery implementation intended to restore application behaviour
    when the original search_agent.py is unavailable.
    """
    form_data = form_data or {}

    extracted = map_resume_to_form_data(resume_text or "")

    position = _first_non_empty(
        form_data.get("position"),
        extracted.get("position"),
        extracted.get("parsed_title"),
        extracted.get("desired_position"),
    )

    location = _first_non_empty(
        form_data.get("location"),
        extracted.get("location"),
    )

    email = _first_non_empty(
        form_data.get("email"),
        extracted.get("email"),
    )

    keywords = _split_keywords(form_data.get("keywords")) or _split_keywords(extracted.get("keywords"))
    industry = _first_non_empty(
        extracted.get("industry"),
        extracted.get("query_text"),
    )

    role_family = _normalize_role_family(position, keywords)
    senior_history_roles = []
    for item in extracted.get("past_roles") or []:
        cleaned = _clean_text(item)
        if cleaned:
            senior_history_roles.append(cleaned)

    seniority_level = _normalize_seniority(position, senior_history_roles, extracted)

    if not industry and role_family == "finance":
        industry = "Финансы"

    primary_query = _clean_text(extracted.get("query_text"))
    if not primary_query:
        if position and location:
            primary_query = f"{position} {location}"
        else:
            primary_query = position or location or ""

    query_variants = _build_query_variants(position, keywords, location, role_family)
    diagnostics = _build_diagnostics(extracted, position, location, keywords)
    management = _build_management(diagnostics, seniority_level)

    profile = {
        "primary_role": position,
        "industry": industry,
        "location": location,
        "email": email,
        "keywords": keywords,
        "employment_type": _first_non_empty(form_data.get("employment_type"), extracted.get("employment_type")),
        "work_format": _first_non_empty(form_data.get("work_format"), extracted.get("work_format")),
        "remote": bool(form_data.get("remote") or (str(extracted.get("work_format") or "").lower() == "remote")),
        "seniority_level": seniority_level,
        "role_family": role_family,
        "primary_target_role": _first_non_empty(extracted.get("primary_target_role"), position),
        "senior_history_roles": senior_history_roles,
        "finance_context_signals": list(extracted.get("finance_context_signals") or []),
        "recognition_notes": list(extracted.get("recognition_notes") or []),
        "product_domain": "",
    }

    strategy = {
        "primary_query": primary_query,
        "role_variants": [position] if position else [],
        "industry_variants": [industry] if industry else [],
        "keyword_variants": keywords,
        "query_variants": query_variants,
        "source_priority": _build_source_priority(role_family),
        "scenarios": [
            {
                "name": "primary",
                "role": position,
                "industry": industry,
                "query": primary_query,
                "keywords": keywords,
            }
        ] if primary_query else [],
    }

    return {
        "profile": profile,
        "strategy": strategy,
        "diagnostics": diagnostics,
        "management": management,
    }
