import re

import requests

from app.config import Config


HH_API_BASE_URL = "https://api.hh.ru"
HH_USER_AGENT = "MatrixParser/1.0 (labinfluences.ru)"

PYTHON_TITLE_STRONG_PATTERNS = [
    r"\bpython\b",
    r"\bdjango\b",
    r"\bfastapi\b",
    r"\bflask\b",
]

PYTHON_BODY_POSITIVE_PATTERNS = [
    r"\bpython\b",
    r"\bdjango\b",
    r"\bfastapi\b",
    r"\bflask\b",
    r"\bdrf\b",
    r"\basyncio\b",
    r"\bcelery\b",
    r"\bpostgresql\b",
    r"\bpostgres\b",
]

NEGATIVE_STACK_PATTERNS = [
    r"\bnode(?:[\s\.\-]*js)?\b",
    r"\bjavascript\b",
    r"\btypescript\b",
    r"\bphp\b",
    r"\blaravel\b",
    r"\bsymfony\b",
    r"\bbitrix\b",
    r"\bjava\b",
    r"\bspring\b",
    r"\bkotlin\b",
    r"\bscala\b",
    r"\bc#\b",
    r"\b\.net\b",
    r"\basp\.net\b",
    r"\bgolang\b",
    r"\bruby\b",
    r"\brails\b",
    r"\b1c\b",
]

GENERAL_BACKEND_TITLE_PATTERNS = [
    r"\bbackend\b",
    r"\bback-end\b",
    r"\bbackend-разработчик\b",
    r"\bbackend разработчик\b",
    r"\bbackend developer\b",
    r"\bbackend engineer\b",
    r"\bведущий backend\b",
    r"\bbackend-инженер\b",
    r"\bбэкенд\b",
]

FULLSTACK_TITLE_PATTERNS = [
    r"\bfullstack\b",
    r"\bfull stack\b",
    r"\bfull-stack\b",
]

NEGATIVE_ALLOWED_CONTEXT_PATTERNS = [
    r"\b(?:node(?:[\s\.\-]*js)?|javascript|typescript|go|golang|java)\b\s+(?:будет|как)?\s*плюс",
    r"\bplus\b",
    r"\bnice to have\b",
    r"\boptional\b",
    r"\bбудет плюсом\b",
    r"\bкак плюс\b",
    r"\bкак преимущество\b",
    r"\bжелательно\b",
    r"\bбудет преимуществом\b",
    r"\bопционально\b",
]

STRONG_NEGATIVE_CONTEXT_PATTERNS = [
    r"\bpython\s+или\s+java\b",
    r"\bjava\s+или\s+python\b",
    r"\bpython\s+или\s+node(?:[\s\.\-]*js)?\b",
    r"\bnode(?:[\s\.\-]*js)?\s+или\s+python\b",
    r"\bpython\s+and\s+node(?:[\s\.\-]*js)?\b",
    r"\bnode(?:[\s\.\-]*js)?\s+and\s+python\b",
    r"\bpython\s+and\s+java\b",
    r"\bjava\s+and\s+python\b",
    r"\bна\s+python\s+и\s+node(?:[\s\.\-]*js)?\b",
    r"\bnode(?:[\s\.\-]*js)?\b.*\bpython\b",
    r"\bpython\b.*\bnode(?:[\s\.\-]*js)?\b",
    r"\bjava\b.*\bpython\b",
    r"\bpython\b.*\bjava\b",
    r"\bphp\b.*\bpython\b",
    r"\bpython\b.*\bphp\b",
    r"\bgolang\b.*\bpython\b",
    r"\bpython\b.*\bgolang\b",
]

GENERIC_NOISE_TITLE_PATTERNS = [
    r"\bрекрутер\b",
    r"\bhr\b",
    r"\bподбор персонала\b",
    r"\bпомощник\b",
    r"\bassistant\b",
    r"\bассистент\b",
    r"\bличный помощник\b",
    r"\bстаж[её]р\b",
    r"\bintern\b",
    r"\bменеджер по продажам\b",
    r"\bруководитель отдела продаж\b",
    r"\bпродаж\b",
    r"\bsales\b",
    r"\bмаркетолог\b",
    r"\bмаркетинга\b",
    r"\bproduct marketing\b",
    r"\baccount manager\b",
    r"\bоператор\b",
    r"\bcall[- ]center\b",
    r"\bредакц",
    r"\bглавный редактор\b",
    r"\bдиректор колледжа\b",
    r"\bобучени[ея]\b",
    r"\bedtech\b",
]

