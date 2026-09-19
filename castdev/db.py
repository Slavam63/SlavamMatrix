"""SQLite persistence: RAW responses + ANALYTICAL classifications. Separate test DB."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Literal

from . import config

Dataset = Literal["production", "test"]


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS responses (
  response_id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  q1 TEXT NOT NULL,
  q2 TEXT NOT NULL,
  q3 TEXT NOT NULL,
  q4 TEXT NOT NULL,
  dataset TEXT NOT NULL DEFAULT 'production',
  content_hash TEXT NOT NULL,
  client_submit_token TEXT
);

CREATE INDEX IF NOT EXISTS idx_responses_created ON responses(created_at);
CREATE INDEX IF NOT EXISTS idx_responses_dataset ON responses(dataset);
CREATE INDEX IF NOT EXISTS idx_responses_hash ON responses(content_hash);

-- ANALYTICAL layer: derived, recalculable; never replaces RAW.
CREATE TABLE IF NOT EXISTS classifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  response_id TEXT NOT NULL REFERENCES responses(response_id) ON DELETE CASCADE,
  question TEXT NOT NULL,
  feature_key TEXT NOT NULL,
  feature_value TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 1.0,
  method TEXT NOT NULL DEFAULT 'semantic_rules_v1',
  UNIQUE(response_id, question, feature_key, feature_value)
);

CREATE INDEX IF NOT EXISTS idx_class_feature ON classifications(feature_key, feature_value);
CREATE INDEX IF NOT EXISTS idx_class_response ON classifications(response_id);

CREATE TABLE IF NOT EXISTS admin_sessions (
  session_id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  revoked INTEGER NOT NULL DEFAULT 0,
  label TEXT NOT NULL DEFAULT 'tatiana'
);

CREATE TABLE IF NOT EXISTS admin_activation_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  ok INTEGER NOT NULL,
  note TEXT
);

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

-- Minimal Analyst API audit (no token, no full raw answers, no question text).
CREATE TABLE IF NOT EXISTS analyst_audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  op_type TEXT NOT NULL,
  endpoint TEXT NOT NULL,
  success INTEGER NOT NULL,
  note TEXT
);

CREATE INDEX IF NOT EXISTS idx_analyst_audit_created ON analyst_audit_log(created_at);
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def db_path_for(dataset: Dataset | None = None) -> Path:
    """Production and test use separate files so TEST can be wiped safely."""
    if dataset == "test":
        return config.TEST_DB_PATH
    return config.DB_PATH


def connect(path: Path | None = None) -> sqlite3.Connection:
    config.ensure_dirs()
    p = path or config.DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(path: Path | None = None) -> Path:
    p = path or config.DB_PATH
    with connect(p) as conn:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES (?, ?)",
            ("schema_version", "1"),
        )
    try:
        os_chmod = __import__("os").chmod
        os_chmod(p, 0o600)
    except OSError:
        pass
    return p


def init_all() -> dict[str, str]:
    prod = init_db(config.DB_PATH)
    test = init_db(config.TEST_DB_PATH)
    return {"production": str(prod), "test": str(test)}


@contextmanager
def session(dataset: Dataset = "production") -> Iterator[sqlite3.Connection]:
    conn = connect(db_path_for(dataset))
    try:
        yield conn
    finally:
        conn.close()


def insert_response(
    conn: sqlite3.Connection,
    *,
    q1: str,
    q2: str,
    q3: str,
    q4: str,
    dataset: Dataset,
    content_hash: str,
    client_submit_token: str | None,
    classifications: list[dict[str, Any]],
) -> str:
    response_id = str(uuid.uuid4())
    created_at = _utc_now()
    conn.execute("BEGIN IMMEDIATE")
    try:
        # Soft dedup: identical payload within window
        row = conn.execute(
            """
            SELECT response_id, created_at FROM responses
            WHERE content_hash = ? AND dataset = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (content_hash, dataset),
        ).fetchone()
        if row:
            from datetime import datetime as dt

            try:
                prev = dt.fromisoformat(row["created_at"])
                now = dt.fromisoformat(created_at)
                if (now - prev).total_seconds() < config.SUBMIT_DEDUP_SECONDS:
                    conn.execute("ROLLBACK")
                    return row["response_id"]  # treat as success, same id
            except ValueError:
                pass

        if client_submit_token:
            dup = conn.execute(
                """
                SELECT response_id FROM responses
                WHERE client_submit_token = ? AND dataset = ?
                LIMIT 1
                """,
                (client_submit_token, dataset),
            ).fetchone()
            if dup:
                conn.execute("ROLLBACK")
                return dup["response_id"]

        conn.execute(
            """
            INSERT INTO responses(
              response_id, created_at, q1, q2, q3, q4,
              dataset, content_hash, client_submit_token
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                response_id,
                created_at,
                q1,
                q2,
                q3,
                q4,
                dataset,
                content_hash,
                client_submit_token,
            ),
        )
        for c in classifications:
            conn.execute(
                """
                INSERT OR IGNORE INTO classifications(
                  response_id, question, feature_key, feature_value, confidence, method
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    response_id,
                    c["question"],
                    c["feature_key"],
                    c["feature_value"],
                    c.get("confidence", 1.0),
                    c.get("method", "semantic_rules_v1"),
                ),
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return response_id


def count_responses(conn: sqlite3.Connection, dataset: Dataset = "production") -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM responses WHERE dataset = ?", (dataset,)
    ).fetchone()
    return int(row["n"])


