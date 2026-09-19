"""Semantic classification for open answers — stance/sense, not keyword counts.

Critical: mentioning «HH» is not one category. We classify *attitude / usage stance*
around a channel (positive use, negative while using, abandoned, etc.).
"""

from __future__ import annotations

import re
from typing import Any

# Channel lexicon: surface forms → canonical channel id
CHANNEL_FORMS: list[tuple[str, re.Pattern[str]]] = [
    ("hh", re.compile(r"\b(?:hh|хх|head[\s-]?hunter|хед[\s-]?хантер)\b", re.I)),
    ("linkedin", re.compile(r"\b(?:linkedin|линкедин|linked\s*in)\b", re.I)),
    ("recruiters", re.compile(r"\b(?:рекрутер\w*|агентств\w*|хедхантер\w*)\b", re.I)),
    ("network", re.compile(r"\b(?:знаком\w*|сети|нетворкинг|рекомендац\w*|сарафан\w*)\b", re.I)),
    ("direct", re.compile(r"\b(?:прямые?\s+обращени\w*|напрямую|cold\s*mail|письмо\s+в\s+компан)\b", re.I)),
    ("telegram", re.compile(r"\b(?:telegram|телеграм)\b", re.I)),
]

# Stance cues — applied in window around a channel mention
POS_USE = re.compile(
    r"(?:работа\w*|помощ\w*|отклик\w*|результат\w*|эффектив\w*|полезн\w*|получа\w*|наход\w*|через\s+него|через\s+неё|реально\s+работает)",
    re.I,
)
NEG_WHILE_USING = re.compile(
    r"(?:бесполезн\w*|не\s+работает|пуст\w*\s+отклик|без\s+результата|трат\w*\s+время|не\s+считаю\s+работающ|формальн\w*)",
    re.I,
)
ABANDONED = re.compile(
    r"(?:больше\s+не\s+использу|перестал\w*\s+использу|не\s+использую|отказал\w*|уш[её]л\w*\s+с|забросил\w*)",
    re.I,
)

# Q2 decision criteria (semantic themes)
Q2_CRITERIA: list[tuple[str, re.Pattern[str]]] = [
    ("role_content", re.compile(r"(?:содержани\w*\s+рол|смысл\s+работ|задач\w*|функционал)", re.I)),
    ("level", re.compile(r"(?:уровень\s+позиц|грей|c-level|топ[\s-]?менедж|директорск)", re.I)),
    ("company", re.compile(r"(?:компани\w*|бренд|репутаци\w*\s+работодател)", re.I)),
    ("compensation", re.compile(r"(?:доход|компенсац|зарплат|пакет|equity|бонус)", re.I)),
    ("industry", re.compile(r"(?:отрасл|индустри|сектор|вертикал)", re.I)),
    ("specific_vacancy", re.compile(r"(?:конкретн\w*\s+ваканси|уже\s+есть\s+список|таргет[\s-]?лист)", re.I)),
]

# Q3 friction points
Q3_FRICTION: list[tuple[str, re.Pattern[str]]] = [
    ("first_contact", re.compile(r"(?:перв\w*\s+контакт|достучать|не\s+отвеча\w*|гейтkeeper|ассистент)", re.I)),
    ("interest_experience", re.compile(r"(?:заинтерес\w*|упаковк\w*\s+опыт|резюме|питч|не\s+замеча\w*)", re.I)),
    ("interview", re.compile(r"(?:интервью|собеседован|много\s+этап|loop)", re.I)),
    ("terms", re.compile(r"(?:услови\w*|оффер|торг|компенсац\w*\s+на\s+финале)", re.I)),
    ("other", re.compile(r"(?:другое|вообще\s+в\s+другом|не\s+в\s+этом)", re.I)),
]

# Q4 change vs keep
Q4_CHANGE = re.compile(r"(?:менял|измен|пересмотр|усил|сфокусир|отказ\w*\s+от)", re.I)
Q4_KEEP = re.compile(r"(?:не\s+менял|сохран|оставл|правильн\w*|точно\s+не\s+трог)", re.I)