HEAVY_NEGATIVE_TITLE_PATTERNS = [
    r"\bгенеральный директор\b",
    r"\bceo\b",
    r"\bисполнительный директор\b",
    r"\bcoo\b",
    r"\bоперационный директор\b",
    r"\bкоммерческий директор\b",
    r"\bдиректор по продажам\b",
    r"\bдиректор по маркетингу\b",
    r"\bpr[- ]директор\b",
    r"\bдиректор по pr\b",
]

PRODUCT_POSITIVE_TITLE_PATTERNS = [
    r"\bруководитель цифровых продуктов\b",
    r"\bруководитель цифрового продукта\b",
    r"\bруководитель продукта\b",
    r"\bруководитель по продуктам\b",
    r"\bproduct manager\b",
    r"\bhead of product\b",
    r"\bproduct lead\b",
    r"\bменеджер продукта\b",
    r"\bвладелец продукта\b",
    r"\bproduct owner\b",
]

TRANSFORMATION_POSITIVE_TITLE_PATTERNS = [
    r"\bдиректор по цифровой трансформации\b",
    r"\bруководитель по цифровой трансформации\b",
    r"\bруководитель цифровой трансформации\b",
    r"\bруководитель отдела цифровой трансформации\b",
    r"\bhead of digital transformation\b",
    r"\bcdto\b",
    r"\bcdo\b",
]

INNOVATION_POSITIVE_TITLE_PATTERNS = [
    r"\bдиректор по инновациям\b",
    r"\bруководитель направления инноваций\b",
    r"\bруководитель лаборатории инноваций\b",
    r"\bруководитель центра инноваций\b",
    r"\bhead of innovation\b",
    r"\binnovation lead\b",
]

PROJECT_POSITIVE_TITLE_PATTERNS = [
    r"\bруководитель проекта\b",
    r"\bруководитель проектов\b",
    r"\bруководитель крупных цифровых проектов\b",
    r"\bproject manager\b",
    r"\bprogram manager\b",
    r"\bpmo\b",
]

DIGITAL_CONTEXT_PATTERNS = [
    r"\bцифров",
    r"\bdigital\b",
    r"\bai\b",
    r"\bml\b",
    r"\bllm\b",
    r"\binnovation\b",
    r"\bинновац",
    r"\bproduct\b",
    r"\bпродукт",
    r"\bcustomer journey\b",
    r"\bcx\b",
    r"\bux\b",
    r"\bmvp\b",
    r"\bportfolio\b",
    r"\broadmap\b",
]

TRAVEL_CONTEXT_PATTERNS = [
    r"\btravel\b",
    r"\bhospitality\b",
    r"\bтуризм\b",
    r"\bгостеприим",
    r"\btrip\b",
    r"\bcustomer journey\b",
    r"\bcx\b",
]

COMMERCIAL_ENTERPRISE_TITLE_PATTERNS = [
    r"\bкоммерческий директор\b",
    r"\bcco\b",
    r"\bchief commercial officer\b",
    r"\bcommercial director\b",
    r"\bдиректор по продажам\b",
    r"\bsales director\b",
    r"\bhead of sales\b",
    r"\bдиректор по развитию бизнеса\b",
    r"\bbusiness development director\b",
    r"\bhead of business development\b",
    r"\benterprise sales director\b",
    r"\bchannel sales director\b",
    r"\bpartner sales director\b",
    r"\bregional sales director\b",
]

