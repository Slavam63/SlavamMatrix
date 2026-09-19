"""Research cabinet aggregates for Tatiana — themes, dynamic columns, cross-links."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from . import db, labels_ru, stats
from .db import Dataset


def _feature_col_key(feature_key: str, feature_value: str) -> str:
    return f"{feature_key}::{feature_value}"


def _dynamic_columns(
    classes: list[dict[str, Any]], *, question: str | None = None
) -> list[dict[str, str]]:
    """Build analytical columns from features actually present in data."""
    seen: dict[str, dict[str, str]] = {}
    for c in classes:
        if question and c["question"] != question and not (
            question == "all" and c["question"] in ("q1", "q2", "q3", "q4", "cross")
        ):
            if question != "all":
                continue
        qn = c["question"]
        if question and question != "all" and qn != question:
            continue
        if qn not in ("q1", "q2", "q3", "q4", "cross"):
            continue
        key = _feature_col_key(c["feature_key"], c["feature_value"])
        if key in seen:
            continue
        label = labels_ru.feature_value_ru(c["feature_key"], c["feature_value"])
        # Prefix with question short code when showing all
        if question == "all" or question is None:
            qtitle = labels_ru.QUESTION_TITLES.get(qn, qn)
            label = f"{qtitle}: {label}"
        seen[key] = {
            "key": key,
            "feature_key": c["feature_key"],
            "feature_value": c["feature_value"],
            "question": qn,
            "label": label,
        }
    # Stable order: by question then label
    order = {"q1": 0, "q2": 1, "q3": 2, "q4": 3, "cross": 4}
    return sorted(
        seen.values(),
        key=lambda x: (order.get(x["question"], 9), x["label"]),
    )


def theme_summaries(
    conn, dataset: Dataset = "production"
) -> dict[str, Any]:
    """Per-question themes with counts, shares, and confirming RAW answers."""
    total = stats.total_count(conn, dataset)
    responses = {r["response_id"]: r for r in db.fetch_all_responses(conn, dataset)}
    classes = db.fetch_classifications(conn, dataset)

    buckets: dict[str, dict[tuple[str, str], set[str]]] = {
        "q1": defaultdict(set),
        "q2": defaultdict(set),
        "q3": defaultdict(set),
        "q4": defaultdict(set),
    }
    for c in classes:
        qn = c["question"]
        if qn not in buckets:
            continue
        buckets[qn][(c["feature_key"], c["feature_value"])].add(c["response_id"])

    out: dict[str, Any] = {}
    for qn in ("q1", "q2", "q3", "q4"):
        themes = []
        for (fkey, fval), ids in sorted(
            buckets[qn].items(), key=lambda x: (-len(x[1]), x[0])
        ):
            sources = []
            for rid in sorted(ids):
                r = responses.get(rid)
                if not r:
                    continue
                sources.append(
                    {
                        "response_id": rid,
                        "created_at_display": stats.format_msk(r["created_at"]),
                        "text": r[qn],
                    }
                )
            block = stats.pct(len(ids), total)
            themes.append(
                {
                    "feature_key": fkey,
                    "feature_value": fval,
                    "label": labels_ru.feature_value_ru(fkey, fval),
                    "count": len(ids),
                    "share": block,
                    "display": block["display"],
                    "response_ids": sorted(ids),
                    "sources": sources,
                }
            )
        out[qn] = {
            "question": qn,
            "title": labels_ru.QUESTION_TITLES[qn],
            "prompt": labels_ru.QUESTION_PROMPTS_SHORT[qn],
            "themes": themes,
            "total": total,
        }
    return out


def answers_table(
    conn, dataset: Dataset = "production", *, question: str = "all"
) -> dict[str, Any]:
    """
    Answers + dynamic feature columns (✓ / empty), multi-label.
    question: all | q1 | q2 | q3 | q4
    """
    if question not in ("all", "q1", "q2", "q3", "q4"):
        question = "all"
    responses = db.fetch_all_responses(conn, dataset)
    classes = db.fetch_classifications(conn, dataset)
    by_rid: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in classes:
        by_rid[c["response_id"]].append(c)

    # Dynamic columns from data (scoped)
    if question == "all":
        columns = _dynamic_columns(classes, question="all")
    else:
        columns = _dynamic_columns(
            [c for c in classes if c["question"] == question], question=question
        )

    rows: list[dict[str, Any]] = []
    # Newest first; number by reverse chrono then renumber 1..n for display
    ordered = sorted(responses, key=lambda r: r["created_at"] or "", reverse=True)

    if question == "all":
        for i, r in enumerate(ordered, start=1):
            feats = by_rid.get(r["response_id"], [])
            present = {
                _feature_col_key(f["feature_key"], f["feature_value"]) for f in feats
            }
            cells = {col["key"]: (col["key"] in present) for col in columns}
            tags = [
                labels_ru.feature_value_ru(f["feature_key"], f["feature_value"])
                for f in feats
                if f["question"] in ("q1", "q2", "q3", "q4", "cross")
            ]
            rows.append(
                {
                    "num": i,
                    "response_id": r["response_id"],
                    "created_at": r["created_at"],
                    "created_at_display": stats.format_msk(r["created_at"]),
                    "question_filter": "all",
                    "answer_text": None,
                    "answers": {
                        "q1": r["q1"],
                        "q2": r["q2"],
                        "q3": r["q3"],
                        "q4": r["q4"],
                    },
                    "cells": cells,
                    "feature_tags": tags,
                }
            )
    else:
        for i, r in enumerate(ordered, start=1):
            feats = [
                f for f in by_rid.get(r["response_id"], []) if f["question"] == question
            ]
            present = {
                _feature_col_key(f["feature_key"], f["feature_value"]) for f in feats
            }
            cells = {col["key"]: (col["key"] in present) for col in columns}
            tags = [
                labels_ru.feature_value_ru(f["feature_key"], f["feature_value"])
                for f in feats
            ]
            rows.append(
                {
                    "num": i,
                    "response_id": r["response_id"],
                    "created_at": r["created_at"],
                    "created_at_display": stats.format_msk(r["created_at"]),
                    "question_filter": question,
                    "answer_text": r[question],
                    "answers": {question: r[question]},
                    "cells": cells,
                    "feature_tags": tags,
                }
            )

    return {
        "filter": question,
        "columns": columns,
        "rows": rows,
        "total": len(ordered),
    }


def cross_questionnaire(
    conn, dataset: Dataset = "production", *, limit: int = 12
) -> dict[str, Any]:
    """
    Combinations of features across different questions for the same response.
    Unit of analysis = whole anonymous questionnaire.
    """
    total = stats.total_count(conn, dataset)
    responses = {r["response_id"]: r for r in db.fetch_all_responses(conn, dataset)}
    classes = db.fetch_classifications(conn, dataset)
    by_rid: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in classes:
        if c["question"] in ("q1", "q2", "q3", "q4"):
            by_rid[c["response_id"]].append(c)

    pair_counter: Counter[tuple[str, str, str, str, str, str]] = Counter()
    pair_ids: dict[tuple[str, str, str, str, str, str], set[str]] = defaultdict(set)

    for rid, feats in by_rid.items():
        # unique features per response
        uniq = []
        seen = set()
        for f in feats:
            key = (f["question"], f["feature_key"], f["feature_value"])
            if key in seen:
                continue
            seen.add(key)
            uniq.append(f)
        for i in range(len(uniq)):
            for j in range(i + 1, len(uniq)):
                a, b = uniq[i], uniq[j]
                if a["question"] == b["question"]:
                    continue
                # order by question number
                if a["question"] > b["question"]:
                    a, b = b, a
                tup = (
                    a["question"],
                    a["feature_key"],
                    a["feature_value"],
                    b["question"],
                    b["feature_key"],
                    b["feature_value"],
                )
                pair_counter[tup] += 1
                pair_ids[tup].add(rid)

    links = []
    for tup, n in pair_counter.most_common(limit):
        q_a, fk_a, fv_a, q_b, fk_b, fv_b = tup
        ids = pair_ids[tup]
        block = stats.pct(len(ids), total)
        sources = []
        for rid in sorted(ids)[:5]:
            r = responses.get(rid)
            if not r:
                continue
            sources.append(
                {
                    "response_id": rid,
                    "created_at_display": stats.format_msk(r["created_at"]),
                    "q1": r["q1"],
                    "q2": r["q2"],
                    "q3": r["q3"],
                    "q4": r["q4"],
                }
            )
        links.append(
            {
                "a": {
                    "question": q_a,
                    "title": labels_ru.QUESTION_TITLES[q_a],
                    "label": labels_ru.feature_value_ru(fk_a, fv_a),
                    "feature_key": fk_a,
                    "feature_value": fv_a,
                },
                "b": {
                    "question": q_b,
                    "title": labels_ru.QUESTION_TITLES[q_b],
                    "label": labels_ru.feature_value_ru(fk_b, fv_b),
                    "feature_key": fk_b,
                    "feature_value": fv_b,
                },
                "count": len(ids),
                "share": block,
                "display": block["display"],
                "response_ids": sorted(ids),
                "sources": sources,
            }
        )

    # Explicit contradiction features
    contras = [c for c in classes if c["feature_key"] == "contradiction"]
    contradiction = {
        "count": len({c["response_id"] for c in contras}),
        "total": total,
        "display": stats.pct(len({c["response_id"] for c in contras}), total)["display"],
        "items": [
            {
                "response_id": c["response_id"],
                "label": labels_ru.feature_value_ru(c["feature_key"], c["feature_value"]),
            }
            for c in contras
        ],
    }

    return {
        "total": total,
        "links": links,
        "contradiction": contradiction,
        "note": (
            "Единица анализа — целая анонимная анкета (ответы на вопросы 1–4 вместе). "
            "Сочетания показывают, какие признаки встречаются у одних и тех же людей."
        ),
    }


def build_cabinet(conn, dataset: Dataset = "production") -> dict[str, Any]:
    latest = db.latest_created_at(conn, dataset)
    total = stats.total_count(conn, dataset)
    return {
        "ok": True,
        "total": total,
        "latest": latest,
        "latest_display": stats.format_msk(latest),
        "dataset": dataset,
        "dataset_label": labels_ru.DATASET_LABELS.get(dataset, dataset),
        "question_titles": dict(labels_ru.QUESTION_TITLES),
        "themes": theme_summaries(conn, dataset),
        "answers_all": answers_table(conn, dataset, question="all"),
        "answers_by_question": {
            qn: answers_table(conn, dataset, question=qn)
            for qn in ("q1", "q2", "q3", "q4")
        },
        "cross": cross_questionnaire(conn, dataset),
        "hh_stances": stats.opposing_stances(conn, "hh", dataset),
        "period_7d": stats.period_count(conn, dataset, days=7),
    }


def export_payload(
    conn, dataset: Dataset = "production", *, fmt: str = "json"
) -> dict[str, Any]:
    """Protected analyst export — RAW + derived, no Cursor/LLM integration chatter."""
    cabinet = build_cabinet(conn, dataset)
    snap = db.export_snapshot(conn, dataset)
    return {
        "ok": True,
        "format": fmt,
        "exported_at": snap["exported_at"],
        "total": snap["total"],
        "source_label": labels_ru.DATASET_LABELS.get(dataset, dataset),
        "responses": snap["responses"],
        "classifications": snap["classifications"],
        "themes": cabinet["themes"],
        "cross": cabinet["cross"],
    }


def export_csv_text(conn, dataset: Dataset = "production") -> str:
    """Flat CSV of RAW answers + feature tags (UTF-8 with BOM-friendly)."""
    import csv
    import io

    responses = db.fetch_all_responses(conn, dataset)
    classes = db.fetch_classifications(conn, dataset)
    by_rid: dict[str, list[str]] = defaultdict(list)
    for c in classes:
        by_rid[c["response_id"]].append(
            f"{c['question']}:{labels_ru.feature_value_ru(c['feature_key'], c['feature_value'])}"
        )
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "num",
            "response_id",
            "created_at",
            "created_at_msk",
            "q1",
            "q2",
            "q3",
            "q4",
            "features",
        ]
    )
    ordered = sorted(responses, key=lambda r: r["created_at"] or "", reverse=True)
    for i, r in enumerate(ordered, start=1):
        w.writerow(
            [
                i,
                r["response_id"],
                r["created_at"],
                stats.format_msk(r["created_at"]) or "",
                r["q1"],
                r["q2"],
                r["q3"],
                r["q4"],
                " | ".join(by_rid.get(r["response_id"], [])),
            ]
        )
    return buf.getvalue()
