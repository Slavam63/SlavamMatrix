import re


IT_STRONG_MARKERS = [
    "product manager",
    "product owner",
    "head of product",
    "director of product",
    "chief product officer",
    "cpo",
    "digital product",
    "software product",
    "saas",
    "b2b saas",
    "roadmap",
    "backlog",
    "scrum",
    "agile",
    "kanban",
    "ux",
    "ui",
    "user journey",
    "product analytics",
    "product discovery",
    "product development",
    "mobile app",
    "web app",
    "api",
    "platform",
    "product metrics",
    "a/b test",
    "retention",
    "activation",
    "conversion funnel",
    "продакт-менеджер",
    "продакт менеджер",
    "менеджер продукта",
    "владелец продукта",
    "директор по продукту",
    "руководитель продукта",
    "продуктовая команда",
    "цифровой продукт",
    "ит-продукт",
    "it-продукт",
    "аналитика продукта",
    "продуктовая аналитика",
    "разработка продукта",
    "команда разработки",
    "разработчики",
    "мобильное приложение",
    "веб-приложение",
]

IT_WEAK_MARKERS = [
    "product",
    "продукт",
    "продуктовый",
    "цифровой",
    "разработка",
    "разработчик",
    "developer",
    "engineering",
    "software",
    "application",
    "app",
    "metric",
    "метрики",
    "гипотез",
    "hypothesis",
    "analytics",
    "аналитика",
]

FOOD_STRONG_MARKERS = [
    "продукты питания",
    "пищевая промышленность",
    "пищевая продукция",
    "продовольственные товары",
    "fmcg",
    "food products",
    "food production",
    "food distribution",
    "grocery",
    "groceries",
    "retail chain",
    "consumer goods",
    "fresh products",
    "horeca",
    "category manager",
    "бакалея",
    "молочная продукция",
    "мясная продукция",
    "свежие продукты",
    "производство продуктов питания",
    "товары повседневного спроса",
]

FOOD_WEAK_MARKERS = [
    "food",
    "fmcg",
    "horeca",
    "пищевая",
    "продоволь",
    "бакалея",
    "молочная",
    "мясная продукция",
    "свежие продукты",
]


def _normalize_text(text: str) -> str:
    text = (text or "").replace("\r", "\n").lower()
    text = text.replace("ё", "е")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _collect_context_windows(text: str, target_terms: list[str], window: int = 18) -> list[str]:
    normalized = _normalize_text(text)
    if not normalized:
        return []

    words = normalized.split()
    if not words:
        return []

    normalized_targets = [term.strip().lower().replace("ё", "е") for term in target_terms if term.strip()]
    windows = []

    for idx, word in enumerate(words):
        clean_word = re.sub(r"^[^\wа-яa-z0-9]+|[^\wа-яa-z0-9]+$", "", word)
        if not clean_word:
            continue

        matched = False
        for term in normalized_targets:
            if " " in term:
                continue
            if clean_word == term or clean_word.startswith(term):
                matched = True
                break

        if matched:
            start = max(0, idx - window)
            end = min(len(words), idx + window + 1)
            windows.append(" ".join(words[start:end]))

    for term in normalized_targets:
        if " " not in term:
            continue
        for match in re.finditer(re.escape(term), normalized):
            left_part = normalized[: match.start()]
            start_idx = max(0, len(left_part.split()) - window)
            end_idx = min(len(words), len(left_part.split()) + len(term.split()) + window)
            windows.append(" ".join(words[start_idx:end_idx]))

    if not windows:
        windows.append(normalized)

    return windows[:30]


def _score_markers(text_blocks: list[str], strong_markers: list[str], weak_markers: list[str]) -> tuple[int, list[str]]:
    score = 0
    matched = []

    for block in text_blocks:
        for marker in strong_markers:
            if marker in block:
                score += 3
                if marker not in matched:
                    matched.append(marker)

        for marker in weak_markers:
            if marker in block:
                score += 1
                if marker not in matched:
                    matched.append(marker)

    return score, matched


def _score_role_title_bonus(normalized_text: str) -> tuple[int, int, list[str], list[str]]:
    it_bonus = 0
    food_bonus = 0
    it_matches = []
    food_matches = []

    lines = [line.strip() for line in normalized_text.splitlines() if line.strip()]
    top_lines = lines[:20]

    for line in top_lines:
        if any(
            marker in line
            for marker in [
                "product manager",
                "product owner",
                "head of product",
                "director of product",
                "chief product officer",
                "директор по продукту",
                "руководитель продукта",
                "продакт-менеджер",
                "продакт менеджер",
                "владелец продукта",
            ]
        ):
            it_bonus += 4
            if line not in it_matches:
                it_matches.append(line)

        if any(
            marker in line
            for marker in [
                "продукты питания",
                "food",
                "fmcg",
                "пищевая продукция",
                "пищевая промышленность",
                "retail",
                "ритейл",
                "horeca",
            ]
        ) and ("product manager" not in line and "директор по продукту" not in line):
            food_bonus += 4
            if line not in food_matches:
                food_matches.append(line)

    return it_bonus, food_bonus, it_matches, food_matches