COMMERCIAL_ENTERPRISE_CONTEXT_PATTERNS = [
    r"\benterprise\b",
    r"\benterprise sales\b",
    r"\benterprise software\b",
    r"\bsoftware\b",
    r"\bsoftware sales\b",
    r"\bsaas\b",
    r"\bcloud\b",
    r"\bcloud sales\b",
    r"\bcloud solutions\b",
    r"\bit solutions\b",
    r"\binformation security\b",
    r"\bsecurity\b",
    r"\bvendor\b",
    r"\bвендор",
    r"\bpartner\b",
    r"\bpartner sales\b",
    r"\bchannel\b",
    r"\bchannel sales\b",
    r"\bканальн",
    r"\bпартнерск",
    r"\bb2b\b",
    r"\bcrm\b",
    r"\berp\b",
    r"\boracle\b",
    r"\bibm\b",
    r"\bveritas\b",
    r"\bмойофис\b",
    r"\bmyoffice\b",
]

ROLE_GROUP_PATTERNS = {
    "project_management": [
        r"\bруководитель проекта\b",
        r"\bруководитель проектов\b",
        r"\bproject manager\b",
        r"\bprogram manager\b",
        r"\bdelivery manager\b",
        r"\bpmo\b",
    ],
    "product_management": [
        r"\bруководитель цифровых продуктов\b",
        r"\bруководитель цифрового продукта\b",
        r"\bруководитель продукта\b",
        r"\bруководитель по продуктам\b",
        r"\bдиректор по продукту\b",
        r"\bproduct manager\b",
        r"\bhead of product\b",
        r"\bproduct lead\b",
        r"\bchief product officer\b",
        r"\bменеджер продукта\b",
        r"\bвладелец продукта\b",
        r"\bproduct owner\b",
    ],
    "digital_transformation": [
        r"\bдиректор по цифровой трансформации\b",
        r"\bруководитель цифровой трансформации\b",
        r"\bруководитель по цифровой трансформации\b",
        r"\bруководитель отдела цифровой трансформации\b",
        r"\bhead of digital transformation\b",
        r"\bcdto\b",
        r"\bcdo\b",
        r"\bдиректор по инновациям\b",
        r"\bhead of innovation\b",
        r"\binnovation lead\b",
        r"\bруководитель лаборатории инноваций\b",
        r"\bруководитель центра инноваций\b",
    ],
    "finance": [
        r"\bфинансовый директор\b",
        r"\bcfo\b",
        r"\bfinance director\b",
        r"\bhead of finance\b",
    ],
    "commercial_it_enterprise": COMMERCIAL_ENTERPRISE_TITLE_PATTERNS,
}

INDUSTRY_PATTERNS = {
    "it_ai_digital": [
        r"\bit\b",
        r"\bdigital\b",
        r"\bai\b",
        r"\bllm\b",
        r"\bml\b",
        r"\bцифров",
        r"\bинновац",
        r"\bdata science\b",
        r"\bproduct\b",
        r"\bcustomer journey\b",
        r"\bcx\b",
    ],
    "travel_hospitality": [
        r"\btravel\b",
        r"\bhospitality\b",
        r"\bтуризм\b",
        r"\bгостеприим",
        r"\bотел",
        r"\bcx\b",
        r"\bcustomer experience\b",
        r"\bcustomer journey\b",
    ],
    "finance": [
        r"\bфинанс",
        r"\bbank",
        r"\bбан",
        r"\btreasury\b",
    ],
    "logistics": [
        r"\bлогист",
        r"\bscm\b",
        r"\bsupply chain\b",
        r"\btransport\b",
    ],
    "commercial_it_enterprise": COMMERCIAL_ENTERPRISE_CONTEXT_PATTERNS,
}

ROLE_TO_GROUP = {
    "руководитель проекта": "project_management",
    "project manager": "project_management",
    "program manager": "project_management",
    "руководитель цифровых продуктов": "product_management",
    "руководитель цифрового продукта": "product_management",
    "руководитель продукта": "product_management",
    "head of product": "product_management",
    "product manager": "product_management",
    "product owner": "product_management",
    "директор по цифровой трансформации": "digital_transformation",
    "директор по инновациям": "digital_transformation",
    "руководитель лаборатории инноваций": "digital_transformation",
    "финансовый директор": "finance",
    "cfo": "finance",
    "коммерческий директор": "commercial_it_enterprise",
    "commercial director": "commercial_it_enterprise",
    "chief commercial officer": "commercial_it_enterprise",
    "директор по продажам": "commercial_it_enterprise",
    "sales director": "commercial_it_enterprise",
    "head of sales": "commercial_it_enterprise",
    "директор по развитию бизнеса": "commercial_it_enterprise",
    "business development director": "commercial_it_enterprise",
    "head of business development": "commercial_it_enterprise",
    "enterprise sales director": "commercial_it_enterprise",
    "channel sales director": "commercial_it_enterprise",
    "partner sales director": "commercial_it_enterprise",
}

