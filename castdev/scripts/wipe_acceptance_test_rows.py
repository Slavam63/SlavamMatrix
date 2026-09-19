#!/usr/bin/env python3
"""Wipe CASTDEV09.26 acceptance TEST rows marked [TEST-ACCEPTANCE-WIPE].

Safe: deletes ONLY responses where any of q1–q4 contains the marker.
Never deletes unmarked production research answers.

Usage on production (ssh myserver):
  cd /opt/castdev0926
  sudo -u www-data CASTDEV_DATA_DIR=/var/lib/castdev0926 \
    .venv/bin/python -m castdev.scripts.wipe_acceptance_test_rows --apply

Dry-run (default):
  ... wipe_acceptance_test_rows.py
"""

from __future__ import annotations

import argparse
import sys

from castdev import config, db

MARKER = "[TEST-ACCEPTANCE-WIPE]"


def find_marked(conn) -> list[str]:
    rows = conn.execute(
        """
        SELECT response_id FROM responses
        WHERE q1 LIKE ? OR q2 LIKE ? OR q3 LIKE ? OR q4 LIKE ?
        """,
        (f"%{MARKER}%",) * 4,
    ).fetchall()
    return [r["response_id"] if hasattr(r, "keys") else r[0] for r in rows]


def wipe(conn, ids: list[str]) -> int:
    if not ids:
        return 0
    conn.execute("BEGIN IMMEDIATE")
    try:
        for rid in ids:
            conn.execute("DELETE FROM classifications WHERE response_id = ?", (rid,))
            conn.execute("DELETE FROM responses WHERE response_id = ?", (rid,))
        conn.execute("COMMIT")
        return len(ids)
    except Exception:
        conn.execute("ROLLBACK")
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete marked rows (default is dry-run).",
    )
    args = parser.parse_args(argv)

    config.ensure_dirs()
    db.init_db(config.DB_PATH)
    with db.session("production") as conn:
        ids = find_marked(conn)
        print(f"marked_rows={len(ids)} marker={MARKER!r} db={config.DB_PATH}")
        if not ids:
            return 0
        for rid in ids:
            print(f"  {rid}")
        if not args.apply:
            print("dry-run: pass --apply to delete")
            return 0
        n = wipe(conn, ids)
        print(f"deleted={n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
