"""
Runtime configuration validation at application startup
"""

import os

from core.config import (
    get_app_base_url,
    get_internal_cron_token,
    is_app_https,
    is_dev_magic_link_response_enabled,
    is_email_delivery_configured,
    is_production,
    is_rate_limit_disabled,
    is_csrf_disabled,
)


class StartupConfigError(RuntimeError):
    """Raised when required production configuration is missing or unsafe."""


def validate_runtime_config() -> None:
    if not is_production():
        return

    if not os.getenv("DATABASE_URL", "").strip():
        raise StartupConfigError(
            "DATABASE_URL must be set when APP_ENV is production"
        )

    if not get_app_base_url().strip():
        raise StartupConfigError(
            "APP_BASE_URL must be set when APP_ENV is production"
        )

    if not is_app_https():
        raise StartupConfigError(
            "APP_BASE_URL must use https when APP_ENV is production"
        )

    if is_csrf_disabled():
        raise StartupConfigError(
            "DISABLE_CSRF must not be set when APP_ENV is production"
        )

    if is_rate_limit_disabled():
        raise StartupConfigError(
            "DISABLE_RATE_LIMIT must not be set when APP_ENV is production"
        )

    if is_dev_magic_link_response_enabled():
        raise StartupConfigError(
            "ALLOW_DEV_MAGIC_LINK_RESPONSE must not be set when APP_ENV is production"
        )

    if not is_email_delivery_configured():
        raise StartupConfigError(
            "SMTP_HOST and EMAIL_FROM must be set when APP_ENV is production"
        )

    token = get_internal_cron_token()
    if token is None or len(token) < 32:
        raise StartupConfigError(
            "INTERNAL_CRON_TOKEN must be set to a random string of at least 32 "
            "characters when APP_ENV is production"
        )

    if not os.getenv("EMAIL_UNSUBSCRIBE_SECRET", "").strip():
        raise StartupConfigError(
            "EMAIL_UNSUBSCRIBE_SECRET must be set when APP_ENV is production"
        )
