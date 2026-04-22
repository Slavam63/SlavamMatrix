from __future__ import annotations

import re
from typing import Any


# --- Section title guards (shared by pipeline + LLM stub) ---

RESUME_SECTION_TITLE_EXACT = {
    "professional summary",
    "summary",
    "profile",
    "about",
    "about me",
    "personal profile",
    "career objective",
    "career summary",
    "executive summary",
    "overview",
    "core competencies",
    "key competencies",
    "key skills",
    "technical skills",
    "skills",
    "professional experience",
    "experience",
    "work experience",
    "employment history",
    "work history",
    "education",
    "certifications",
    "references",
    "languages",
    "projects",
    "обо мне",
    "о себе",
    "общие сведения",
    "ключевые навыки",
    "профессиональные навыки",
    "опыт работы",
    "образование",
    "контакты",
    "контактная информация",
    "contact",
    "contacts",
    "contact details",
    "contact information",
    "personal information",
    "objective",
    "дополнительная информация",
    "highlights",
    "qualifications",
}

RESUME_SECTION_TITLE_PREFIX_RE = re.compile(
    r"^(?:[\d\.\)\-–—]+\s*)?"
    r"(?:"
    r"professional\s+summary|executive\s+summary|career\s+(?:objective|summary)|"
    r"personal\s+(?:profile|information|statement)|\babout\s+me\b|"
    r"key\s+(?:skills|competencies|achievements|qualifications)|"
    r"core\s+competencies|technical\s+skills|"
    r"work\s+(?:experience|history)|professional\s+experience|employment\s+history|"
    r"education(?:al)?\s+background|academic\s+background|"
    r"certifications?|references|languages|projects|"
    r"contact\s+(?:details|information)|"
    r"обо\s+мне|о\s+себе|опыт\s+работы|образование|навыки|контакты|рекомендации"
    r")\b",
    flags=re.I,
)


def _normalize_section_heading_line(value: str) -> str:
    s = (value or "").strip()
    s = s.strip(":-–—•·●◦▪▫").strip()
    s = re.sub(r"^[\d\.\)\-–—]+\s*", "", s)
    return re.sub(r"\s+", " ", s).lower()


def is_resume_section_title_line(value: str) -> bool:
    s = _normalize_section_heading_line(value or "")
    if not s:
        return True
    if s in RESUME_SECTION_TITLE_EXACT:
        return True
    if s.rstrip(":") in RESUME_SECTION_TITLE_EXACT:
        return True
    first = s.split(":", maxsplit=1)[0].strip()
    if first in RESUME_SECTION_TITLE_EXACT:
        return True
    return bool(RESUME_SECTION_TITLE_PREFIX_RE.match((value or "").strip()))


def is_forbidden_position_title(value: str) -> bool:
    # Any section title (even with suffix) is forbidden as position.
    s = _normalize_section_heading_line(value or "")
    if not s:
        return True
    if s in RESUME_SECTION_TITLE_EXACT:
        return True
    if s.rstrip(":") in RESUME_SECTION_TITLE_EXACT:
        return True
    if s.split(":", maxsplit=1)[0].strip() in RESUME_SECTION_TITLE_EXACT:
        return True
    return bool(RESUME_SECTION_TITLE_PREFIX_RE.match((value or "").strip()))


_ROLE_WORD_CORE_RE = re.compile(
    r"\b(analyst|specialist|manager|director|lead|head|chief|officer|consultant|engineer|developer|"
    r"controller|fp\s*&\s*a|fpa|finance|financial|accounting|директор|специалист|руководител|менеджер|"
    r"аналитик|начальник|заместител)\b",
    flags=re.I,
)


def is_valid_role_candidate(value: str) -> bool:
    s = (value or "").strip()
    if not s:
        return False
    low = s.lower()
    if "professional summary" in low:
        return False
    if is_resume_section_title_line(low):
        return False
    if is_forbidden_position_title(s):
        return False
    if len(s) < 3 or len(s) > 160:
        return False
    if not _ROLE_WORD_CORE_RE.search(s):
        # FP&A содержит символ '&' и ломает \b границы; проверяем отдельно.
        if not re.search(r"fp\s*&\s*a|(?<![a-z])fpa(?![a-z])", s, flags=re.I):
            return False
    if len(s.split()) > 12:
        return False
    if re.search(r"[@]|https?://|www\.", s, flags=re.I):
        return False
    return True


# --- Pipeline: extract → normalize → validate ---


