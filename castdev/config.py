"""Server-side configuration. Secrets never ship in frontend."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("CASTDEV_DATA_DIR", ROOT / "data")).resolve()
BACKUP_DIR = Path(os.environ.get("CASTDEV_BACKUP_DIR", ROOT / "backups")).resolve()

DB_PATH = Path(os.environ.get("CASTDEV_DB_PATH", DATA_DIR / "castdev0926.sqlite")).resolve()
TEST_DB_PATH = Path(
    os.environ.get("CASTDEV_TEST_DB_PATH", DATA_DIR / "castdev0926_test.sqlite")
).resolve()

# Activation token for Tatiana's browser (one-time / rotatable). Override via env in prod.
ADMIN_ACTIVATION_TOKEN = os.environ.get(
    "CASTDEV_ADMIN_ACTIVATION_TOKEN",
    "castdev-tatiana-activate-CHANGE-ME-IN-PRODUCTION",
)
ADMIN_SESSION_SECRET = os.environ.get(
    "CASTDEV_ADMIN_SESSION_SECRET",
    secrets.token_hex(32),
)
ADMIN_SESSION_HOURS = int(os.environ.get("CASTDEV_ADMIN_SESSION_HOURS", "720"))  # 30 days
ADMIN_COOKIE_NAME = "castdev_admin_session"
ADMIN_CSRF_COOKIE = "castdev_admin_csrf"

MAX_ANSWER_LEN = int(os.environ.get("CASTDEV_MAX_ANSWER_LEN", "8000"))
MIN_ANSWER_LEN = 1

# Soft flood: same payload hash within window → reject as duplicate (no respondent ID).
SUBMIT_DEDUP_SECONDS = int(os.environ.get("CASTDEV_SUBMIT_DEDUP_SECONDS", "30"))
# Bucketed rate limit without storing IP in research DB (in-memory only).
FLOOD_WINDOW_SECONDS = int(os.environ.get("CASTDEV_FLOOD_WINDOW_SECONDS", "60"))
FLOOD_MAX_PER_WINDOW = int(os.environ.get("CASTDEV_FLOOD_MAX_PER_WINDOW", "12"))

# Optional LLM for free-form analyst answers. If missing — deterministic engine + snapshot path.
LLM_API_KEY = os.environ.get("CASTDEV_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
LLM_API_BASE = os.environ.get("CASTDEV_LLM_API_BASE", "https://api.openai.com/v1")
LLM_MODEL = os.environ.get("CASTDEV_LLM_MODEL", "gpt-4o-mini")

HOST = os.environ.get("CASTDEV_HOST", "127.0.0.1")
PORT = int(os.environ.get("CASTDEV_PORT", "8092"))
DEBUG = os.environ.get("CASTDEV_DEBUG", "").lower() in ("1", "true", "yes")

STATIC_ROOT = ROOT  # index.html + assets/ live at repo root for public survey
ADMIN_STATIC = Path(__file__).resolve().parent / "static"
ADMIN_TEMPLATES = Path(__file__).resolve().parent / "templates"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    # Restrictive defaults for local data dir
    try:
        os.chmod(DATA_DIR, 0o700)
    except OSError:
        pass
