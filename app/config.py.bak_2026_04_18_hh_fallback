import os
from dotenv import load_dotenv


load_dotenv()


def _get_list_from_env(name: str, default: str):
    raw_value = os.getenv(name, default)
    return [
        item.strip()
        for item in raw_value.split(",")
        if item.strip()
    ]


class Config:
    APP_NAME = os.getenv("APP_NAME", "matrix-parser")
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")

    DATABASE_URL = os.getenv("DATABASE_URL")
    REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")

    SLOT_STEP_MINUTES = int(os.getenv("SLOT_STEP_MINUTES", "15"))
    SLOT_HORIZON_HOURS = int(os.getenv("SLOT_HORIZON_HOURS", "24"))

    # По умолчанию стараемся давать "живой" источник (LinkedIn bridge),
    # а mock оставляем как страховку, чтобы UX не ломался.
    PARSER_DEFAULT_SOURCES = _get_list_from_env("PARSER_DEFAULT_SOURCES", "linkedin,mock")
    PARSER_RESULTS_LIMIT = int(os.getenv("PARSER_RESULTS_LIMIT", "50"))

    ENABLE_MOCK_SOURCE = os.getenv("ENABLE_MOCK_SOURCE", "1") == "1"
    ENABLE_HH_SOURCE = os.getenv("ENABLE_HH_SOURCE", "0") == "1"

    LINKEDIN_PROXY_ENABLED = os.getenv("LINKEDIN_PROXY_ENABLED", "0") == "1"
    LINKEDIN_PROXY_SCHEME = os.getenv("LINKEDIN_PROXY_SCHEME", "http").strip().lower()
    LINKEDIN_PROXY_HOST = os.getenv("LINKEDIN_PROXY_HOST", "").strip()
    LINKEDIN_PROXY_PORT = int(os.getenv("LINKEDIN_PROXY_PORT", "0"))
    LINKEDIN_PROXY_USERNAME = os.getenv("LINKEDIN_PROXY_USERNAME", "").strip()
    LINKEDIN_PROXY_PASSWORD = os.getenv("LINKEDIN_PROXY_PASSWORD", "").strip()

    LINKEDIN_PROXY_URL = os.getenv("LINKEDIN_PROXY_URL", "").strip()

    if LINKEDIN_PROXY_URL:
        EFFECTIVE_LINKEDIN_PROXY_URL = LINKEDIN_PROXY_URL
    elif LINKEDIN_PROXY_ENABLED and LINKEDIN_PROXY_HOST and LINKEDIN_PROXY_PORT:
        if LINKEDIN_PROXY_USERNAME and LINKEDIN_PROXY_PASSWORD:
            EFFECTIVE_LINKEDIN_PROXY_URL = (
                f"{LINKEDIN_PROXY_SCHEME}://"
                f"{LINKEDIN_PROXY_USERNAME}:{LINKEDIN_PROXY_PASSWORD}@"
                f"{LINKEDIN_PROXY_HOST}:{LINKEDIN_PROXY_PORT}"
            )
        else:
            EFFECTIVE_LINKEDIN_PROXY_URL = (
                f"{LINKEDIN_PROXY_SCHEME}://"
                f"{LINKEDIN_PROXY_HOST}:{LINKEDIN_PROXY_PORT}"
            )
    else:
        EFFECTIVE_LINKEDIN_PROXY_URL = ""

    LINKEDIN_BROWSER_PROFILE_ENABLED = os.getenv("LINKEDIN_BROWSER_PROFILE_ENABLED", "1") == "1"
    LINKEDIN_BROWSER_PROFILE_DIR = os.getenv(
        "LINKEDIN_BROWSER_PROFILE_DIR",
        "/var/www/matrix-parser/browser_profiles/linkedin",
    ).strip()
    LINKEDIN_HEADLESS = os.getenv("LINKEDIN_HEADLESS", "1") == "1"
    LINKEDIN_NAVIGATION_TIMEOUT_MS = int(os.getenv("LINKEDIN_NAVIGATION_TIMEOUT_MS", "45000"))

    # LinkedIn jobs scraping tuning (Playwright bridge)
    LINKEDIN_JOBS_MAX_CARDS = int(os.getenv("LINKEDIN_JOBS_MAX_CARDS", "18"))
    LINKEDIN_JOBS_MAX_DETAILS = int(os.getenv("LINKEDIN_JOBS_MAX_DETAILS", "10"))
    LINKEDIN_JOBS_SCROLL_STEPS = int(os.getenv("LINKEDIN_JOBS_SCROLL_STEPS", "4"))
    LINKEDIN_JOBS_SCROLL_DELAY_MS = int(os.getenv("LINKEDIN_JOBS_SCROLL_DELAY_MS", "650"))
    LINKEDIN_JOBS_SLOWMO_MS = int(os.getenv("LINKEDIN_JOBS_SLOWMO_MS", "0"))