def _clean_text(text: str) -> str:
    text = (text or "").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_email(text: str) -> str:
    m = re.findall(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", text or "", flags=re.I)
    return (m[-1].strip().lower() if m else "")


def _extract_location(text: str) -> str:
    m = re.search(r"\b(Abu Dhabi|Dubai|London|Berlin|Москва|Санкт-Петербург|Remote)\b", text or "", flags=re.I)
    return (m.group(1) if m else "")


_FINANCE_SEEDS = [
    ("fp&a", r"\bfp\s*&\s*a\b|\bfpa\b"),
    ("budgeting", r"\bbudget(?:ing)?\b|бюджет"),
    ("forecasting", r"\bforecast(?:ing)?\b|прогноз"),
    ("cash flow", r"\bcash\s*flow\b|денежн(?:ый|ого)\s+поток"),
    ("p&l", r"\bp&l\b|pnl|прибыл"),
    ("kpi reporting", r"\bkpi\b|отчетн"),
    ("financial modelling", r"\bfinancial\s+model(?:ling|ing)?\b|финансов(?:ая|ое)\s+модел"),
    ("management reporting", r"\bmanagement\s+reporting\b|управленческ(?:ая|ий)\s+отчет"),
    ("ifrs", r"\bifrs\b|мсфо"),
    ("excel", r"\bexcel\b"),
    ("power query", r"\bpower\s+query\b"),
    ("vba", r"\bvba\b"),
]


def _extract_finance_keywords(text: str, limit: int = 12) -> list[str]:
    low = (text or "").lower()
    compact = low.replace(" ", "")
    out: list[str] = []
    seen: set[str] = set()
    for label, pattern in _FINANCE_SEEDS:
        if re.search(pattern, low, flags=re.I):
            key = label.lower()
            if key not in seen:
                seen.add(key)
                out.append(label)
        # Fast-path for fp&a spacing variants
        if label == "fp&a" and ("fp&a" in low or "fpa" in low or "fp&a" in compact):
            if "fp&a" not in seen:
                seen.add("fp&a")
                out.insert(0, "fp&a")
        if len(out) >= limit:
            break
    return out[:limit]


def _has_finance_context(text: str) -> bool:
    low = (text or "").lower()
    return any(re.search(pattern, low, flags=re.I) for _label, pattern in _FINANCE_SEEDS) or bool(
        re.search(r"\bfinance\b|финанс", low, flags=re.I)
    )


def _extract_target_position(text: str) -> str:
    # Conservative: only parse explicit "Желаемая должность/Position" blocks.
    src = text or ""
    m = re.search(r"(?:желаемая должность|position|objective)\s*[:\-]?\s*([^\n]{2,120})", src, flags=re.I)
    if not m:
        return ""
    candidate = m.group(1).strip()
    return candidate if is_valid_role_candidate(candidate) else ""


def _extract_headline_position(text: str, max_lines: int = 20) -> str:
    """
    Headline роль берём только из верхней части резюме и прекращаем поиск,
    если встретили заголовок секции (чтобы не «провалиться» в summary/skills).
    """
    lines = [ln.strip() for ln in (text or "").splitlines()[:max_lines] if ln.strip()]
    for line in lines:
        low = line.lower().strip()
        if not low:
            continue
        if is_resume_section_title_line(low) or is_forbidden_position_title(line):
            break
        if "professional summary" in low:
            break
        if is_valid_role_candidate(line):
            return line.strip()
    return ""


def infer_seniority(text: str, roles: list[str]) -> str:
    blob = " ".join([str(text or "")] + [str(r or "") for r in (roles or [])]).lower()
    if not blob.strip():
        return "unknown"
    if re.search(r"\b(cfo|ceo|coo|chief|head of|director|vp|vice president)\b|директор|генеральный директор", blob):
        return "executive"
    if re.search(r"\b(senior|lead|principal)\b|ведущ|старш", blob):
        return "senior"
    if re.search(r"\b(junior|intern|trainee)\b|стаж", blob):
        return "junior"
    if re.search(r"\b(analyst|specialist|manager)\b|аналитик|специалист|менеджер", blob):
        return "middle"
    return "unknown"


def infer_role_family(keywords: list[str], role: str) -> str:
    blob = " ".join([str(role or "")] + [str(k or "") for k in (keywords or [])]).lower()
    if any(h in blob for h in ("fp&a", "fpa", "ifrs", "budget", "finance", "financial", "accounting", "финанс", "бюджет")):
        return "finance"
    if any(h in blob for h in ("product", "roadmap", "backlog", "продукт")):
        return "product"
    if any(h in blob for h in ("sales", "b2b", "revenue", "продаж", "коммерческ")):
        return "sales"
    if any(h in blob for h in ("operations", "coo", "операцион", "логист")):
        return "operations"
    if any(h in blob for h in ("it", "digital", "developer", "engineer", "разработ")):
        return "it"
    return "unknown"


def extract_raw_facts(text: str) -> dict[str, Any]:
    clean_text = _clean_text(text or "")
    top = "\n".join([ln for ln in clean_text.splitlines()[:25] if ln.strip()])
    position_raw = _extract_target_position(clean_text)
    position_source_raw = "target_section" if position_raw else "fallback"
    if not position_raw:
        headline = _extract_headline_position(clean_text)
        if headline:
            position_raw = headline
            position_source_raw = "headline"

    keywords_raw: list[str] = []
    primary_industry = ""
    industry = ""
    if _has_finance_context(clean_text):
        primary_industry = "Финансы"
        industry = "Финансы"
        keywords_raw = _extract_finance_keywords(clean_text, limit=12)

    return {
        "clean_text": clean_text,
        "position_raw": position_raw,
        "position_source_raw": position_source_raw,
        "email": _extract_email(clean_text),
        "phone": "",
        "location": _extract_location(top),
        "past_roles": [],
        "primary_industry": primary_industry,
        "industry": industry,
        "employment_type": "",
        "work_format": "",
        "salary_min": None,
        "keywords_raw": keywords_raw,
    }


def normalize_facts(raw_facts: dict[str, Any]) -> dict[str, Any]:
    out = dict(raw_facts or {})
    src = str(out.get("position_source_raw") or "").strip().lower()
    if src not in ("headline", "target_section", "fallback", "llm"):
        src = "fallback"
    out["position_source_raw"] = src
    out["position_norm"] = str(out.get("position_raw") or "").strip()
    out["location_norm"] = str(out.get("location") or "").strip()
    out["email_norm"] = str(out.get("email") or "").strip().lower()
    kws = out.get("keywords_raw") or []
    if isinstance(kws, str):
        kws = [p.strip() for p in kws.split(",") if p.strip()]
    out["keywords_norm"] = [str(x).strip().lower() for x in kws if str(x).strip()]
    return out


def validate_facts(normalized_facts: dict[str, Any]) -> dict[str, Any]:
    n = dict(normalized_facts or {})
    warnings: list[str] = []

    position = str(n.get("position_norm") or "").strip()
    if position:
        low = position.lower()
        if "professional summary" in low:
            position = ""
        elif is_resume_section_title_line(low) or is_forbidden_position_title(position):
            position = ""
        elif not is_valid_role_candidate(position):
            position = ""

    if not position:
        warnings.append("Не удалось определить должность")

    location = str(n.get("location_norm") or "").strip()
    if not location:
        warnings.append("Локация не обнаружена")

    keywords = []
    for kw in list(n.get("keywords_norm") or []):
        if kw and not is_resume_section_title_line(kw) and len(kw) <= 80:
            keywords.append(kw)
        if len(keywords) >= 12:
            break

    query_text = " ".join([p for p in [position, location] if p]).strip()
    if "professional summary" in query_text.lower():
        query_text = location.strip()

    pos_source = str(n.get("position_source_raw") or "fallback").strip().lower()
    if pos_source not in ("headline", "target_section", "fallback", "llm"):
        pos_source = "fallback"
    if not position:
        pos_source = "fallback"

    return {
        **n,
        "position": position,
        "position_source": pos_source,
        "location": location,
        "email": n.get("email_norm") or "",
        "keywords": keywords,
        "query_text": query_text,
        "primary_industry": n.get("primary_industry") or "",
        "industry": n.get("industry") or "",
        "pipeline_warnings": list(dict.fromkeys(warnings)),
    }


def map_resume_to_form_data(text: str) -> dict[str, Any]:
    """
    Совместимость с UI-роутами: возвращает данные формы из pipeline.
    Это thin-wrapper вокруг extract→normalize→validate, без изменения логики.
    """
    raw = extract_raw_facts(text or "")
    normalized = normalize_facts(raw)
    validated = validate_facts(normalized)
    return {
        "email": validated.get("email") or "",
        "query_text": validated.get("query_text") or "",
        "position": validated.get("position") or "",
        "keywords": ", ".join(validated.get("keywords") or []),
        "location": validated.get("location") or "",
        "salary_min": validated.get("salary_min") or "",
        "salary_max": "",
        "employment_type": validated.get("employment_type") or "",
        "work_format": validated.get("work_format") or "",
        "remote": False,
        # Diagnostics
        "position_source": validated.get("position_source") or "",
        "llm_used": "",
        "warnings": validated.get("pipeline_warnings") or [],
    }

