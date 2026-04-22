from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any
import json
import re

import app
from app.models import (
    GeneratedArtifact,
    JobRequest,
    VacancyActionTask,
    VacancyIntake,
    VacancyMatch,
)
from app.resume_form_mapper import map_resume_to_form_data
from app.search_agent import build_agent_plan


REMOTE_MARKERS = [
    "remote",
    "удал",
    "home office",
    "work from home",
    "гибрид",
    "hybrid",
]

EMPLOYMENT_MARKERS = {
    "full_time": ["full time", "полная занятость", "full-time"],
    "part_time": ["part time", "частичная занятость", "part-time"],
    "contract": ["contract", "контракт", "project basis", "consulting"],
}

SKILL_MARKERS = [
    "p&l",
    "sales",
    "commercial",
    "revenue",
    "growth",
    "b2b",
    "b2c",
    "product",
    "digital",
    "transformation",
    "innovation",
    "marketing",
    "crm",
    "cx",
    "customer journey",
    "erp",
    "sap",
    "ifrs",
    "finance",
    "operations",
    "strategy",
    "business development",
    "negotiation",
    "leadership",
]

ACTION_PRIORITY_BY_DECISION = {
    "apply": "high",
    "review": "medium",
    "ignore": "low",
    "follow_up": "medium",
}

ROLE_ALIASES = {
    "коммерческий директор": [
        "коммерческий директор",
        "commercial director",
        "chief commercial officer",
        "cco",
        "директор по продажам",
        "sales director",
        "head of sales",
    ],
    "директор по продажам": [
        "директор по продажам",
        "sales director",
        "head of sales",
        "commercial director",
    ],
    "директор по развитию бизнеса": [
        "директор по развитию бизнеса",
        "business development director",
        "head of business development",
        "business development lead",
    ],
    "генеральный директор": [
        "генеральный директор",
        "ceo",
        "chief executive officer",
        "managing director",
        "управляющий директор",
    ],
    "исполнительный директор": [
        "исполнительный директор",
        "executive director",
        "coo",
        "chief operating officer",
    ],
    "операционный директор": [
        "операционный директор",
        "operations director",
        "coo",
        "chief operating officer",
    ],
    "финансовый директор": [
        "финансовый директор",
        "cfo",
        "finance director",
        "head of finance",
    ],
    "руководитель цифровых продуктов": [
        "руководитель цифровых продуктов",
        "head of product",
        "product lead",
        "product manager",
        "product owner",
        "chief product officer",
    ],
    "директор по цифровой трансформации": [
        "директор по цифровой трансформации",
        "head of digital transformation",
        "cdto",
        "cdo",
        "digital transformation director",
    ],
    "директор по инновациям": [
        "директор по инновациям",
        "head of innovation",
        "innovation lead",
        "innovation director",
    ],
    "руководитель проекта": [
        "руководитель проекта",
        "project manager",
        "program manager",
        "delivery manager",
    ],
}

INDUSTRY_HINTS = {
    "Продажи / Развитие бизнеса": [
        "sales",
        "commercial",
        "business development",
        "revenue",
        "partnership",
        "b2b",
        "b2c",
        "growth",
        "crm",
        "channel",
        "distribution",
    ],
    "IT / AI / Цифровая трансформация": [
        "digital",
        "product",
        "ai",
        "ml",
        "llm",
        "innovation",
        "transformation",
        "cx",
        "customer journey",
        "data",
        "technology",
    ],
    "Финансы": [
        "finance",
        "ifrs",
        "budget",
        "forecast",
        "treasury",
        "fp&a",
        "cash flow",
    ],
}

LOCATION_ALIASES = {
    "москва": ["москва", "moscow", "moskva"],
    "санкт-петербург": ["санкт-петербург", "санкт петербург", "saint petersburg", "st petersburg", "st. petersburg", "petersburg"],
    "дубай": ["дубай", "dubai"],
    "абу-даби": ["абу-даби", "абу даби", "abu dhabi"],
    "удаленно": ["remote", "удаленно", "удалённо", "hybrid", "гибрид"],
}