def _window(text: str, start: int, end: int, radius: int = 80) -> str:
    a = max(0, start - radius)
    b = min(len(text), end + radius)
    return text[a:b]


def classify_channel_stances(text: str, question: str = "q1") -> list[dict[str, Any]]:
    """Return stance features per mentioned channel — not a flat 'mentions HH' flag."""
    out: list[dict[str, Any]] = []
    for channel, pat in CHANNEL_FORMS:
        for m in pat.finditer(text):
            ctx = _window(text, m.start(), m.end())
            if ABANDONED.search(ctx):
                stance = "abandoned"
            elif NEG_WHILE_USING.search(ctx):
                stance = "negative_while_using"
            elif POS_USE.search(ctx):
                stance = "positive_use"
            else:
                # Mentioned without clear stance — separate bucket, not merged with positive.
                stance = "mentioned_neutral"
            out.append(
                {
                    "question": question,
                    "feature_key": f"channel_stance:{channel}",
                    "feature_value": stance,
                    "confidence": 0.85 if stance != "mentioned_neutral" else 0.55,
                    "method": "semantic_rules_v1",
                }
            )
            break  # one stance per channel per answer
    return out


def classify_q2(text: str) -> list[dict[str, Any]]:
    out = []
    for key, pat in Q2_CRITERIA:
        if pat.search(text):
            out.append(
                {
                    "question": "q2",
                    "feature_key": "decision_criterion",
                    "feature_value": key,
                    "confidence": 0.8,
                    "method": "semantic_rules_v1",
                }
            )
    return out


def classify_q3(text: str) -> list[dict[str, Any]]:
    out = []
    for key, pat in Q3_FRICTION:
        if pat.search(text):
            out.append(
                {
                    "question": "q3",
                    "feature_key": "friction",
                    "feature_value": key,
                    "confidence": 0.8,
                    "method": "semantic_rules_v1",
                }
            )
    return out


def classify_q4(text: str) -> list[dict[str, Any]]:
    out = []
    if Q4_CHANGE.search(text):
        out.append(
            {
                "question": "q4",
                "feature_key": "intent",
                "feature_value": "wants_change",
                "confidence": 0.75,
                "method": "semantic_rules_v1",
            }
        )
    if Q4_KEEP.search(text):
        out.append(
            {
                "question": "q4",
                "feature_key": "intent",
                "feature_value": "wants_keep",
                "confidence": 0.75,
                "method": "semantic_rules_v1",
            }
        )
    return out


def classify_response(q1: str, q2: str, q3: str, q4: str) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    features.extend(classify_channel_stances(q1, "q1"))
    # Channels may also appear in other answers with stance
    for qn, text in (("q2", q2), ("q3", q3), ("q4", q4)):
        features.extend(classify_channel_stances(text, qn))
    features.extend(classify_q2(q2))
    features.extend(classify_q3(q3))
    features.extend(classify_q4(q4))
    # Cross-answer contradiction signal: positive HH in q1 + abandoned HH in q4
    stances_q1 = {(f["feature_key"], f["feature_value"]) for f in features if f["question"] == "q1"}
    stances_q4 = {(f["feature_key"], f["feature_value"]) for f in features if f["question"] == "q4"}
    for ch in ("hh", "linkedin", "recruiters", "network", "direct"):
        k = f"channel_stance:{ch}"
        if (k, "positive_use") in stances_q1 and (k, "abandoned") in stances_q4:
            features.append(
                {
                    "question": "cross",
                    "feature_key": "contradiction",
                    "feature_value": f"{ch}_positive_then_abandoned",
                    "confidence": 0.7,
                    "method": "semantic_rules_v1",
                }
            )
    return features


def explain_not_keyword_only() -> str:
    return (
        "Классификация учитывает смысловую позицию вокруг упоминания канала: "
        "positive_use / negative_while_using / abandoned / mentioned_neutral. "
        "Ответы «HH использую и получаю отклики», «HH использую, но бесполезен», "
        "«HH больше не использую» попадают в разные feature_value при одном channel."
    )
