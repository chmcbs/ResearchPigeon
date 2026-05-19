"""
Runtime configuration validation at application startup
"""

from core.config import (
    get_internal_cron_token,
    is_dev_magic_link_response_enabled,
    is_production,
    is_rate_limit_disabled,
    is_csrf_disabled,
)


class StartupConfigError(RuntimeError):
    """Raised when required production configuration is missing or unsafe."""


def validate_runtime_config() -> None:
    if not is_production():
        return

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

    token = get_internal_cron_token()
    if token is None or len(token) < 32:
        raise StartupConfigError(
            "INTERNAL_CRON_TOKEN must be set to a random string of at least 32 "
            "characters when APP_ENV is production"
        )
