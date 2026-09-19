"""Natural-language analyst for Tatiana — deterministic engine + optional LLM hook.

Without CASTDEV_LLM_API_KEY / OPENAI_API_KEY the deterministic engine produces a
rich Russian narrative report (context, N из D, %, quotes, факт vs наблюдение).
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

from . import classify, config, db, labels_ru, stats
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
        "want_quotes": bool(re.search(r"цитат|формулир|как\s+пишут|пример|raw|сырые", q)),
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


def _context_block(dataset: Dataset, total: int, latest: str | None) -> list[str]:
    ds_label = labels_ru.DATASET_LABELS.get(dataset, dataset)
    lines = [
        f"Контекст. Набор данных: «{ds_label}» (CASTDEV09.26).",
        f"В выборке сейчас {total} анкет.",
    ]
    disp = stats.format_msk(latest)
    if disp:
        lines.append(f"Последнее поступление: {disp}.")
    return lines


def _fact_line(label: str, block: dict[str, Any]) -> str:
    return f"• {label}: {block['numerator']} из {block['denominator']} — {block['percentage']}%."


def _quotes_block(quotes: list[dict[str, Any]]) -> list[str]:
    if not quotes:
        return []
    lines = ["", "Характерные формулировки (RAW, без искажений):"]
    for q in quotes:
        title = labels_ru.QUESTION_TITLES.get(q["question"], q["question"])
        lines.append(f"• [{title}] «{q['quote']}»")
    return lines


def _observations_block(observations: list[str]) -> list[str]:
    if not observations:
        return []
    lines = ["", "Наблюдения (интерпретация методики, не прямой ответ респондентов):"]
    for o in observations:
        lines.append(f"• {o}")
    return lines


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
    latest = db.latest_created_at(conn, dataset) if total else None
    ds_label = labels_ru.DATASET_LABELS.get(dataset, dataset)

    base = {
        "ok": True,
        "mode": "llm" if llm_available() else "deterministic",
        "llm_available": llm_available(),
        "dataset": dataset,
        "dataset_label": ds_label,
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
            f"Контекст. В наборе «{ds_label}» пока нет анкет CASTDEV09.26.\n"
            "Факт: 0 из 0 — н/д.\n"
            "Недостаточно данных для анализа; ответ не выдуман."
        )
        base["facts"] = []
        base["observations"] = []
        return base

    if intent["kind"] == "insufficient":
        base["answer_text"] = "\n".join(
            _context_block(dataset, total, latest)
            + [
                "",
                "Факты:",
                "• По этой теме в базе CASTDEV09.26 релевантных ответов нет: "
                f"0 из {total} — 0%.",
                "",
                "Вывод: недостаточно данных — ответ не выдуман.",
            ]
        )
        base["facts"] = [stats.pct(0, total) | {"label": "релевантных ответов"}]
        return base

    facts: list[dict[str, Any]] = []
    observations: list[str] = []
    quotes: list[dict[str, Any]] = []
    sections: list[str] = []

    facts.append({"label": "всего анкет", **stats.pct(total, total)})
    sections.extend(_context_block(dataset, total, latest))

    if intent["kind"] in ("overview", "quantitative", "focused"):
        sm = stats.summary(conn, dataset)
        p7 = sm["period_7d"]
        facts.append({"label": "за 7 дней", **{k: p7[k] for k in ("numerator", "denominator", "percentage", "display")}})
        sections.append("")
        sections.append("Факты по выборке:")
        sections.append(_fact_line("Всего анкет", stats.pct(total, total)))
        sections.append(
            f"• За последние 7 дней поступило: {p7['numerator']} из {p7['denominator']} "
            f"— {p7['percentage']}%."
        )

        if intent["kind"] == "focused":
            sections.append("")
            sections.append(
                "Фокус: "
                + ", ".join(
                    f"{labels_ru.QUESTION_TITLES[q]} ({labels_ru.QUESTION_PROMPTS_SHORT[q]})"
                    for q in intent["questions"]
                )
                + "."
            )
            matrix = sm["feature_matrix"]
            for qn in intent["questions"]:
                block = matrix.get(qn)
                if not block:
                    continue
                sections.append("")
                sections.append(
                    f"Смысловые признаки — {block['title']} "
                    f"({block['prompt']}):"
                )
                shown = 0
                for col in block["columns"]:
                    if col["numerator"] <= 0:
                        continue
                    sections.append(_fact_line(col["title"], col))
                    facts.append(
                        {
                            "label": col["label_ru"],
                            "numerator": col["numerator"],
                            "denominator": col["denominator"],
                            "percentage": col["percentage"],
                            "display": col["display"],
                        }
                    )
                    shown += 1
                if shown == 0:
                    sections.append("• Пока ни один признак не сработал на этой выборке.")
        else:
            top = sm["features"]["features"][:8]
            if top:
                sections.append("")
                sections.append(
                    "Ведущие смысловые категории (не простой подсчёт слов):"
                )
                for f in top:
                    label = labels_ru.feature_value_ru(f["feature_key"], f["feature_value"])
                    sections.append(_fact_line(label, f))
                    facts.append(
                        {
                            "label": label,
                            "numerator": f["numerator"],
                            "denominator": f["denominator"],
                            "percentage": f["percentage"],
                            "display": f["display"],
                        }
                    )
            observations.append(
                "Категории строятся по semantic_rules_v1: позиция вокруг канала "
                "(позитив / негатив / отказ / нейтрально), критерии решения, "
                "точки трения, намерение изменить или сохранить подход."
            )

    if intent["kind"] == "channel_stance" or intent.get("channel"):
        ch = intent.get("channel") or "hh"
        ch_ru = labels_ru.CHANNEL_LABELS.get(ch, ch)
        opp = stats.opposing_stances(conn, ch, dataset)
        sections.append("")
        sections.append(
            f"Факты: отношение к каналу «{ch_ru}» "
            "(смысловая позиция, а не просто упоминание слова):"
        )
        for stance in (
            "positive_use",
            "negative_while_using",
            "abandoned",
            "mentioned_neutral",
        ):
            block = opp[stance]
            label = labels_ru.stance_ru(stance)
            sections.append(_fact_line(label, block))
            facts.append(
                {
                    "label": f"{ch_ru}: {label}",
                    **{
                        k: block[k]
                        for k in ("numerator", "denominator", "percentage", "display")
                    },
                }
            )
        observations.append(opp["note"])
        observations.append(
            "Разные формулировки вроде «использую и получаю результат», "
            "«использую, но бесполезно» и «больше не использую» попадают "
            "в разные доли, даже если канал один и тот же."
        )
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
            elif ch != "hh":
                # soft match via channel forms in q1
                if ch_ru.lower() in t.lower() or ch in t.lower():
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
        sections.append("")
        sections.append("Факты: динамика поступления по дням (UTC-дата записи):")
        for d in dyn[-14:]:
            sections.append(f"• {d['date']}: {d['count']} анкет")
        facts.append(
            {"label": "дней с поступлениями", **stats.pct(len(dyn), len(dyn) or 1)}
        )
        if len(dyn) >= 2:
            observations.append(
                f"За период наблюдений поступления шли в {len(dyn)} календарных днях; "
                "это поток заполнений, а не оценка качества ответов."
            )

    if intent["kind"] == "contradiction" or intent["want_contradiction"]:
        classes = db.fetch_classifications(conn, dataset)
        contras = [c for c in classes if c["feature_key"] == "contradiction"]
        n = len({c["response_id"] for c in contras})
        block = stats.pct(n, total)
        sections.append("")
        sections.append("Факты: межвопросные противоречия (эвристика методики):")
        sections.append(_fact_line("Есть метка противоречия", block))
        facts.append({"label": "contradiction", **block})
        for c in contras[:5]:
            observations.append(
                f"Метка «{labels_ru.feature_value_ru(c['feature_key'], c['feature_value'])}» "
                f"у анкеты {c['response_id'][:8]}…"
            )
        observations.append(
            "Это аналитическая метка методики, а не прямой ответ респондентов."
        )

    if intent["want_quotes"] or intent["kind"] == "focused":
        for qn in intent["questions"]:
            quotes.extend(_citations(responses, qn, limit=3))

    # Deduplicate quotes by (response_id, question)
    seen = set()
    uniq_quotes = []
    for q in quotes:
        key = (q.get("response_id"), q.get("question"), q.get("quote"))
        if key in seen:
            continue
        seen.add(key)
        uniq_quotes.append(q)
    quotes = uniq_quotes[:10]

    sections.extend(_quotes_block(quotes))
    sections.extend(_observations_block(observations))
    sections.append("")
    sections.append(
        "Разделение: строки «Факты» опираются на базу CASTDEV09.26; "
        "строки «Наблюдения» — интерпретация методики."
    )

    answer_text = "\n".join(sections)

    result = {
        **base,
        "answer_text": answer_text,
        "facts": facts,
        "observations": observations,
        "quotes": quotes,
        "classification_note": classify.explain_not_keyword_only(),
        # Do not surface LLM/integration junk in admin UI
        "capability_note": None,
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

    return result


def _llm_enrich(question: str, structured: dict, sample: list[dict]) -> str | None:
    """Optional OpenAI-compatible chat. Only called when API key present."""
    payload = {
        "model": config.LLM_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Ты аналитик CASTDEV09.26. Пиши связный русский отчёт: "
                    "контекст, факты с «N из D — %», цитаты RAW, наблюдения отдельно. "
                    "Не выдумывай. Не упоминай API-ключи, пути к файлам и технические детали."
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
