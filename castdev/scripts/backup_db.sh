#!/usr/bin/env bash
# Backup CASTDEV09.26 SQLite databases (safe copy).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DATA="${CASTDEV_DATA_DIR:-$ROOT/data}"
BACKUP_ROOT="${CASTDEV_BACKUP_DIR:-$ROOT/backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="$BACKUP_ROOT/$STAMP"
mkdir -p "$DEST"
for f in castdev0926.sqlite castdev0926_test.sqlite; do
  if [[ -f "$DATA/$f" ]]; then
    sqlite3 "$DATA/$f" ".backup '$DEST/$f'"
    chmod 600 "$DEST/$f" || true
    echo "backed up $f -> $DEST/$f"
  fi
done
# Also copy WAL/SHM if present (after .backup they are consolidated)
echo "BACKUP_OK $DEST"
