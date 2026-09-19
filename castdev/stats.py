"""Statistics engine: always returns numerator + denominator + percentage."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from . import db
from .db import Dataset


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


def summary(conn, dataset: Dataset = "production") -> dict[str, Any]:
    return {
        "total": total_count(conn, dataset),
        "latest": db.latest_created_at(conn, dataset),
        "period_7d": period_count(conn, dataset, days=7),
        "dynamics": inflow_dynamics(conn, dataset),
        "features": feature_stats(conn, dataset),
        "hh_stances": opposing_stances(conn, "hh", dataset),
    }
