#!/usr/bin/env bash
# Restore onto a TEST COPY only — never overwrite production in place from this script
# without explicit DEST path confirmation.
set -euo pipefail
SRC="${1:?Usage: restore_db.sh <backup.sqlite> <dest.sqlite>}"
DEST="${2:?Usage: restore_db.sh <backup.sqlite> <dest.sqlite>}"
if [[ "$DEST" == *"castdev0926.sqlite" && "${ALLOW_PROD_RESTORE:-}" != "1" ]]; then
  echo "Refusing to restore over production DB. Set ALLOW_PROD_RESTORE=1 to override." >&2
  exit 2
fi
mkdir -p "$(dirname "$DEST")"
sqlite3 "$SRC" ".backup '$DEST'"
chmod 600 "$DEST" || true
echo "RESTORE_OK $DEST"
