"""
Default application settings
"""

import json
import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_CATEGORY_LABELS_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "arxiv_category_labels.json"
)

DEFAULT_USER_ID = os.getenv("DEFAULT_USER_ID", "default")
DEFAULT_DAILY_K = int(os.getenv("DAILY_PICKS_K", "3"))
DEFAULT_INTEREST_TEXT = os.getenv(
    "DEFAULT_INTEREST_TEXT",
    "I'm interested in learning about artificial intelligence research.",
)


# Ingestion
def get_arxiv_categories() -> list[str]:
    raw = os.getenv("ARXIV_CATEGORIES", "cs.AI")
    categories = [c.strip() for c in raw.split(",") if c.strip()]

    if not categories:
        raise ValueError("At least one arXiv category must be configured")

    return categories


@lru_cache(maxsize=1)
def _get_arxiv_category_labels() -> dict[str, str]:
    if not _CATEGORY_LABELS_PATH.is_file():
        return {}
    payload = json.loads(_CATEGORY_LABELS_PATH.read_text(encoding="utf-8"))
    return {str(key): str(value) for key, value in payload.items()}


def format_arxiv_category_label(category_id: str) -> str:
    name = _get_arxiv_category_labels().get(category_id.strip())
    if name:
        return f"{category_id} ({name})"
    return category_id


def get_arxiv_category_options() -> list[dict[str, str]]:
    return [
        {
            "id": category_id,
            "label": format_arxiv_category_label(category_id),
        }
        for category_id in get_arxiv_categories()
    ]


def get_ingestion_max_results() -> int:
    return max(1, int(os.getenv("INGESTION_MAX_RESULTS", "150")))


def get_embedding_limit() -> int:
    return max(1, int(os.getenv("EMBEDDING_LIMIT", "600")))


# Recommendation
def get_daily_picks_k() -> int:
    if DEFAULT_DAILY_K < 1:
        raise ValueError("DAILY_PICKS_K must be >= 1")

    return DEFAULT_DAILY_K


# Ranking
def get_keyword_boost_cap() -> float:
    raw_value = float(os.getenv("KEYWORD_BOOST_CAP", "0.25"))
    if raw_value < 0:
        raise ValueError("KEYWORD_BOOST_CAP must be non-negative")
    return raw_value


# URLs
def get_app_base_url() -> str:
    return os.getenv("APP_BASE_URL", "http://localhost:8000")


def is_app_https() -> bool:
    return get_app_base_url().lower().startswith("https://")


def is_production() -> bool:
    return os.getenv("APP_ENV", "").strip().lower() in ("production", "prod")


def _env_flag_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


def is_csrf_disabled() -> bool:
    return _env_flag_enabled("DISABLE_CSRF")


def is_rate_limit_disabled() -> bool:
    return _env_flag_enabled("DISABLE_RATE_LIMIT")


def is_dev_magic_link_response_enabled() -> bool:
    return _env_flag_enabled("ALLOW_DEV_MAGIC_LINK_RESPONSE")


def get_internal_cron_token() -> str | None:
    token = os.getenv("INTERNAL_CRON_TOKEN", "").strip()
    return token or None


def is_trust_proxy_headers_enabled() -> bool:
    return _env_flag_enabled("TRUST_PROXY_HEADERS")


# Debugging
def is_debug_digest_data_reset_enabled() -> bool:
    raw = os.getenv("ALLOW_DEBUG_DIGEST_DATA_RESET", "")
    return raw.strip().lower() in ("1", "true", "yes", "on")


def is_debug_features_enabled() -> bool:
    raw = os.getenv("ALLOW_DEBUG_FEATURES", "")
    if raw.strip():
        return raw.strip().lower() in ("1", "true", "yes", "on")
    return is_debug_digest_data_reset_enabled()


def get_debug_admin_emails() -> frozenset[str]:
    raw = os.getenv("DEBUG_ADMIN_EMAILS", "")
    return frozenset(
        email.strip().lower() for email in raw.split(",") if email.strip()
    )


# Auth rate limits
def get_magic_link_request_limit_per_email() -> int:
    return max(1, int(os.getenv("MAGIC_LINK_REQUEST_LIMIT_PER_EMAIL", "3")))


def get_magic_link_request_limit_per_ip() -> int:
    return max(1, int(os.getenv("MAGIC_LINK_REQUEST_LIMIT_PER_IP", "20")))


def get_magic_link_verify_limit_per_ip() -> int:
    return max(1, int(os.getenv("MAGIC_LINK_VERIFY_LIMIT_PER_IP", "30")))


def get_rate_limit_window_seconds() -> int:
    return max(60, int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "3600")))


def get_daily_picks_generate_limit_per_user() -> int:
    return max(1, int(os.getenv("DAILY_PICKS_GENERATE_LIMIT_PER_USER", "5")))


def is_database_rate_limit_enabled() -> bool:
    raw = os.getenv("RATE_LIMIT_USE_DATABASE", "").strip()
    if raw:
        return _env_flag_enabled("RATE_LIMIT_USE_DATABASE")
    return is_production()


# Email
def get_smtp_host() -> str:
    return os.getenv("SMTP_HOST", "").strip()


def get_smtp_port() -> int:
    return max(1, int(os.getenv("SMTP_PORT", "587")))


def get_smtp_username() -> str | None:
    value = os.getenv("SMTP_USERNAME", "").strip()
    return value or None


def get_smtp_password() -> str | None:
    value = os.getenv("SMTP_PASSWORD", "").strip()
    return value or None


def get_email_from() -> str:
    return os.getenv("EMAIL_FROM", "").strip()


def get_smtp_use_ssl() -> bool:
    raw = os.getenv("SMTP_USE_SSL", "").strip()
    if raw:
        return _env_flag_enabled("SMTP_USE_SSL")
    return get_smtp_port() == 465


def is_email_delivery_configured() -> bool:
    return bool(get_smtp_host() and get_email_from())
