"""Statistics engine: always returns numerator + denominator + percentage."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from . import db, labels_ru
from .db import Dataset

MSK = ZoneInfo("Europe/Moscow")


def format_msk(iso_ts: str | None) -> str | None:
    """Format stored UTC/ISO timestamp as «DD.MM.YYYY в HH:MM (мск)»."""
    if not iso_ts:
        return None
    raw = iso_ts.strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone(MSK)
        return local.strftime("%d.%m.%Y в %H:%M (мск)")
    except ValueError:
        return iso_ts


def pct(numerator: int, denominator: int) -> dict[str, Any]:
    percentage = round(100.0 * numerator / denominator, 1) if denominator else None
    return {
        "numerator": numerator,
        "denominator": denominator,
        "percentage": percentage,
        "display": (
            f"{numerator} из {denominator} — {percentage}%."
            if denominator
            else f"{numerator} из 0 — н/д."
        ),
    }


def total_count(conn, dataset: Dataset = "production") -> int:
    return db.count_responses(conn, dataset)


def period_count(
    conn, dataset: Dataset = "production", *, days: int | None = None, since: str | None = None
) -> dict[str, Any]:
    rows = db.fetch_all_responses(conn, dataset)
    if since:
        cutoff = since
    elif days is not None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).replace(
            microsecond=0
        ).isoformat()
    else:
        cutoff = None
    if cutoff is None:
        n = len(rows)
    else:
        n = sum(1 for r in rows if r["created_at"] >= cutoff)
    return {
        "count": n,
        "since": cutoff,
        "total_base": len(rows),
        **pct(n, len(rows) if cutoff else n or 1),
    }


def inflow_dynamics(conn, dataset: Dataset = "production") -> list[dict[str, Any]]:
    rows = db.fetch_all_responses(conn, dataset)
    by_day: dict[str, int] = defaultdict(int)
    for r in rows:
        day = r["created_at"][:10]
        by_day[day] += 1
    return [{"date": d, "count": by_day[d]} for d in sorted(by_day)]


def feature_stats(conn, dataset: Dataset = "production") -> dict[str, Any]:
    total = total_count(conn, dataset)
    classes = db.fetch_classifications(conn, dataset)
    # Unique responses per (feature_key, feature_value)
    buckets: dict[tuple[str, str], set[str]] = defaultdict(set)
    for c in classes:
        buckets[(c["feature_key"], c["feature_value"])].add(c["response_id"])

    items = []
    for (fkey, fval), ids in sorted(buckets.items(), key=lambda x: (-len(x[1]), x[0])):
        items.append(
            {
                "feature_key": fkey,
                "feature_value": fval,
                "response_ids": sorted(ids),
                **pct(len(ids), total),
            }
        )
    return {"total": total, "features": items}


def category_share(
    conn,
    *,
    feature_key: str,
    feature_value: str,
    dataset: Dataset = "production",
) -> dict[str, Any]:
    total = total_count(conn, dataset)
    classes = db.fetch_classifications(conn, dataset)
    ids = {
        c["response_id"]
        for c in classes
        if c["feature_key"] == feature_key and c["feature_value"] == feature_value
    }
    return {
        "feature_key": feature_key,
        "feature_value": feature_value,
        **pct(len(ids), total),
        "response_ids": sorted(ids),
    }


def intersection(
    conn,
    *,
    a: tuple[str, str],
    b: tuple[str, str],
    dataset: Dataset = "production",
) -> dict[str, Any]:
    total = total_count(conn, dataset)
    classes = db.fetch_classifications(conn, dataset)
    set_a = {
        c["response_id"]
        for c in classes
        if c["feature_key"] == a[0] and c["feature_value"] == a[1]
    }
    set_b = {
        c["response_id"]
        for c in classes
        if c["feature_key"] == b[0] and c["feature_value"] == b[1]
    }
    both = set_a & set_b
    return {
        "a": {"feature_key": a[0], "feature_value": a[1], **pct(len(set_a), total)},
        "b": {"feature_key": b[0], "feature_value": b[1], **pct(len(set_b), total)},
        "intersection": pct(len(both), total),
        "response_ids": sorted(both),
    }


def opposing_stances(
    conn, channel: str = "hh", dataset: Dataset = "production"
) -> dict[str, Any]:
    """Opposite attitudes to the same topic (e.g. HH) — never merge into one keyword hit."""
    key = f"channel_stance:{channel}"
    total = total_count(conn, dataset)
    out = {}
    for stance in ("positive_use", "negative_while_using", "abandoned", "mentioned_neutral"):
        out[stance] = category_share(
            conn, feature_key=key, feature_value=stance, dataset=dataset
        )
    out["total_responses"] = total
    out["note"] = (
        f"Упоминания «{channel}» разделены по смысловой позиции; "
        "сумма stance ≠ «сколько раз встретилось слово»."
    )
    return out


def feature_matrix(conn, dataset: Dataset = "production") -> dict[str, Any]:
    """Per-question semantic feature columns with N из D for admin table."""
    total = total_count(conn, dataset)
    classes = db.fetch_classifications(conn, dataset)
    buckets: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for c in classes:
        buckets[(c["question"], c["feature_key"], c["feature_value"])].add(
            c["response_id"]
        )

    out: dict[str, Any] = {}
    for qn, columns in labels_ru.FEATURE_COLUMNS_BY_QUESTION.items():
        col_rows = []
        for fkey, fval, title in columns:
            ids = buckets.get((qn, fkey, fval), set())
            # Also accept same key/value stored under another question code if needed
            if not ids and qn.startswith("q"):
                for (qq, kk, vv), s in buckets.items():
                    if kk == fkey and vv == fval and qq == qn:
                        ids = s
                        break
            col_rows.append(
                {
                    "feature_key": fkey,
                    "feature_value": fval,
                    "title": title,
                    "label_ru": labels_ru.feature_value_ru(fkey, fval),
                    **pct(len(ids), total),
                }
            )
        out[qn] = {
            "question": qn,
            "title": labels_ru.QUESTION_TITLES[qn],
            "prompt": labels_ru.QUESTION_PROMPTS_SHORT[qn],
            "columns": col_rows,
        }
    return out


def responses_overview(conn, dataset: Dataset = "production") -> list[dict[str, Any]]:
    """One row per response: MSK time, feature tags by question, RAW answers."""
    responses = db.fetch_all_responses(conn, dataset)
    classes = db.fetch_classifications(conn, dataset)
    by_rid: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in classes:
        by_rid[c["response_id"]].append(c)

    rows: list[dict[str, Any]] = []
    for r in responses:
        feats = by_rid.get(r["response_id"], [])
        by_q: dict[str, list[dict[str, Any]]] = defaultdict(list)
        tags: list[str] = []
        for f in feats:
            item = {
                "question": f["question"],
                "feature_key": f["feature_key"],
                "feature_value": f["feature_value"],
                "label_ru": labels_ru.feature_value_ru(
                    f["feature_key"], f["feature_value"]
                ),
            }
            by_q[f["question"]].append(item)
            if f["question"] in ("q1", "q2", "q3", "q4", "cross"):
                tags.append(item["label_ru"])
        rows.append(
            {
                "response_id": r["response_id"],
                "created_at": r["created_at"],
                "created_at_display": format_msk(r["created_at"]),
                "q1": r["q1"],
                "q2": r["q2"],
                "q3": r["q3"],
                "q4": r["q4"],
                "features_by_question": {k: by_q[k] for k in sorted(by_q)},
                "feature_tags": tags,
            }
        )
    # Newest first for admin scan
    rows.sort(key=lambda x: x["created_at"] or "", reverse=True)
    return rows


def summary(conn, dataset: Dataset = "production") -> dict[str, Any]:
    latest = db.latest_created_at(conn, dataset)
    return {
        "total": total_count(conn, dataset),
        "latest": latest,
        "latest_display": format_msk(latest),
        "dataset_label": labels_ru.DATASET_LABELS.get(dataset, dataset),
        "period_7d": period_count(conn, dataset, days=7),
        "dynamics": inflow_dynamics(conn, dataset),
        "features": feature_stats(conn, dataset),
        "hh_stances": opposing_stances(conn, "hh", dataset),
        "feature_matrix": feature_matrix(conn, dataset),
        "responses": responses_overview(conn, dataset),
        "question_titles": dict(labels_ru.QUESTION_TITLES),
    }