def latest_created_at(conn: sqlite3.Connection, dataset: Dataset = "production") -> str | None:
    row = conn.execute(
        """
        SELECT created_at FROM responses WHERE dataset = ?
        ORDER BY created_at DESC LIMIT 1
        """,
        (dataset,),
    ).fetchone()
    return row["created_at"] if row else None


def fetch_all_responses(
    conn: sqlite3.Connection, dataset: Dataset = "production"
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT response_id, created_at, q1, q2, q3, q4
        FROM responses WHERE dataset = ?
        ORDER BY created_at ASC
        """,
        (dataset,),
    ).fetchall()
    return [dict(r) for r in rows]


def fetch_responses_page(
    conn: sqlite3.Connection,
    dataset: Dataset = "production",
    *,
    limit: int = 50,
    offset: int = 0,
    since: str | None = None,
    until: str | None = None,
    ids: list[str] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Anonymous RAW page: survey_id (=response_id), q1–q4, submitted_at. No PII."""
    clauses = ["dataset = ?"]
    params: list[Any] = [dataset]
    if since:
        clauses.append("created_at >= ?")
        params.append(since)
    if until:
        clauses.append("created_at <= ?")
        params.append(until)
    if ids:
        placeholders = ",".join("?" for _ in ids)
        clauses.append(f"response_id IN ({placeholders})")
        params.extend(ids)
    where = " AND ".join(clauses)
    total_row = conn.execute(
        f"SELECT COUNT(*) AS n FROM responses WHERE {where}", params
    ).fetchone()
    total = int(total_row["n"])
    rows = conn.execute(
        f"""
        SELECT response_id, created_at, q1, q2, q3, q4
        FROM responses WHERE {where}
        ORDER BY created_at ASC
        LIMIT ? OFFSET ?
        """,
        [*params, limit, offset],
    ).fetchall()
    items = [
        {
            "survey_id": r["response_id"],
            "response_id": r["response_id"],
            "submitted_at": r["created_at"],
            "q1": r["q1"],
            "q2": r["q2"],
            "q3": r["q3"],
            "q4": r["q4"],
        }
        for r in rows
    ]
    return items, total


def fetch_classifications(
    conn: sqlite3.Connection, dataset: Dataset = "production"
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT c.response_id, c.question, c.feature_key, c.feature_value,
               c.confidence, c.method
        FROM classifications c
        JOIN responses r ON r.response_id = c.response_id
        WHERE r.dataset = ?
        """,
        (dataset,),
    ).fetchall()
    return [dict(r) for r in rows]


def fetch_classifications_filtered(
    conn: sqlite3.Connection,
    dataset: Dataset = "production",
    *,
    response_id: str | None = None,
    question: str | None = None,
    feature_key: str | None = None,
    feature_value: str | None = None,
) -> list[dict[str, Any]]:
    clauses = ["r.dataset = ?"]
    params: list[Any] = [dataset]
    if response_id:
        clauses.append("c.response_id = ?")
        params.append(response_id)
    if question:
        clauses.append("c.question = ?")
        params.append(question)
    if feature_key:
        clauses.append("c.feature_key = ?")
        params.append(feature_key)
    if feature_value:
        clauses.append("c.feature_value = ?")
        params.append(feature_value)
    where = " AND ".join(clauses)
    rows = conn.execute(
        f"""
        SELECT c.response_id, c.question, c.feature_key, c.feature_value,
               c.confidence, c.method
        FROM classifications c
        JOIN responses r ON r.response_id = c.response_id
        WHERE {where}
        ORDER BY c.response_id, c.question, c.feature_key, c.feature_value
        """,
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def derived_status(conn: sqlite3.Connection, dataset: Dataset = "production") -> dict[str, Any]:
    """Presence of derived layer + method; last classify inferred from latest response."""
    n_class = conn.execute(
        """
        SELECT COUNT(*) AS n FROM classifications c
        JOIN responses r ON r.response_id = c.response_id
        WHERE r.dataset = ?
        """,
        (dataset,),
    ).fetchone()
    method_row = conn.execute(
        """
        SELECT c.method FROM classifications c
        JOIN responses r ON r.response_id = c.response_id
        WHERE r.dataset = ?
        LIMIT 1
        """,
        (dataset,),
    ).fetchone()
    last = latest_created_at(conn, dataset)
    return {
        "derived_present": int(n_class["n"]) > 0,
        "classification_count": int(n_class["n"]),
        "method": method_row["method"] if method_row else None,
        "last_recompute": last,  # classifications written at submit; no separate recompute yet
    }


def meta_get(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def log_analyst_audit(
    conn: sqlite3.Connection,
    *,
    op_type: str,
    endpoint: str,
    success: bool,
    note: str | None = None,
) -> None:
    """Minimal audit — never store token or full answer text."""
    safe_note = (note or "")[:120]
    try:
        conn.execute(
            """
            INSERT INTO analyst_audit_log(created_at, op_type, endpoint, success, note)
            VALUES (?, ?, ?, ?, ?)
            """,
            (_utc_now(), op_type[:64], endpoint[:256], 1 if success else 0, safe_note or None),
        )
    except Exception:
        # Audit must not break API
        pass


def wipe_test_dataset(conn: sqlite3.Connection) -> int:
    """Delete only dataset='test' rows. Never touches production."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        ids = [
            r["response_id"]
            for r in conn.execute(
                "SELECT response_id FROM responses WHERE dataset = 'test'"
            ).fetchall()
        ]
        for rid in ids:
            conn.execute("DELETE FROM classifications WHERE response_id = ?", (rid,))
        conn.execute("DELETE FROM responses WHERE dataset = 'test'")
        conn.execute("COMMIT")
        return len(ids)
    except Exception:
        conn.execute("ROLLBACK")
        raise


def export_snapshot(conn: sqlite3.Connection, dataset: Dataset = "production") -> dict[str, Any]:
    responses = fetch_all_responses(conn, dataset)
    classifications = fetch_classifications(conn, dataset)
    return {
        "exported_at": _utc_now(),
        "dataset": dataset,
        "total": len(responses),
        "responses": responses,
        "classifications": classifications,
    }


def create_admin_session(conn: sqlite3.Connection, hours: int | None = None) -> dict[str, str]:
    hours = hours if hours is not None else config.ADMIN_SESSION_HOURS
    sid = secrets_token()
    created = datetime.now(timezone.utc)
    from datetime import timedelta

    expires = created + timedelta(hours=hours)
    conn.execute(
        """
        INSERT INTO admin_sessions(session_id, created_at, expires_at, revoked, label)
        VALUES (?, ?, ?, 0, 'tatiana')
        """,
        (
            sid,
            created.replace(microsecond=0).isoformat(),
            expires.replace(microsecond=0).isoformat(),
        ),
    )
    return {
        "session_id": sid,
        "created_at": created.replace(microsecond=0).isoformat(),
        "expires_at": expires.replace(microsecond=0).isoformat(),
    }


def secrets_token() -> str:
    import secrets

    return secrets.token_urlsafe(32)


def validate_admin_session(conn: sqlite3.Connection, session_id: str | None) -> bool:
    if not session_id:
        return False
    row = conn.execute(
        """
        SELECT revoked, expires_at FROM admin_sessions WHERE session_id = ?
        """,
        (session_id,),
    ).fetchone()
    if not row or row["revoked"]:
        return False
    try:
        exp = datetime.fromisoformat(row["expires_at"])
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) < exp
    except ValueError:
        return False


def revoke_admin_session(conn: sqlite3.Connection, session_id: str | None) -> bool:
    if not session_id:
        return False
    cur = conn.execute(
        "UPDATE admin_sessions SET revoked = 1 WHERE session_id = ?",
        (session_id,),
    )
    return cur.rowcount > 0


def revoke_all_admin_sessions(conn: sqlite3.Connection) -> int:
    cur = conn.execute("UPDATE admin_sessions SET revoked = 1 WHERE revoked = 0")
    return cur.rowcount
