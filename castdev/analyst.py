"""Natural-language analyst for Tatiana — deterministic engine + optional LLM hook.

Does NOT invent a Cursor API. If CASTDEV_LLM_API_KEY / OPENAI_API_KEY missing:
web chat uses rule-based retrieval over CASTDEV DB + honest capability note.
Snapshot export lets Cursor agent answer offline.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

from . import classify, config, db, stats
from .db import Dataset


def llm_available() -> bool:
    return bool(config.LLM_API_KEY)


def _citations(responses: list[dict], question: str, limit: int = 5) -> list[dict]:
    out = []
    for r in responses:
        text = (r.get(question) or "").strip()
        if text:
            out.append(
                {
                    "response_id": r["response_id"],
                    "question": question,
                    "quote": text[:400],
                    "created_at": r["created_at"],
                }
            )
        if len(out) >= limit:
            break
    return out


def _detect_intent(question: str) -> dict[str, Any]:
    q = question.lower().strip()
    intent = {
        "kind": "overview",
        "questions": ["q1", "q2", "q3", "q4"],
        "want_quotes": bool(re.search(r"цитат|формулир|как\s+пишут|пример", q)),
        "want_trend": bool(re.search(r"динамик|тенденц|со\s+времен|по\s+дням", q)),
        "want_contradiction": bool(re.search(r"противореч|расхожд", q)),
        "want_compare": bool(re.search(r"сравн|versus|vs\b|против", q)),
        "want_count": bool(re.search(r"сколько|число|количеств|процент|доля|%\b", q)),
        "channel": None,
        "insufficient_ok": bool(
            re.search(r"марс|марсиан|инопланет|несуществующ|юпитер|атлантид", q)
        ),
    }
    qs = []
    if re.search(r"\bq1\b|перв(ый|ому|ого)\s+вопрос|как\s+ищут", q):
        qs.append("q1")
    if re.search(r"\bq2\b|втор(ой|ому)|реша(ют|ете).*позиц|критер", q):
        qs.append("q2")
    if re.search(r"\bq3\b|трет(ий|ьему)|после\s+того|сложност|фрикц", q):
        qs.append("q3")
    if re.search(r"\bq4\b|четвёрт|четверт|изменил|не\s+менял", q):
        qs.append("q4")
    if qs:
        intent["questions"] = qs
        intent["kind"] = "focused"

    for ch, pat in (
        ("hh", r"\bhh\b|хедхантер|headhunter"),
        ("linkedin", r"linkedin|линкедин"),
        ("recruiters", r"рекрутер"),
        ("network", r"знаком|нетворкинг|рекомендац"),
        ("direct", r"прям(ые|ое)\s+обращен"),
    ):
        if re.search(pat, q, re.I):
            intent["channel"] = ch
            intent["kind"] = "channel_stance"
            break

    if intent["want_contradiction"]:
        intent["kind"] = "contradiction"
    elif intent["want_trend"]:
        intent["kind"] = "trend"
    elif intent["want_compare"] and intent["channel"]:
        intent["kind"] = "channel_stance"
    elif intent["want_count"] and intent["kind"] == "overview":
        intent["kind"] = "quantitative"

    if intent["insufficient_ok"]:
        intent["kind"] = "insufficient"

    return intent


def answer(conn, question: str, *, dataset: Dataset = "production") -> dict[str, Any]:
    question = (question or "").strip()
    if not question:
        return {
            "ok": False,
            "error": "Пустой вопрос.",
            "mode": "deterministic",
        }

    responses = db.fetch_all_responses(conn, dataset)
    total = len(responses)
    intent = _detect_intent(question)

    base = {
        "ok": True,
        "mode": "llm" if llm_available() else "deterministic",
        "llm_available": llm_available(),
        "dataset": dataset,
        "total_responses": total,
        "intent": intent,
        "source": "CASTDEV09.26 database",
        "disclaimer": (
            "Источник истины — база CASTDEV09.26. "
            "Интерпретации помечены отдельно от фактов. "
            "Общие знания о рынке труда не подменяют данные исследования."
        ),
    }

    if total == 0:
        base["answer_text"] = (
            "В выбранном массиве пока нет анкет. "
            "Недостаточно данных для анализа."
        )
        base["facts"] = []
        base["observations"] = []
        return base

    if intent["kind"] == "insufficient":
        base["answer_text"] = (
            "В массиве CASTDEV09.26 нет данных по этой теме. "
            "Недостаточно данных — ответ не выдуман."
        )
        base["facts"] = [
            stats.pct(0, total) | {"label": "релевантных ответов"},
        ]
        return base

    facts: list[dict[str, Any]] = []
    observations: list[str] = []
    quotes: list[dict[str, Any]] = []
    parts: list[str] = []

    facts.append({"label": "всего анкет", **stats.pct(total, total)})

    if intent["kind"] in ("overview", "quantitative", "focused"):
        sm = stats.summary(conn, dataset)
        facts.append({"label": "за 7 дней", **sm["period_7d"]})
        parts.append(f"Всего заполнено анкет: {total}.")
        if sm["latest"]:
            parts.append(f"Последнее поступление: {sm['latest']}.")
        # Top features with denom
        top = sm["features"]["features"][:8]
        if top:
            parts.append("Смысловые категории (не keyword-count):")
            for f in top:
                parts.append(
                    f"— {f['feature_key']}={f['feature_value']}: {f['display']}"
                )
                facts.append(
                    {
                        "label": f"{f['feature_key']}={f['feature_value']}",
                        "numerator": f["numerator"],
                        "denominator": f["denominator"],
                        "percentage": f["percentage"],
                        "display": f["display"],
                    }
                )

    if intent["kind"] == "channel_stance" or intent.get("channel"):
        ch = intent.get("channel") or "hh"
        opp = stats.opposing_stances(conn, ch, dataset)
        parts.append(
            f"Отношение к каналу «{ch}» (смысловые позиции, не просто упоминания слова):"
        )
        for stance in ("positive_use", "negative_while_using", "abandoned", "mentioned_neutral"):
            block = opp[stance]
            parts.append(f"— {stance}: {block['display']}")
            facts.append({"label": f"{ch}:{stance}", **{k: block[k] for k in ("numerator", "denominator", "percentage", "display")}})
        observations.append(opp["note"])
        # Quotes for opposing HH examples
        for r in responses:
            t = r["q1"]
            if ch == "hh" and re.search(r"hh|хх|head", t, re.I):
                quotes.append(
                    {
                        "response_id": r["response_id"],
                        "question": "q1",
                        "quote": t[:400],
                    }
                )
            if len(quotes) >= 6:
                break

    if intent["kind"] == "trend" or intent["want_trend"]:
        dyn = stats.inflow_dynamics(conn, dataset)
        parts.append("Динамика поступления по дням (факт из базы):")
        for d in dyn[-14:]:
            parts.append(f"— {d['date']}: {d['count']}")
        facts.append({"label": "дней с поступлениями", **stats.pct(len(dyn), len(dyn) or 1)})

    if intent["kind"] == "contradiction" or intent["want_contradiction"]:
        classes = db.fetch_classifications(conn, dataset)
        contras = [c for c in classes if c["feature_key"] == "contradiction"]
        n = len({c["response_id"] for c in contras})
        parts.append(
            f"Признак межвопросного противоречия (эвристика semantic_rules_v1): "
            f"{stats.pct(n, total)['display']}"
        )
        facts.append({"label": "contradiction", **stats.pct(n, total)})
        observations.append(
            "Это аналитическая метка методики, не прямой ответ респондентов."
        )

    if intent["want_quotes"] or intent["kind"] == "focused":
        for qn in intent["questions"]:
            quotes.extend(_citations(responses, qn, limit=3))

    if not parts:
        parts.append(f"В массиве {total} анкет. Уточните вопрос для узкого среза.")

    answer_text = "\n".join(parts)
    if observations:
        answer_text += "\n\nНаблюдения / интерпретации:\n- " + "\n- ".join(observations)

    result = {
        **base,
        "answer_text": answer_text,
        "facts": facts,
        "observations": observations,
        "quotes": quotes[:10],
        "classification_note": classify.explain_not_keyword_only(),
    }

    if llm_available():
        try:
            enriched = _llm_enrich(question, result, responses[:40])
            if enriched:
                result["answer_text"] = enriched
                result["mode"] = "llm"
        except Exception as exc:  # noqa: BLE001 — surface honestly
            result["llm_error"] = str(exc)
            result["mode"] = "deterministic_fallback"

    if not llm_available():
        result["capability_note"] = (
            "LLM API credential отсутствует (CASTDEV_LLM_API_KEY / OPENAI_API_KEY). "
            "Ответ сформирован детерминированным аналитическим движком по базе CASTDEV09.26. "
            "Точка интеграции LLM готова (castdev/analyst.py::_llm_enrich). "
            "Временный путь: GET /api/admin/snapshot → выгрузка для агента Cursor."
        )

    return result


def _llm_enrich(question: str, structured: dict, sample: list[dict]) -> str | None:
    """Optional OpenAI-compatible chat. Only called when API key present."""
    payload = {
        "model": config.LLM_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Ты аналитик CASTDEV09.26. Отвечай только по переданным данным. "
                    "Для долей всегда указывай numerator из denominator. "
                    "Не выдумывай. Помечай интерпретации. Цитаты не искажай."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "question": question,
                        "structured": {
                            k: structured[k]
                            for k in (
                                "facts",
                                "observations",
                                "quotes",
                                "total_responses",
                                "answer_text",
                            )
                            if k in structured
                        },
                        "sample_responses": sample,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "temperature": 0.2,
    }
    req = urllib.request.Request(
        f"{config.LLM_API_BASE.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.LLM_API_KEY}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]