INDUSTRY_TO_GROUP = {
    "it / ai / цифровая трансформация": "it_ai_digital",
    "туризм / гостеприимство": "travel_hospitality",
    "финансы": "finance",
    "логистика": "logistics",
    "продажи / развитие бизнеса": "commercial_it_enterprise",
    "enterprise software": "commercial_it_enterprise",
}


def _clean_text_for_matching(value):
    if not value:
        return ""

    text = str(value).lower()
    text = text.replace("c++", "cpp")
    text = text.replace("node. js", "node.js")
    text = text.replace("node js", "nodejs")
    text = text.replace("phyton", "python")
    text = re.sub(r"[^\w\s\.\-\+#/]", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _normalize_keywords(keywords):
    normalized = []

    for keyword in keywords or []:
        keyword_text = str(keyword).strip()
        if keyword_text:
            normalized.append(keyword_text)

    return normalized


def _matches_any_pattern(text: str, patterns):
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _count_pattern_matches(text: str, patterns):
    count = 0
    for pattern in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            count += 1
    return count


def _normalize_payload_value_list(values):
    result = []
    seen = set()

    for item in values or []:
        cleaned = str(item or "").strip()
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        result.append(cleaned)

    return result


def _is_python_focused_payload(payload: dict):
    combined_parts = [
        payload.get("position") or "",
        payload.get("query_text") or "",
        " ".join(_normalize_keywords(payload.get("keywords") or [])),
    ]
    combined_text = _clean_text_for_matching(" ".join(combined_parts))

    python_markers = [
        "python",
        "django",
        "fastapi",
        "flask",
        "backend",
        "back-end",
    ]

    return any(marker in combined_text for marker in python_markers)


def _is_commercial_it_enterprise_payload(payload: dict):
    product_domain = _clean_text_for_matching((payload.get("agent_profile") or {}).get("product_domain") or "")
    if product_domain == "commercial_it_enterprise":
        return True

    combined_parts = [
        payload.get("position") or "",
        payload.get("query_text") or "",
        " ".join(_normalize_keywords(payload.get("keywords") or [])),
        " ".join(_normalize_keywords(payload.get("industry_variants") or [])),
        " ".join(_normalize_keywords(payload.get("role_variants") or [])),
    ]
    combined_text = _clean_text_for_matching(" ".join(combined_parts))
    return _count_pattern_matches(combined_text, COMMERCIAL_ENTERPRISE_CONTEXT_PATTERNS) >= 2 or _matches_any_pattern(
        combined_text,
        COMMERCIAL_ENTERPRISE_TITLE_PATTERNS,
    )


def _get_role_group(payload: dict):
    position = _clean_text_for_matching(payload.get("position") or "")
    role_variants = [_clean_text_for_matching(x) for x in payload.get("role_variants") or []]

    for value in [position] + role_variants:
        if not value:
            continue
        for role_name, group_name in ROLE_TO_GROUP.items():
            if role_name in value:
                return group_name

    return None


def _get_industry_group(payload: dict):
    query_text = _clean_text_for_matching(payload.get("query_text") or "")
    industry_variants = [_clean_text_for_matching(x) for x in payload.get("industry_variants") or []]

    for value in [query_text] + industry_variants:
        if not value:
            continue
        for industry_name, group_name in INDUSTRY_TO_GROUP.items():
            if industry_name in value:
                return group_name

    return None


def _build_hh_python_text(payload: dict):
    position = str(payload.get("position") or "").strip()
    query_text = str(payload.get("query_text") or "").strip()
    keywords = _normalize_keywords(payload.get("keywords") or [])

    base_parts = []

    if position:
        base_parts.append(position)

    if query_text and query_text.lower() != position.lower():
        base_parts.append(query_text)

    for keyword in keywords:
        keyword_lower = keyword.lower()
        if keyword_lower not in {"python", "backend", "back-end"}:
            base_parts.append(keyword)

    required_parts = ["Python", "backend"]
    optional_parts = ["Django", "FastAPI", "Flask"]

    search_parts = []
    if base_parts:
        search_parts.append(" ".join(base_parts[:4]))

    search_parts.append(" ".join(required_parts))
    search_parts.append(" OR ".join(optional_parts))

    negative_parts = [
        "Node.js",
        "JavaScript",
        "TypeScript",
        "PHP",
        "Laravel",
        "Bitrix",
        "Java",
        "Spring",
        "Kotlin",
        "Scala",
        "C#",
        ".NET",
        "Golang",
    ]

    return " ".join(search_parts + [f"NOT {item}" for item in negative_parts]).strip()


def _build_hh_commercial_text(payload: dict):
    position = str(payload.get("position") or "").strip()
    scenario_name = _clean_text_for_matching(payload.get("scenario_name") or "")
    role_variants = _normalize_payload_value_list(payload.get("role_variants") or [])
    keywords = _normalize_payload_value_list(payload.get("keywords") or [])
    location = str(payload.get("location") or "").strip()

    text_parts = []

    if "channel" in scenario_name or "partner" in scenario_name:
        text_parts.extend(["Channel Sales Director", "Partner Sales Director"])
    elif "security" in scenario_name or "vendor" in scenario_name:
        text_parts.extend(["Commercial Director", "enterprise software", "information security"])
    elif "cloud" in scenario_name or "saas" in scenario_name:
        text_parts.extend(["Business Development Director", "cloud", "SaaS"])
    elif "enterprise" in scenario_name:
        text_parts.extend(["Commercial Director", "enterprise software"])

    if position:
        text_parts.append(position)

    for item in role_variants[:3]:
        if item.lower() != position.lower():
            text_parts.append(item)

    domain_keywords = []
    for item in keywords:
        lowered = item.lower()
        if any(token in lowered for token in ["enterprise", "software", "cloud", "saas", "vendor", "channel", "partner", "security", "crm", "erp"]):
            domain_keywords.append(item)

    if not domain_keywords:
        domain_keywords = [
            "enterprise sales",
            "enterprise software",
            "cloud",
            "vendor sales",
        ]

    text_parts.extend(domain_keywords[:3])

    compact = []
    seen = set()
    for part in text_parts:
        cleaned = str(part).strip()
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        compact.append(cleaned)

    text = " ".join(compact[:6]).strip()
    if location and "moscow" not in text.lower() and "москва" not in text.lower():
        text = f"{text} {location}".strip()

    return text


def _build_hh_general_text(payload: dict):
    position = str(payload.get("position") or "").strip()
    query_text = str(payload.get("query_text") or "").strip()
    keywords = _normalize_keywords(payload.get("keywords") or [])
    role_variants = _normalize_keywords(payload.get("role_variants") or [])
    industry_variants = _normalize_keywords(payload.get("industry_variants") or [])

    text_parts = []

    if position:
        text_parts.append(position)

    for item in role_variants[:2]:
        if item.lower() != position.lower():
            text_parts.append(item)

    if query_text and query_text.lower() != position.lower():
        text_parts.append(query_text)

    for item in industry_variants[:2]:
        lowered = item.lower()
        if lowered not in {position.lower(), query_text.lower()}:
            text_parts.append(item)

    for item in keywords[:3]:
        lowered = item.lower()
        if lowered not in {position.lower(), query_text.lower()}:
            text_parts.append(item)

    final_parts = []
    seen = set()
    for part in text_parts:
        cleaned = str(part).strip()
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        final_parts.append(cleaned)

    return " ".join(final_parts[:6]).strip()


def _build_hh_text(payload: dict):
    if _is_python_focused_payload(payload):
        return _build_hh_python_text(payload)

    if _is_commercial_it_enterprise_payload(payload):
        return _build_hh_commercial_text(payload)

    return _build_hh_general_text(payload)


def _build_hh_params(payload: dict):
    params = {
        "text": _build_hh_text(payload),
        "page": 0,
        "per_page": min(Config.PARSER_RESULTS_LIMIT, 50),
    }

    if payload.get("salary_min") is not None:
        params["salary"] = int(payload["salary_min"])

    return params


def _extract_salary_text(salary_data):
    if not salary_data:
        return None

    salary_from = salary_data.get("from")
    salary_to = salary_data.get("to")
    currency = salary_data.get("currency")

    parts = []
    if salary_from is not None:
        parts.append(f"from {salary_from}")
    if salary_to is not None:
        parts.append(f"to {salary_to}")
    if currency:
        parts.append(str(currency))

    return " ".join(parts) if parts else None


def _clean_hh_text(value):
    if not value:
        return None

    text = str(value)
    text = re.sub(r"</?highlighttext>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _has_negative_stack_only_as_plus(description_text: str):
    if not _matches_any_pattern(description_text, NEGATIVE_STACK_PATTERNS):
        return False

    if _matches_any_pattern(description_text, STRONG_NEGATIVE_CONTEXT_PATTERNS):
        return False

    return _matches_any_pattern(description_text, NEGATIVE_ALLOWED_CONTEXT_PATTERNS)


def _title_has_strong_positive(title_text: str):
    return (
        _matches_any_pattern(title_text, PRODUCT_POSITIVE_TITLE_PATTERNS)
        or _matches_any_pattern(title_text, TRANSFORMATION_POSITIVE_TITLE_PATTERNS)
        or _matches_any_pattern(title_text, INNOVATION_POSITIVE_TITLE_PATTERNS)
        or _matches_any_pattern(title_text, PROJECT_POSITIVE_TITLE_PATTERNS)
    )


def _title_has_commercial_enterprise_positive(title_text: str):
    return _matches_any_pattern(title_text, COMMERCIAL_ENTERPRISE_TITLE_PATTERNS)


def _score_commercial_it_enterprise_vacancy(payload: dict, title: str, description: str):
    title_text = _clean_text_for_matching(title or "")
    description_text = _clean_text_for_matching(description or "")
    combined_text = _clean_text_for_matching(" ".join([title or "", description or ""]))
    score = 0

    if _matches_any_pattern(title_text, GENERIC_NOISE_TITLE_PATTERNS):
        score -= 10

    if _title_has_commercial_enterprise_positive(title_text):
        score += 18

    score += 4 * _count_pattern_matches(title_text, COMMERCIAL_ENTERPRISE_TITLE_PATTERNS)
    score += 3 * _count_pattern_matches(combined_text, COMMERCIAL_ENTERPRISE_CONTEXT_PATTERNS)

    role_group = _get_role_group(payload)
    if role_group == "commercial_it_enterprise":
        score += 4 * _count_pattern_matches(title_text, ROLE_GROUP_PATTERNS["commercial_it_enterprise"])

    for keyword in _normalize_keywords(payload.get("keywords") or [])[:8]:
        keyword_text = _clean_text_for_matching(keyword)
        if not keyword_text or len(keyword_text) < 2:
            continue
        if keyword_text in title_text:
            score += 4
        elif keyword_text in description_text:
            score += 1.5

    scenario_name = _clean_text_for_matching(payload.get("scenario_name") or "")
    if "cloud" in scenario_name or "saas" in scenario_name:
        if any(token in combined_text for token in ["cloud", "saas", "software", "enterprise"]):
            score += 8
    if "security" in scenario_name or "vendor" in scenario_name:
        if any(token in combined_text for token in ["security", "vendor", "partner", "channel", "enterprise"]):
            score += 8
    if "enterprise" in scenario_name:
        if "enterprise" in combined_text or "software" in combined_text:
            score += 7

    position = _clean_text_for_matching(payload.get("position") or "")
    if position:
        if position in title_text:
            score += 10
        else:
            matched_tokens = sum(1 for token in position.split() if len(token) > 3 and token in title_text)
            score += min(matched_tokens * 3, 9)

    return score


def _score_management_vacancy(payload: dict, title: str, description: str):
    if _is_commercial_it_enterprise_payload(payload):
        return _score_commercial_it_enterprise_vacancy(payload, title, description)

    title_text = _clean_text_for_matching(title or "")
    description_text = _clean_text_for_matching(description or "")
    combined_text = _clean_text_for_matching(" ".join([title or "", description or ""]))

    score = 0

    if _matches_any_pattern(title_text, GENERIC_NOISE_TITLE_PATTERNS):
        score -= 12

    if _matches_any_pattern(title_text, HEAVY_NEGATIVE_TITLE_PATTERNS):
        score -= 14

    if _matches_any_pattern(title_text, PRODUCT_POSITIVE_TITLE_PATTERNS):
        score += 14

    if _matches_any_pattern(title_text, TRANSFORMATION_POSITIVE_TITLE_PATTERNS):
        score += 14

    if _matches_any_pattern(title_text, INNOVATION_POSITIVE_TITLE_PATTERNS):
        score += 12

    if _matches_any_pattern(title_text, PROJECT_POSITIVE_TITLE_PATTERNS):
        score += 7

    role_group = _get_role_group(payload)
    if role_group and role_group in ROLE_GROUP_PATTERNS:
        score += 6 * _count_pattern_matches(title_text, ROLE_GROUP_PATTERNS[role_group])
        score += 2 * _count_pattern_matches(description_text, ROLE_GROUP_PATTERNS[role_group])

    industry_group = _get_industry_group(payload)
    if industry_group and industry_group in INDUSTRY_PATTERNS:
        score += 3 * _count_pattern_matches(combined_text, INDUSTRY_PATTERNS[industry_group])

    score += 2 * _count_pattern_matches(combined_text, DIGITAL_CONTEXT_PATTERNS)

    if _matches_any_pattern(combined_text, TRAVEL_CONTEXT_PATTERNS):
        score += 3

    for keyword in _normalize_keywords(payload.get("keywords") or [])[:6]:
        keyword_text = _clean_text_for_matching(keyword)
        if not keyword_text or len(keyword_text) < 2:
            continue
        if keyword_text in title_text:
            score += 3
        elif keyword_text in description_text:
            score += 1

    position = _clean_text_for_matching(payload.get("position") or "")
    if position:
        if position in title_text:
            score += 8
        else:
            matched_tokens = sum(1 for token in position.split() if len(token) > 3 and token in title_text)
            score += min(matched_tokens * 2, 6)

    scenario_name = _clean_text_for_matching(payload.get("scenario_name") or "")
    if "travel" in scenario_name and _matches_any_pattern(combined_text, TRAVEL_CONTEXT_PATTERNS):
        score += 5

    if "product" in scenario_name and _matches_any_pattern(title_text, PRODUCT_POSITIVE_TITLE_PATTERNS):
        score += 4

    if "transformation" in scenario_name and _matches_any_pattern(title_text, TRANSFORMATION_POSITIVE_TITLE_PATTERNS):
        score += 4

    if "innovation" in scenario_name and _matches_any_pattern(title_text, INNOVATION_POSITIVE_TITLE_PATTERNS):
        score += 4

    return score


def _is_relevant_vacancy(payload: dict, title: str, description: str):
    if _is_python_focused_payload(payload):
        title_text = _clean_text_for_matching(title or "")
        description_text = _clean_text_for_matching(description or "")
        combined_text = _clean_text_for_matching(" ".join([title or "", description or ""]))

        title_has_python = _matches_any_pattern(title_text, PYTHON_TITLE_STRONG_PATTERNS)
        body_has_python = _matches_any_pattern(combined_text, PYTHON_BODY_POSITIVE_PATTERNS)
        title_has_negative = _matches_any_pattern(title_text, NEGATIVE_STACK_PATTERNS)
        body_has_negative = _matches_any_pattern(description_text, NEGATIVE_STACK_PATTERNS)
        title_is_general_backend = _matches_any_pattern(title_text, GENERAL_BACKEND_TITLE_PATTERNS)
        title_is_fullstack = _matches_any_pattern(title_text, FULLSTACK_TITLE_PATTERNS)

        if not body_has_python:
            return False

        if title_has_negative:
            return False

        if body_has_negative and not _has_negative_stack_only_as_plus(description_text):
            if not title_has_python:
                return False

        if title_has_python:
            return True

        if title_is_fullstack:
            return True

        if title_is_general_backend:
            return _matches_any_pattern(description_text, PYTHON_TITLE_STRONG_PATTERNS)

        return not body_has_negative or _has_negative_stack_only_as_plus(description_text)

    title_text = _clean_text_for_matching(title or "")
    description_text = _clean_text_for_matching(description or "")
    combined_text = _clean_text_for_matching(" ".join([title or "", description or ""]))

    if _is_commercial_it_enterprise_payload(payload):
        if _matches_any_pattern(title_text, GENERIC_NOISE_TITLE_PATTERNS) and not _title_has_commercial_enterprise_positive(title_text):
            return False

        commercial_context_hits = _count_pattern_matches(combined_text, COMMERCIAL_ENTERPRISE_CONTEXT_PATTERNS)
        if not _title_has_commercial_enterprise_positive(title_text) and commercial_context_hits < 2:
            return False

        score = _score_commercial_it_enterprise_vacancy(payload, title, description or "")
        return score >= 10

    if _matches_any_pattern(title_text, HEAVY_NEGATIVE_TITLE_PATTERNS) and not _title_has_strong_positive(title_text):
        return False

    if _matches_any_pattern(title_text, GENERIC_NOISE_TITLE_PATTERNS) and not _title_has_strong_positive(title_text):
        return False

    if not _matches_any_pattern(combined_text, DIGITAL_CONTEXT_PATTERNS) and not _title_has_strong_positive(title_text):
        return False

    score = _score_management_vacancy(payload, title, description or "")
    return score >= 8


def _compute_ai_score(payload: dict, title: str, description: str):
    if _is_python_focused_payload(payload):
        return 53.0

    if _is_commercial_it_enterprise_payload(payload):
        score = 55 + _score_commercial_it_enterprise_vacancy(payload, title, description or "") * 2
        if score < 1:
            score = 1
        if score > 100:
            score = 100
        return float(score)

    score = 50 + _score_management_vacancy(payload, title, description or "") * 2
    if score < 1:
        score = 1
    if score > 100:
        score = 100
    return float(score)


def search_hh_vacancies(payload: dict):
    params = _build_hh_params(payload)

    response = requests.get(
        f"{HH_API_BASE_URL}/vacancies",
        params=params,
        headers={"User-Agent": HH_USER_AGENT},
        timeout=20,
    )
    response.raise_for_status()

    data = response.json()
    items = data.get("items", [])

    vacancies = []

    for item in items:
        employer = item.get("employer") or {}
        area = item.get("area") or {}
        snippet = item.get("snippet") or {}

        title = _clean_hh_text(item.get("name")) or "Untitled vacancy"

        description_parts = [
            _clean_hh_text(snippet.get("requirement")),
            _clean_hh_text(snippet.get("responsibility")),
        ]
        description = " | ".join(part for part in description_parts if part) or None

        if not _is_relevant_vacancy(payload, title, description or ""):
            continue

        vacancies.append(
            {
                "source": "hh",
                "external_id": item.get("id"),
                "title": title,
                "company": _clean_hh_text(employer.get("name")),
                "location": _clean_hh_text(area.get("area")) if isinstance(area, dict) and area.get("area") else _clean_hh_text(area.get("name")),
                "salary": _extract_salary_text(item.get("salary")),
                "url": item.get("alternate_url") or item.get("url") or "",
                "description": description,
                "employment_type": None,
                "remote": bool(payload.get("remote", False)),
                "ai_score": _compute_ai_score(payload, title, description or ""),
                "scenario_name": payload.get("scenario_name"),
            }
        )

    vacancies.sort(key=lambda item: item.get("ai_score") or 0, reverse=True)
    return vacancies