SKILL_EQUIVALENTS = {
    "strategy": ["sales strategy", "commercial strategy", "growth strategy", "go-to-market strategy"],
    "sales strategy": ["strategy", "commercial strategy"],
    "commercial": ["commercial management", "commercial leadership"],
    "commercial management": ["commercial", "commercial leadership"],
    "business development": ["partnerships", "channel partnerships", "new business"],
    "channel partnerships": ["business development", "partnerships"],
    "negotiation": ["negotiations"],
    "crm": ["crm systems", "pipeline management"],
    "leadership": ["team leadership", "commercial leadership", "sales leadership"],
    "p&l": ["pnl", "profit and loss"],
}


@dataclass
class ParsedVacancy:
    title: str = ""
    company: str = ""
    location: str = ""
    employment_type: str = ""
    remote: bool = False
    requirements: list[str] | None = None
    responsibilities: list[str] | None = None
    skills: list[str] | None = None
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["requirements"] = self.requirements or []
        data["responsibilities"] = self.responsibilities or []
        data["skills"] = self.skills or []
        return data


@dataclass
class VacancyMatchResult:
    relevance_score: float
    matched_skills: list[str]
    missing_skills: list[str]
    red_flags: list[str]
    agent_summary: str
    agent_rationale: str
    decision: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clean_text(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text.strip(" \n\r\t-–—:;,")


def _split_lines(text: str) -> list[str]:
    lines = []
    for raw in (text or "").splitlines():
        value = _clean_text(raw)
        if value:
            lines.append(value)
    return lines


def _normalize_text(text: str) -> str:
    value = _clean_text(text).lower()
    value = value.replace("ё", "е")
    return value


def _json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


def _json_loads(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _normalize_location_tokens(location_text: str) -> set[str]:
    normalized = _normalize_text(location_text)
    if not normalized:
        return set()

    tokens = {normalized}

    for canonical, aliases in LOCATION_ALIASES.items():
        if any(alias in normalized for alias in aliases):
            tokens.add(canonical)

    return tokens


def _locations_compatible(profile_location: str, vacancy_location: str, is_remote: bool) -> bool:
    profile_tokens = _normalize_location_tokens(profile_location)
    vacancy_tokens = _normalize_location_tokens(vacancy_location)

    if not profile_tokens or not vacancy_tokens:
        return True

    if is_remote:
        return True

    if profile_tokens & vacancy_tokens:
        return True

    profile_text = _normalize_text(profile_location)
    vacancy_text = _normalize_text(vacancy_location)

    if profile_text in vacancy_text or vacancy_text in profile_text:
        return True

    return False


def _extract_resume_text_for_agent(job_request: JobRequest) -> str:
    raw_path = (job_request.resume_file_path or "").strip()
    raw_name = (job_request.resume_file_name or "").strip()

    if not raw_path and not raw_name:
        return ""

    app_dir = Path(app.__file__).resolve().parent
    project_dir = app_dir.parent

    candidate_paths = []

    if raw_path:
        path_obj = Path(raw_path)
        if path_obj.is_absolute():
            candidate_paths.append(path_obj)
        else:
            cleaned_relative = raw_path.lstrip("./")
            candidate_paths.append(project_dir / cleaned_relative)
            candidate_paths.append(app_dir / cleaned_relative)

    if raw_name:
        candidate_paths.append(app_dir / "uploads" / "resumes" / raw_name)

    seen = set()
    resolved_candidates = []
    for item in candidate_paths:
        normalized = str(item)
        if normalized in seen:
            continue
        seen.add(normalized)
        resolved_candidates.append(item)

    file_path = next((path for path in resolved_candidates if path.exists() and path.is_file()), None)
    if not file_path:
        return ""

    try:
        from app.routes import _extract_resume_text, _clean_resume_text

        resume_text = _extract_resume_text(file_path)
        return _clean_resume_text(resume_text)
    except Exception:
        return ""


def _build_job_form_data(job_request: JobRequest) -> dict[str, Any]:
    return {
        "email": job_request.user.email if job_request.user else "",
        "query_text": job_request.query_text or "",
        "position": job_request.position or "",
        "keywords": job_request.keywords or "",
        "location": job_request.location or "",
        "salary_min": str(job_request.salary_min) if job_request.salary_min is not None else "",
        "salary_max": str(job_request.salary_max) if job_request.salary_max is not None else "",
        "employment_type": job_request.employment_type or "",
        "work_format": job_request.work_format or "",
        "remote": bool(job_request.remote),
    }


def _infer_source_name(source_name: str, source_url: str, sender_email: str) -> str:
    joined = " ".join([source_name or "", source_url or "", sender_email or ""]).lower()

    if "linkedin" in joined:
        return "linkedin"
    if "hh." in joined or "headhunter" in joined:
        return "hh"
    if "telegram" in joined or "t.me" in joined:
        return "telegram"
    if "indeed" in joined:
        return "indeed"
    if "jooble" in joined:
        return "jooble"
    if source_name:
        return _normalize_text(source_name)

    return "manual"


def _extract_section(lines: list[str], start_markers: list[str], stop_markers: list[str]) -> list[str]:
    collecting = False
    result = []

    for line in lines:
        lowered = _normalize_text(line)

        if any(marker in lowered for marker in start_markers):
            collecting = True
            continue

        if collecting and any(marker in lowered for marker in stop_markers):
            break

        if collecting:
            cleaned = re.sub(r"^[•\-\*\d\.\)\(]+\s*", "", line).strip()
            if cleaned:
                result.append(cleaned)

    deduped = []
    seen = set()
    for item in result:
        key = _normalize_text(item)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    return deduped[:12]


def _extract_title(lines: list[str], fallback: str = "") -> str:
    if fallback:
        return _clean_text(fallback)

    for line in lines[:6]:
        lowered = _normalize_text(line)
        if len(line) > 120:
            continue
        if any(marker in lowered for marker in ["обязанности", "requirements", "responsibilities", "company:", "location:"]):
            continue
        return line

    return ""


def _extract_company(lines: list[str], fallback: str = "") -> str:
    if fallback:
        return _clean_text(fallback)

    patterns = [
        r"^(?:company|компания)\s*[:\-]\s*(.+)$",
        r"^(?:employer|работодатель)\s*[:\-]\s*(.+)$",
    ]
    for line in lines[:12]:
        for pattern in patterns:
            match = re.match(pattern, line, flags=re.I)
            if match:
                return _clean_text(match.group(1))

    if len(lines) >= 2 and len(lines[1]) <= 80:
        second = _clean_text(lines[1])
        if second and second != lines[0]:
            return second

    return ""


def _extract_location(lines: list[str], fallback: str = "") -> str:
    if fallback:
        return _clean_text(fallback)

    patterns = [
        r"^(?:location|локация|город|место работы)\s*[:\-]\s*(.+)$",
    ]
    for line in lines[:15]:
        for pattern in patterns:
            match = re.match(pattern, line, flags=re.I)
            if match:
                return _clean_text(match.group(1))

    location_markers = [
        "moscow",
        "mosk",
        "москва",
        "saint petersburg",
        "санкт-петербург",
        "dubai",
        "abu dhabi",
        "remote",
        "удаленно",
    ]
    for line in lines[:15]:
        lowered = _normalize_text(line)
        if any(marker in lowered for marker in location_markers):
            return line

    return ""


def _extract_employment_type(text: str) -> str:
    lowered = _normalize_text(text)
    for normalized, markers in EMPLOYMENT_MARKERS.items():
        if any(marker in lowered for marker in markers):
            return normalized
    return ""


def _detect_remote(text: str) -> bool:
    lowered = _normalize_text(text)
    return any(marker in lowered for marker in REMOTE_MARKERS)


def _extract_skills(text: str) -> list[str]:
    lowered = _normalize_text(text)
    result = []
    seen = set()

    for marker in SKILL_MARKERS:
        if marker in lowered and marker not in seen:
            seen.add(marker)
            result.append(marker)

    return result[:12]


def _keyword_tokens(value: str) -> set[str]:
    normalized = _normalize_text(value)
    return {
        token
        for token in re.split(r"[^a-zа-я0-9\+\&]+", normalized)
        if token and len(token) > 1
    }


def _skill_variants(skill: str) -> set[str]:
    normalized = _normalize_text(skill)
    if not normalized:
        return set()

    variants = {normalized}
    for variant in SKILL_EQUIVALENTS.get(normalized, []):
        cleaned = _normalize_text(variant)
        if cleaned:
            variants.add(cleaned)

    for canonical, alias_list in SKILL_EQUIVALENTS.items():
        alias_set = {_normalize_text(x) for x in alias_list}
        if normalized in alias_set:
            variants.add(_normalize_text(canonical))
            variants.update(alias_set)

    return variants


def _skills_equivalent(left: str, right: str) -> bool:
    left_norm = _normalize_text(left)
    right_norm = _normalize_text(right)

    if not left_norm or not right_norm:
        return False

    if left_norm == right_norm:
        return True

    if left_norm in right_norm or right_norm in left_norm:
        return True

    left_variants = _skill_variants(left_norm)
    right_variants = _skill_variants(right_norm)
    if left_variants & right_variants:
        return True

    left_tokens = _keyword_tokens(left_norm)
    right_tokens = _keyword_tokens(right_norm)
    if not left_tokens or not right_tokens:
        return False

    intersection = left_tokens & right_tokens
    if not intersection:
        return False

    min_size = min(len(left_tokens), len(right_tokens))
    if min_size == 1 and len(intersection) == 1:
        return True

    return len(intersection) >= min_size


def _compare_skills(profile_keywords: list[str], vacancy_skills: list[str]) -> tuple[list[str], list[str]]:
    normalized_profile = []
    seen_profile = set()
    for item in profile_keywords:
        cleaned = _clean_text(item)
        normalized = _normalize_text(cleaned)
        if not cleaned or not normalized or normalized in seen_profile:
            continue
        seen_profile.add(normalized)
        normalized_profile.append(cleaned)

    normalized_vacancy = []
    seen_vacancy = set()
    for item in vacancy_skills:
        cleaned = _clean_text(item)
        normalized = _normalize_text(cleaned)
        if not cleaned or not normalized or normalized in seen_vacancy:
            continue
        seen_vacancy.add(normalized)
        normalized_vacancy.append(cleaned)

    matched = []
    missing = []

    for profile_skill in normalized_profile:
        if any(_skills_equivalent(profile_skill, vacancy_skill) for vacancy_skill in normalized_vacancy):
            matched.append(_normalize_text(profile_skill))
        else:
            missing.append(_normalize_text(profile_skill))

    return sorted(matched)[:10], sorted(missing)[:10]


def parse_raw_vacancy(
    raw_text: str,
    title: str = "",
    company: str = "",
    location: str = "",
) -> ParsedVacancy:
    lines = _split_lines(raw_text)
    joined_text = "\n".join(lines)

    parsed_title = _extract_title(lines, fallback=title)
    parsed_company = _extract_company(lines, fallback=company)
    parsed_location = _extract_location(lines, fallback=location)
    parsed_employment_type = _extract_employment_type(joined_text)
    parsed_remote = _detect_remote(joined_text)

    responsibilities = _extract_section(
        lines,
        start_markers=["обязанности", "responsibilities", "what you will do", "задачи"],
        stop_markers=["требования", "requirements", "мы предлагаем", "условия", "about you", "skills"],
    )
    requirements = _extract_section(
        lines,
        start_markers=["требования", "requirements", "skills", "expectations", "about you"],
        stop_markers=["мы предлагаем", "условия", "benefits", "responsibilities", "обязанности"],
    )
    skills = _extract_skills(joined_text)

    summary_parts = []
    if parsed_title:
        summary_parts.append(parsed_title)
    if parsed_company:
        summary_parts.append(parsed_company)
    if parsed_location:
        summary_parts.append(parsed_location)
    if parsed_remote:
        summary_parts.append("remote/hybrid")

    return ParsedVacancy(
        title=parsed_title,
        company=parsed_company,
        location=parsed_location,
        employment_type=parsed_employment_type,
        remote=parsed_remote,
        requirements=requirements,
        responsibilities=responsibilities,
        skills=skills,
        summary=" | ".join(summary_parts),
    )


def _role_aliases(role: str) -> list[str]:
    normalized = _normalize_text(role)
    if not normalized:
        return []
    aliases = ROLE_ALIASES.get(normalized, [])
    if aliases:
        return aliases
    return [role]


def _score_title_match(title_text: str, role: str) -> float:
    aliases = [_normalize_text(x) for x in _role_aliases(role)]
    if not aliases or not title_text:
        return 0.0

    if aliases[0] and aliases[0] in title_text:
        return 34.0

    for alias in aliases[1:]:
        if alias and alias in title_text:
            return 30.0

    best = 0.0
    for alias in aliases:
        tokens = [token for token in alias.split() if len(token) > 2]
        if not tokens:
            continue
        matched = sum(1 for token in tokens if token in title_text)
        if matched:
            score = min(22.0, matched * 7.0)
            if score > best:
                best = score

    return best


def _score_role_context(vacancy_text: str, role: str) -> float:
    aliases = [_normalize_text(x) for x in _role_aliases(role)]
    if not aliases or not vacancy_text:
        return 0.0

    best = 0.0
    for alias in aliases:
        if alias and alias in vacancy_text:
            return 18.0

        tokens = [token for token in alias.split() if len(token) > 2]
        matched = sum(1 for token in tokens if token in vacancy_text)
        if matched:
            score = min(12.0, matched * 3.5)
            if score > best:
                best = score

    return best


def _score_industry_match(vacancy_text: str, industry: str) -> float:
    industry_clean = _normalize_text(industry)
    if not industry_clean:
        return 0.0

    hints = INDUSTRY_HINTS.get(industry, [])
    score = 0.0

    if industry_clean in vacancy_text:
        score += 8.0

    matched_hints = sum(1 for hint in hints if hint in vacancy_text)
    score += min(10.0, matched_hints * 2.5)

    return score


def _score_skill_overlap(matched_skills: list[str]) -> float:
    return min(12.0, len(matched_skills) * 3.0)


def _score_search_mode(search_mode: str) -> float:
    normalized = _normalize_text(search_mode)
    if normalized == "profile_led":
        return 6.0
    if normalized == "balanced":
        return 4.0
    if normalized == "focused":
        return 2.5
    return 0.0


def _score_ambiguity_bonus(ambiguity: float) -> float:
    if ambiguity <= 0.2:
        return 4.0
    if ambiguity <= 0.35:
        return 2.0
    return 0.0


def _apply_soft_cap(score: float) -> float:
    if score <= 70.0:
        return score
    if score <= 85.0:
        return 70.0 + ((score - 70.0) * 0.65)
    return 79.75 + ((score - 85.0) * 0.35)


def _collect_red_flags(
    parsed: ParsedVacancy,
    profile: dict[str, Any],
    raw_text: str,
) -> list[str]:
    red_flags = []
    lowered = _normalize_text(raw_text)

    profile_location = _normalize_text(profile.get("location") or "")
    if profile_location and parsed.location:
        if not _locations_compatible(profile_location, parsed.location, parsed.remote):
            red_flags.append("location_mismatch")

    if "relocation" in lowered or "релокац" in lowered:
        red_flags.append("relocation_required")

    if "arabic" in lowered or "арабск" in lowered:
        red_flags.append("language_requirement")

    return red_flags[:6]


def _determine_decision(
    score: float,
    red_flags: list[str],
    matched_skills: list[str],
    missing_skills: list[str],
) -> str:
    if score >= 68.0:
        decision = "apply"
    elif score >= 45.0:
        decision = "review"
    else:
        decision = "ignore"

    critical_flags = {"relocation_required", "language_requirement"}
    if any(flag in critical_flags for flag in red_flags):
        if decision == "apply":
            decision = "review"

    if "location_mismatch" in red_flags and decision == "apply":
        decision = "review"

    if len(missing_skills) >= 6 and len(matched_skills) <= 1:
        if decision == "apply":
            decision = "review"
        elif decision == "review" and score < 55.0:
            decision = "ignore"

    if len(red_flags) >= 2 and score < 60.0:
        decision = "ignore"

    return decision


def build_vacancy_match_result(
    parsed: ParsedVacancy,
    raw_text: str,
    job_request: JobRequest,
) -> VacancyMatchResult:
    resume_text = _extract_resume_text_for_agent(job_request)
    form_data = _build_job_form_data(job_request)
    agent_plan = build_agent_plan(
        resume_text=resume_text,
        form_data=form_data,
        job_request=job_request,
    )

    profile = agent_plan.get("profile", {})
    management = agent_plan.get("management", {})
    diagnostics = agent_plan.get("diagnostics", {})

    title_text = _normalize_text(parsed.title or "")
    vacancy_text = _normalize_text(
        " ".join(
            [
                parsed.title,
                parsed.company,
                parsed.location,
                " ".join(parsed.requirements or []),
                " ".join(parsed.responsibilities or []),
                " ".join(parsed.skills or []),
                raw_text or "",
            ]
        )
    )

    primary_role = profile.get("primary_role") or ""
    industry = profile.get("industry") or ""

    title_score = _score_title_match(title_text, primary_role)
    context_score = _score_role_context(vacancy_text, primary_role)
    industry_score = _score_industry_match(vacancy_text, industry)

    profile_keywords = list(profile.get("keywords") or [])
    matched_skills, missing_skills = _compare_skills(profile_keywords, parsed.skills or [])
    skills_score = _score_skill_overlap(matched_skills)

    remote_score = 0.0
    if parsed.remote and bool(profile.get("remote")):
        remote_score = 4.0

    employment_score = 0.0
    if parsed.employment_type and profile.get("employment_type"):
        if _normalize_text(parsed.employment_type) == _normalize_text(profile.get("employment_type")):
            employment_score = 2.0

    search_mode = management.get("search_mode") or ""
    search_mode_score = _score_search_mode(search_mode)

    ambiguity = float(diagnostics.get("ambiguity_score") or 1.0)
    ambiguity_score = _score_ambiguity_bonus(ambiguity)

    raw_score = (
        title_score
        + context_score
        + industry_score
        + skills_score
        + remote_score
        + employment_score
        + search_mode_score
        + ambiguity_score
    )

    score = _apply_soft_cap(raw_score)

    red_flags = _collect_red_flags(parsed, profile, raw_text)
    red_flag_penalty = len(red_flags) * 7.0
    score -= red_flag_penalty

    if score < 1.0:
        score = 1.0
    if score > 95.0:
        score = 95.0

    decision = _determine_decision(
        score=score,
        red_flags=red_flags,
        matched_skills=matched_skills,
        missing_skills=missing_skills,
    )

    summary = (
        f"Релевантность {round(score, 1)}. "
        f"Роль кандидата: {profile.get('primary_role') or 'не определена'}. "
        f"Режим поиска: {search_mode or 'unknown'}. "
        f"Решение агента: {decision}."
    )
    rationale_parts = [
        f"role={profile.get('primary_role') or 'unknown'}",
        f"industry={industry or 'unknown'}",
        f"title_score={round(title_score, 2)}",
        f"context_score={round(context_score, 2)}",
        f"industry_score={round(industry_score, 2)}",
        f"skills_score={round(skills_score, 2)}",
        f"remote_score={round(remote_score, 2)}",
        f"employment_score={round(employment_score, 2)}",
        f"search_mode_score={round(search_mode_score, 2)}",
        f"ambiguity_score={round(ambiguity_score, 2)}",
        f"raw_score={round(raw_score, 2)}",
        f"soft_capped_score={round(_apply_soft_cap(raw_score), 2)}",
        f"red_flag_penalty={round(red_flag_penalty, 2)}",
        f"matched_skills={', '.join(matched_skills) or 'none'}",
        f"missing_skills={', '.join(missing_skills) or 'none'}",
        f"red_flags={', '.join(red_flags) or 'none'}",
        f"decision={decision}",
    ]

    return VacancyMatchResult(
        relevance_score=round(score, 2),
        matched_skills=matched_skills,
        missing_skills=missing_skills,
        red_flags=red_flags,
        agent_summary=summary,
        agent_rationale=" | ".join(rationale_parts),
        decision=decision,
    )


def create_vacancy_intake(
    job_request_id: int,
    raw_text: str,
    source_type: str = "manual",
    source_name: str = "manual",
    raw_subject: str = "",
    source_url: str = "",
    sender_email: str = "",
    title: str = "",
    company: str = "",
    location: str = "",
    external_ref: str = "",
) -> VacancyIntake:
    db = app.db_session

    job_request = db.query(JobRequest).filter(JobRequest.id == job_request_id).first()
    if not job_request:
        raise ValueError("job request not found")

    normalized_source_name = _infer_source_name(source_name, source_url, sender_email)
    parsed = parse_raw_vacancy(
        raw_text=raw_text,
        title=title,
        company=company,
        location=location,
    )

    intake = VacancyIntake(
        job_request_id=job_request.id,
        source_type=_clean_text(source_type) or "manual",
        source_name=normalized_source_name,
        external_ref=_clean_text(external_ref),
        status="parsed",
        raw_subject=_clean_text(raw_subject),
        raw_text=raw_text or "",
        source_url=_clean_text(source_url),
        sender_email=_clean_text(sender_email),
        parsed_title=parsed.title,
        parsed_company=parsed.company,
        parsed_location=parsed.location,
        parsed_employment_type=parsed.employment_type,
        parsed_remote=parsed.remote,
        parsed_payload_json=_json_dumps(parsed.to_dict()),
        parser_version="vacancy_agent_v1",
    )

    db.add(intake)
    db.commit()
    db.refresh(intake)

    return intake


def analyze_vacancy_intake(vacancy_intake_id: int) -> dict[str, Any]:
    db = app.db_session

    intake = db.query(VacancyIntake).filter(VacancyIntake.id == vacancy_intake_id).first()
    if not intake:
        raise ValueError("vacancy intake not found")

    job_request = db.query(JobRequest).filter(JobRequest.id == intake.job_request_id).first()
    if not job_request:
        raise ValueError("job request not found")

    parsed_payload = _json_loads(intake.parsed_payload_json)
    parsed = ParsedVacancy(
        title=parsed_payload.get("title") or intake.parsed_title or "",
        company=parsed_payload.get("company") or intake.parsed_company or "",
        location=parsed_payload.get("location") or intake.parsed_location or "",
        employment_type=parsed_payload.get("employment_type") or intake.parsed_employment_type or "",
        remote=bool(parsed_payload.get("remote") if parsed_payload else intake.parsed_remote),
        requirements=parsed_payload.get("requirements") or [],
        responsibilities=parsed_payload.get("responsibilities") or [],
        skills=parsed_payload.get("skills") or [],
        summary=parsed_payload.get("summary") or "",
    )

    match_result = build_vacancy_match_result(
        parsed=parsed,
        raw_text=intake.raw_text or "",
        job_request=job_request,
    )

    existing_match = (
        db.query(VacancyMatch)
        .filter(VacancyMatch.vacancy_intake_id == intake.id)
        .first()
    )

    if existing_match:
        vacancy_match = existing_match
        vacancy_match.status = "ready"
        vacancy_match.relevance_score = match_result.relevance_score
        vacancy_match.matched_skills_json = _json_dumps(match_result.matched_skills)
        vacancy_match.missing_skills_json = _json_dumps(match_result.missing_skills)
        vacancy_match.red_flags_json = _json_dumps(match_result.red_flags)
        vacancy_match.agent_summary = match_result.agent_summary
        vacancy_match.agent_rationale = match_result.agent_rationale
        vacancy_match.decision = match_result.decision
    else:
        vacancy_match = VacancyMatch(
            job_request_id=job_request.id,
            vacancy_intake_id=intake.id,
            status="ready",
            relevance_score=match_result.relevance_score,
            matched_skills_json=_json_dumps(match_result.matched_skills),
            missing_skills_json=_json_dumps(match_result.missing_skills),
            red_flags_json=_json_dumps(match_result.red_flags),
            agent_summary=match_result.agent_summary,
            agent_rationale=match_result.agent_rationale,
            decision=match_result.decision,
        )
        db.add(vacancy_match)

    existing_task = (
        db.query(VacancyActionTask)
        .filter(VacancyActionTask.vacancy_intake_id == intake.id)
        .first()
    )

    task_type = "apply" if match_result.decision == "apply" else "review" if match_result.decision == "review" else "ignore"
    priority = ACTION_PRIORITY_BY_DECISION.get(match_result.decision, "medium")

    if existing_task:
        action_task = existing_task
        action_task.task_type = task_type
        action_task.priority = priority
        action_task.status = "open"
        action_task.notes = match_result.agent_summary
    else:
        action_task = VacancyActionTask(
            job_request_id=job_request.id,
            vacancy_intake_id=intake.id,
            task_type=task_type,
            priority=priority,
            status="open",
            notes=match_result.agent_summary,
        )
        db.add(action_task)

    intake.status = "analyzed"
    db.commit()
    db.refresh(intake)
    db.refresh(vacancy_match)
    db.refresh(action_task)

    return {
        "intake": {
            "id": intake.id,
            "status": intake.status,
            "parsed_title": intake.parsed_title,
            "parsed_company": intake.parsed_company,
            "parsed_location": intake.parsed_location,
        },
        "match": match_result.to_dict(),
        "task": {
            "id": action_task.id,
            "task_type": action_task.task_type,
            "priority": action_task.priority,
            "status": action_task.status,
        },
    }


def create_generated_artifact(
    vacancy_intake_id: int,
    artifact_type: str,
    content_text: str,
    language: str = "ru",
    tone: str = "professional",
    content_json: dict[str, Any] | None = None,
) -> GeneratedArtifact:
    db = app.db_session

    intake = db.query(VacancyIntake).filter(VacancyIntake.id == vacancy_intake_id).first()
    if not intake:
        raise ValueError("vacancy intake not found")

    artifact = GeneratedArtifact(
        job_request_id=intake.job_request_id,
        vacancy_intake_id=intake.id,
        artifact_type=_clean_text(artifact_type),
        status="ready",
        language=_clean_text(language),
        tone=_clean_text(tone),
        content_text=content_text or "",
        content_json=_json_dumps(content_json or {}),
        generator_version="vacancy_agent_v1",
    )

    db.add(artifact)
    db.commit()
    db.refresh(artifact)

    return artifact


def build_recruiter_message_draft(vacancy_intake_id: int) -> str:
    db = app.db_session

    intake = db.query(VacancyIntake).filter(VacancyIntake.id == vacancy_intake_id).first()
    if not intake:
        raise ValueError("vacancy intake not found")

    match_row = (
        db.query(VacancyMatch)
        .filter(VacancyMatch.vacancy_intake_id == intake.id)
        .first()
    )

    title = intake.parsed_title or "роль"
    company = intake.parsed_company or "вашу компанию"
    summary = match_row.agent_summary if match_row else "Вакансия выглядит релевантной."

    return (
        f"Здравствуйте. Увидел вакансию {title} в {company}. "
        f"Мой профиль выглядит релевантным этому направлению. "
        f"{summary} "
        f"Буду рад кратко обсудить, насколько мой опыт может быть полезен вашей команде."
    )


def ingest_and_analyze_manual_vacancy(
    job_request_id: int,
    raw_text: str,
    source_name: str = "manual",
    raw_subject: str = "",
    source_url: str = "",
    sender_email: str = "",
    title: str = "",
    company: str = "",
    location: str = "",
    external_ref: str = "",
) -> dict[str, Any]:
    intake = create_vacancy_intake(
        job_request_id=job_request_id,
        raw_text=raw_text,
        source_type="manual",
        source_name=source_name,
        raw_subject=raw_subject,
        source_url=source_url,
        sender_email=sender_email,
        title=title,
        company=company,
        location=location,
        external_ref=external_ref,
    )
    return analyze_vacancy_intake(intake.id)
