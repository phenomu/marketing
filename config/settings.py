"""MARKETING application configuration.

Single source of truth for settings: real environment variables first (docker
compose injects these), then a local .env file (native development), then
defaults. Native and Docker execution use exactly this module (repo rule:
env-only configuration, secrets never hardcoded).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> dict[str, str]:
    """Minimal .env parser (no extra dependency). Never overrides real env vars."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip().strip('"').strip("'")
        if " #" in val:  # inline comment: KEY=value # comment
            val = val.split(" #", 1)[0].strip()
        values[key.strip()] = val
    return values


_ENV_FILE_VALUES = _load_dotenv(REPO_ROOT / ".env")


def get(key: str, default: str = "") -> str:
    """Real environment wins over .env file (containers inject real env)."""
    if key in os.environ:
        return os.environ[key]
    return _ENV_FILE_VALUES.get(key, default)


def get_bool(key: str, default: bool) -> bool:
    raw = get(key, str(default)).strip().lower()
    return raw in ("1", "true", "yes", "on")


def get_int(key: str, default: int) -> int:
    try:
        return int(get(key, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    """Frozen config object — import `settings`, never module-level copies."""

    app_name: str
    app_env: str
    version: str
    log_level: str
    log_dir: Path
    database_url: str
    backend_url: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_pass: str
    smtp_from: str
    sender_name: str
    dry_run: bool
    lead_source: str
    google_places_api_key: str
    serpapi_api_key: str
    scrape_delay_s: float
    scrape_timeout_s: int
    scrape_max_results: int
    gmaps_hl: str
    gmaps_gl: str
    worker_interval_s: int
    scheduler_interval_s: int
    crawl_delay_s: float
    crawl_max_pages: int
    crawl_timeout_s: int
    crawl_retries: int
    crawl_user_agent: str
    crawl_batch_limit: int
    extract_batch_limit: int
    validate_batch_limit: int
    outreach_send_live: bool
    outreach_batch_limit: int
    outreach_send_per_day: int
    smtp_timeout_s: int
    unsubscribe_base_url: str
    unsubscribe_secret: str

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def database_configured(self) -> bool:
        return bool(self.database_url)


def _build_database_url() -> str:
    # Explicit DATABASE_URL wins; otherwise compose from POSTGRES_* parts.
    if (explicit := get("DATABASE_URL")).strip():
        return explicit.strip()
    user = get("POSTGRES_USER", "marketing")
    password = get("POSTGRES_PASSWORD", "")
    host = get("POSTGRES_HOST", "127.0.0.1")
    port = get("POSTGRES_PORT", "5432")
    database = get("POSTGRES_DB", "marketing")
    if not password:
        return ""  # DB not configured — services report it, never crash at import
    return f"postgresql://{quote(user)}:{quote(password)}@{host}:{port}/{database}"


def build_settings() -> Settings:
    return Settings(
        app_name="marketing",
        app_env=get("APP_ENV", "development"),
        version="0.1.0",
        log_level=get("LOG_LEVEL", "INFO"),
        log_dir=(lambda p: p if p.is_absolute() else (REPO_ROOT / p))(
            Path(get("LOG_DIR", "logs"))
        ),
        database_url=_build_database_url(),
        backend_url=get("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/"),
        smtp_host=get("SMTP_HOST", ""),
        smtp_port=get_int("SMTP_PORT", 587),
        smtp_user=get("SMTP_USER", ""),
        smtp_pass=get("SMTP_PASS", ""),
        smtp_from=get("SMTP_FROM", ""),
        sender_name=get("SENDER_NAME", "MARKETING"),
        dry_run=get_bool("DRY_RUN", True),
        lead_source=get("LEAD_SOURCE", "gmaps_scrape").strip().lower(),
        google_places_api_key=get("GOOGLE_PLACES_API_KEY", "").strip(),
        serpapi_api_key=get("SERPAPI_KEY", "").strip(),
        scrape_delay_s=float(get("SCRAPE_DELAY_S", "3")),
        scrape_timeout_s=get_int("SCRAPE_TIMEOUT_S", 20),
        scrape_max_results=get_int("SCRAPE_MAX_RESULTS", 20),
        gmaps_hl=get("GMAPS_HL", "en"),
        gmaps_gl=get("GMAPS_GL", "id"),
        worker_interval_s=get_int("WORKER_INTERVAL_S", 30),
        scheduler_interval_s=get_int("SCHEDULER_INTERVAL_S", 60),
        crawl_delay_s=float(get("CRAWL_DELAY_S", "5")),
        crawl_max_pages=get_int("CRAWL_MAX_PAGES", 10),
        crawl_timeout_s=get_int("CRAWL_TIMEOUT_S", 15),
        crawl_retries=get_int("CRAWL_RETRIES", 2),
        crawl_user_agent=get(
            "CRAWL_USER_AGENT",
            "marketing-research-bot/0.1 (+contact discovery; respects robots.txt)",
        ),
        crawl_batch_limit=get_int("CRAWL_BATCH_LIMIT", 5),
        extract_batch_limit=get_int("EXTRACT_BATCH_LIMIT", 10),
        validate_batch_limit=get_int("VALIDATE_BATCH_LIMIT", 5),
        outreach_send_live=get_bool("OUTREACH_SEND_LIVE", False),
        outreach_batch_limit=get_int("OUTREACH_BATCH_LIMIT", 10),
        outreach_send_per_day=get_int("OUTREACH_SEND_PER_DAY", 50),
        smtp_timeout_s=get_int("SMTP_TIMEOUT_S", 15),
        unsubscribe_base_url=get("UNSUBSCRIBE_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
        unsubscribe_secret=get("UNSUBSCRIBE_SECRET", ""),
    )


settings = build_settings()
