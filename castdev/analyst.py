"""Natural-language analyst for Tatiana — research memo + optional LLM hook.

Without LLM key: deterministic analytical memo in Russian.
Honest about limits; never invents market knowledge as data.
"""

from __future__ import annotations

import json
import re
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
        "want_cross": bool(
            re.search(r"связ|сочета|одних\s+и\s+тех|межвопрос|пересечен", q)
        ),
        "channel": None,
        "insufficient_ok": bool(
            re.search(r"марс|марсиан|инопланет|несуществующ|юпитер|атлантид", q)
        ),
        "needs_open_llm": bool(
            re.search(
                r"напиши\s+эссе|сочини|придумай|как\s+на\s+рынке\s+вообще|"
                r"по\s+твоему\s+мнению\s+без\s+данных|предскажи\s+будущ",
                q,
            )
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
    elif intent["want_cross"]:
        intent["kind"] = "cross"
    elif intent["want_trend"]:
        intent["kind"] = "trend"
    elif intent["want_compare"] and intent["channel"]:
        intent["kind"] = "channel_stance"
    elif intent["want_count"] and intent["kind"] == "overview":
        intent["kind"] = "quantitative"

    if intent["insufficient_ok"]:
        intent["kind"] = "insufficient"

    return intent


def _memo(
    *,
    short: str,
    seen: list[str],
    counts: list[str],
    quotes: list[str],
    assume: list[str],
    limits: list[str],
) -> str:
    def bullets(items: list[str], empty: str) -> list[str]:
        if not items:
            return [f"• {empty}"]
        return [f"• {x}" for x in items]

    parts = [
        "Короткий вывод",
        short.strip(),
        "",
        "Что видно в данных",
        *bullets(seen, "По выбранному срезу отдельных наблюдений мало."),
        "",
        "Сколько человек",
        *bullets(counts, "Численность среза не рассчитана."),
        "",
        "Характерные ответы",
        *bullets(quotes, "Подходящих цитат в выборке нет."),
        "",
        "Что можно предположить",
        *bullets(assume, "Дополнительных предположений нет."),
        "",
        "Ограничения",
        *bullets(limits, "Ограничения не указаны."),
    ]
    return "\n".join(parts)


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
    latest_disp = stats.format_msk(latest)

    base = {
        "ok": True,
        "mode": "llm" if llm_available() else "deterministic",
        "llm_available": llm_available(),
        "dataset": dataset,
        "dataset_label": ds_label,
        "total_responses": total,
        "intent": intent,
        "source": "CASTDEV09.26 database",
        "capability_note": None,
        "disclaimer": (
            "Источник истины — база CASTDEV09.26. "
            "Предположения отделены от фактов. "
            "Общие знания о рынке труда не подменяют данные исследования."
        ),
    }

    default_limits = [
        "Выводы опираются только на заполненные анкеты CASTDEV09.26, не на рынок в целом.",
        "Классификация смысловая (правила), не замена ручному чтению всех формулировок.",
        "RAW-ответы не изменялись; признаки пересчитываются из RAW.",
    ]

    if total == 0:
        text = _memo(
            short="В выбранном наборе пока нет анкет — анализировать нечего.",
            seen=[f"Набор «{ds_label}» пуст."],
            counts=["0 анкет."],
            quotes=[],
            assume=[],
            limits=["Недостаточно данных; ответ не выдуман."] + default_limits,
        )
        base["answer_text"] = text
        base["facts"] = []
        base["observations"] = []
        return base

    if intent["kind"] == "insufficient":
        text = _memo(
            short="По этой теме в базе CASTDEV09.26 данных нет.",
            seen=[
                f"Вопрос не соотносится с содержанием анкет (вопросы 1–4).",
                f"В выборке {total} анкет, но релевантных ответов по теме — 0.",
            ],
            counts=[f"Релевантных: 0 из {total} — 0%."],
            quotes=[],
            assume=[],
            limits=["Недостаточно данных — ответ не выдуман."] + default_limits,
        )
        base["answer_text"] = text
        base["facts"] = [stats.pct(0, total) | {"label": "релевантных ответов"}]
        return base

    facts: list[dict[str, Any]] = [{"label": "всего анкет", **stats.pct(total, total)}]
    observations: list[str] = []
    quotes: list[dict[str, Any]] = []
    seen_lines: list[str] = []
    count_lines: list[str] = [f"Всего анкет в наборе «{ds_label}»: {total}."]
    if latest_disp:
        count_lines.append(f"Последний ответ: {latest_disp}.")
    assume_lines: list[str] = []
    limit_lines = list(default_limits)
    short = ""

    if intent.get("needs_open_llm") and not llm_available():
        limit_lines.insert(
            0,
            "Свободная формулировка вне данных исследования требует подключения языковой модели; "
            "ниже — только то, что можно сказать по правилам и базе CASTDEV09.26.",
        )

    if intent["kind"] in ("overview", "quantitative", "focused"):
        from . import cabinet as cabinet_mod

        themes = cabinet_mod.theme_summaries(conn, dataset)
        p7 = stats.period_count(conn, dataset, days=7)
        count_lines.append(
            f"За 7 дней: {p7['numerator']} из {p7['denominator']} — {p7['percentage']}%."
        )
        facts.append(
            {
                "label": "за 7 дней",
                **{k: p7[k] for k in ("numerator", "denominator", "percentage", "display")},
            }
        )

        focus_qs = intent["questions"] if intent["kind"] == "focused" else ["q1", "q2", "q3", "q4"]
        top_bits = []
        for qn in focus_qs:
            block = themes.get(qn) or {}
            for th in (block.get("themes") or [])[:3]:
                line = (
                    f"{block.get('title', qn)} — «{th['label']}»: "
                    f"{th['count']} из {total} — {th['share']['percentage']}%"
                )
                seen_lines.append(line)
                top_bits.append(th["label"])
                facts.append(
                    {
                        "label": th["label"],
                        "numerator": th["share"]["numerator"],
                        "denominator": th["share"]["denominator"],
                        "percentage": th["share"]["percentage"],
                        "display": th["display"],
                    }
                )
                for src in th["sources"][:2]:
                    quotes.append(
                        {
                            "response_id": src["response_id"],
                            "question": qn,
                            "quote": (src["text"] or "")[:400],
                        }
                    )
        if intent["kind"] == "focused":
            short = (
                f"По выбранным вопросам ({', '.join(labels_ru.QUESTION_TITLES[q] for q in focus_qs)}) "
                f"в {total} анкетах выделяются темы: "
                + (", ".join(top_bits[:5]) if top_bits else "пока без устойчивых признаков")
                + "."
            )
        else:
            short = (
                f"В наборе {total} анкет. Ниже — наиболее частые смысловые темы по вопросам 1–4 "
                "и доли (N из D)."
            )
        assume_lines.append(
            "Частые темы отражают повторяющиеся формулировки в этой выборке, "
            "а не «мнение рынка»."
        )
        observations.append(
            "Категории — semantic_rules_v1: позиция к каналу, критерии, трение, намерение."
        )

    if intent["kind"] == "channel_stance" or intent.get("channel"):
        ch = intent.get("channel") or "hh"
        ch_ru = labels_ru.CHANNEL_LABELS.get(ch, ch)
        opp = stats.opposing_stances(conn, ch, dataset)
        seen_lines.append(
            f"Отношение к «{ch_ru}» разделено по смыслу (не по простому упоминанию слова)."
        )
        for stance in (
            "positive_use",
            "negative_while_using",
            "abandoned",
            "mentioned_neutral",
        ):
            block = opp[stance]
            label = labels_ru.stance_ru(stance)
            count_lines.append(
                f"{label}: {block['numerator']} из {block['denominator']} — {block['percentage']}%."
            )
            facts.append(
                {
                    "label": f"{ch_ru}: {label}",
                    **{
                        k: block[k]
                        for k in ("numerator", "denominator", "percentage", "display")
                    },
                }
            )
        short = (
            f"К каналу «{ch_ru}» в выборке есть и позитивные, и негативные, и отказные позиции — "
            "их нельзя смешивать в одну «упоминаемость»."
        )
        assume_lines.append(
            "Если негатив и отказ заметны, канал может сохраняться «формально», "
            "но не восприниматься как рабочий — это гипотеза, не факт опроса."
        )
        observations.append(opp["note"])
        for r in responses:
            t = r["q1"]
            if ch == "hh" and re.search(r"hh|хх|head", t, re.I):
                quotes.append(
                    {"response_id": r["response_id"], "question": "q1", "quote": t[:400]}
                )
            elif ch != "hh" and (ch_ru.lower() in t.lower() or ch in t.lower()):
                quotes.append(
                    {"response_id": r["response_id"], "question": "q1", "quote": t[:400]}
                )
            if len(quotes) >= 6:
                break

    if intent["kind"] == "trend" or intent["want_trend"]:
        dyn = stats.inflow_dynamics(conn, dataset)
        short = f"Поступления шли в {len(dyn)} календарных днях (по дате записи)."
        for d in dyn[-14:]:
            seen_lines.append(f"{d['date']}: {d['count']} анкет")
        facts.append(
            {"label": "дней с поступлениями", **stats.pct(len(dyn), len(dyn) or 1)}
        )
        assume_lines.append(
            "Динамика — поток заполнений, не оценка качества ответов."
        )

    if intent["kind"] == "contradiction" or intent["want_contradiction"]:
        classes = db.fetch_classifications(conn, dataset)
        contras = [c for c in classes if c["feature_key"] == "contradiction"]
        n = len({c["response_id"] for c in contras})
        block = stats.pct(n, total)
        short = (
            f"Межвопросные противоречия (эвристика): {block['display']}"
        )
        count_lines.append(f"Анкета с меткой противоречия: {block['display']}")
        facts.append({"label": "contradiction", **block})
        seen_lines.append(
            "Метка ставится методикой (например, позитив к каналу в вопросе 1 и отказ в вопросе 4), "
            "это не прямой ответ респондента."
        )
        for c in contras[:4]:
            observations.append(
                labels_ru.feature_value_ru(c["feature_key"], c["feature_value"])
            )
        assume_lines.append(
            "Противоречие может отражать смену подхода со временем или разные акценты в ответах."
        )
        limit_lines.append("Метка противоречия — аналитическая, не цитата респондента.")

    if intent["kind"] == "cross" or intent["want_cross"]:
        from . import cabinet as cabinet_mod

        cross = cabinet_mod.cross_questionnaire(conn, dataset, limit=8)
        short = (
            "Ниже — частые сочетания признаков у одних и тех же анонимных анкет (вопросы 1–4 вместе)."
        )
        for link in cross["links"][:6]:
            seen_lines.append(
                f"«{link['a']['title']}: {link['a']['label']}» вместе с "
                f"«{link['b']['title']}: {link['b']['label']}» — {link['display']}"
            )
            for src in link["sources"][:1]:
                quotes.append(
                    {
                        "response_id": src["response_id"],
                        "question": "q1",
                        "quote": (src.get("q1") or "")[:400],
                    }
                )
        assume_lines.append(cross["note"])

    if intent["want_quotes"] or intent["kind"] == "focused":
        for qn in intent["questions"]:
            quotes.extend(_citations(responses, qn, limit=3))

    # Dedup quotes
    seen_q = set()
    uniq_quotes = []
    for q in quotes:
        key = (q.get("response_id"), q.get("question"), q.get("quote"))
        if key in seen_q:
            continue
        seen_q.add(key)
        uniq_quotes.append(q)
    quotes = uniq_quotes[:10]

    quote_lines = []
    for q in quotes:
        title = labels_ru.QUESTION_TITLES.get(q["question"], q["question"])
        quote_lines.append(f"[{title}] «{q['quote']}»")

    if not short:
        short = f"В наборе {total} анкет. Уточните вопрос для более узкого среза."

    if not seen_lines:
        seen_lines.append(f"В наборе «{ds_label}» {total} анкет CASTDEV09.26.")

    answer_text = _memo(
        short=short,
        seen=seen_lines,
        counts=count_lines,
        quotes=quote_lines,
        assume=assume_lines or ["Дополнительных предположений по этому вопросу нет."],
        limits=limit_lines,
    )

    result = {
        **base,
        "answer_text": answer_text,
        "facts": facts,
        "observations": observations,
        "quotes": quotes,
        "classification_note": classify.explain_not_keyword_only(),
        "capability_note": None,
    }

    if llm_available():
        try:
            enriched = _llm_enrich(question, result, responses[:40])
            if enriched:
                result["answer_text"] = enriched
                result["mode"] = "llm"
        except Exception as exc:  # noqa: BLE001
            result["llm_error"] = str(exc)
            result["mode"] = "deterministic_fallback"

    return result


def _llm_enrich(question: str, structured: dict, sample: list[dict]) -> str | None:
    payload = {
        "model": config.LLM_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Ты аналитик CASTDEV09.26. Пиши аналитическую записку на русском со структурой: "
                    "Короткий вывод; Что видно в данных; Сколько человек; Характерные ответы; "
                    "Что можно предположить; Ограничения. "
                    "Факты с «N из D — %». Не выдавай гипотезу за факт. Не упоминай API, ключи, Cursor."
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