def _score_combo_bonus(text_blocks: list[str]) -> tuple[int, int, list[str], list[str]]:
    it_bonus = 0
    food_bonus = 0
    it_matches = []
    food_matches = []

    it_combos = [
        ("product manager", "roadmap"),
        ("product owner", "backlog"),
        ("директор по продукту", "разработ"),
        ("saas", "продукт"),
        ("продуктовая команда", "разработ"),
        ("product", "analytics"),
        ("product", "ux"),
        ("product", "ui"),
        ("product", "api"),
    ]

    food_combos = [
        ("продукты питания", "ассортимент"),
        ("fmcg", "закуп"),
        ("food", "retail"),
        ("поставщик", "категор"),
        ("пищевая", "дистрибуц"),
        ("продоволь", "сеть"),
    ]

    for block in text_blocks:
        for left, right in it_combos:
            if left in block and right in block:
                it_bonus += 3
                combo = f"{left} + {right}"
                if combo not in it_matches:
                    it_matches.append(combo)

        for left, right in food_combos:
            if left in block and right in block:
                food_bonus += 3
                combo = f"{left} + {right}"
                if combo not in food_matches:
                    food_matches.append(combo)

    return it_bonus, food_bonus, it_matches, food_matches


def _confidence_from_scores(it_score: int, food_score: int, domain: str) -> float:
    if domain == "unknown":
        if max(it_score, food_score) == 0:
            return 0.0
        if abs(it_score - food_score) <= 1:
            return 0.35
        return 0.45

    diff = abs(it_score - food_score)
    top = max(it_score, food_score)

    if top >= 14 and diff >= 6:
        return 0.93
    if top >= 10 and diff >= 4:
        return 0.84
    if top >= 7 and diff >= 3:
        return 0.74
    return 0.62


def detect_product_domain(text: str) -> dict:
    normalized_text = _normalize_text(text)
    if not normalized_text:
        return {
            "product_domain": "unknown",
            "confidence": 0.0,
            "matched_markers": [],
            "explanation": "Empty resume text",
            "it_score": 0,
            "food_score": 0,
        }

    target_terms = [
        "product manager",
        "product owner",
        "директор по продукту",
        "руководитель продукта",
        "продукты питания",
        "food products",
        "пищевая продукция",
    ]

    windows = _collect_context_windows(normalized_text, target_terms, window=18)
    text_blocks = windows + [normalized_text]

    it_score, it_markers = _score_markers(text_blocks, IT_STRONG_MARKERS, IT_WEAK_MARKERS)
    food_score, food_markers = _score_markers(text_blocks, FOOD_STRONG_MARKERS, FOOD_WEAK_MARKERS)

    it_role_bonus, food_role_bonus, it_role_matches, food_role_matches = _score_role_title_bonus(normalized_text)
    it_score += it_role_bonus
    food_score += food_role_bonus

    it_combo_bonus, food_combo_bonus, it_combo_matches, food_combo_matches = _score_combo_bonus(text_blocks)
    it_score += it_combo_bonus
    food_score += food_combo_bonus

    all_it_matches = []
    for item in it_markers + it_role_matches + it_combo_matches:
        if item not in all_it_matches:
            all_it_matches.append(item)

    all_food_matches = []
    for item in food_markers + food_role_matches + food_combo_matches:
        if item not in all_food_matches:
            all_food_matches.append(item)

    if it_score >= food_score + 3:
        domain = "it_product"
        matched = all_it_matches
        explanation = "Detected IT product context from product-management and digital markers"
    elif food_score >= it_score + 5 and food_score >= 6:
        domain = "food_product"
        matched = all_food_matches
        explanation = "Detected food/FMCG product context from strong food markers"
    else:
        domain = "unknown"
        matched = []
        explanation = "Context is ambiguous or insufficient"

    return {
        "product_domain": domain,
        "confidence": _confidence_from_scores(it_score, food_score, domain),
        "matched_markers": matched[:20],
        "explanation": explanation,
        "it_score": it_score,
        "food_score": food_score,
    }
