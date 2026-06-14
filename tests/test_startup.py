"""
Tests production startup configuration validation
"""

import pytest

from core.startup import StartupConfigError, validate_runtime_config


def _set_valid_production_env(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://postgres:postgres@db:5432/arxiv"
    )
    monkeypatch.setenv("APP_BASE_URL", "https://app.example.com")
    monkeypatch.delenv("DISABLE_CSRF", raising=False)
    monkeypatch.delenv("DISABLE_RATE_LIMIT", raising=False)
    monkeypatch.delenv("ALLOW_DEV_MAGIC_LINK_RESPONSE", raising=False)
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("EMAIL_FROM", "noreply@example.com")
    monkeypatch.setenv("EMAIL_UNSUBSCRIBE_SECRET", "y" * 32)


def test_validate_runtime_config_allows_development_defaults(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("DISABLE_CSRF", raising=False)

    validate_runtime_config()


def test_validate_runtime_config_rejects_disabled_csrf_in_production(monkeypatch):
    _set_valid_production_env(monkeypatch)
    monkeypatch.setenv("DISABLE_CSRF", "1")

    with pytest.raises(StartupConfigError, match="DISABLE_CSRF"):
        validate_runtime_config()


def test_validate_runtime_config_requires_email_delivery_in_production(monkeypatch):
    _set_valid_production_env(monkeypatch)
    monkeypatch.delenv("SMTP_HOST", raising=False)

    with pytest.raises(StartupConfigError, match="SMTP_HOST and EMAIL_FROM"):
        validate_runtime_config()


def test_validate_runtime_config_requires_email_unsubscribe_secret_in_production(
    monkeypatch,
):
    _set_valid_production_env(monkeypatch)
    monkeypatch.delenv("EMAIL_UNSUBSCRIBE_SECRET", raising=False)

    with pytest.raises(StartupConfigError, match="EMAIL_UNSUBSCRIBE_SECRET"):
        validate_runtime_config()


def test_validate_runtime_config_allows_valid_production_settings(monkeypatch):
    _set_valid_production_env(monkeypatch)

    validate_runtime_config()


def test_validate_runtime_config_rejects_dev_magic_link_in_production(monkeypatch):
    _set_valid_production_env(monkeypatch)
    monkeypatch.setenv("ALLOW_DEV_MAGIC_LINK_RESPONSE", "1")

    with pytest.raises(StartupConfigError, match="ALLOW_DEV_MAGIC_LINK_RESPONSE"):
        validate_runtime_config()


def test_validate_runtime_config_rejects_disabled_rate_limit_in_production(
    monkeypatch,
):
    _set_valid_production_env(monkeypatch)
    monkeypatch.setenv("DISABLE_RATE_LIMIT", "1")

    with pytest.raises(StartupConfigError, match="DISABLE_RATE_LIMIT"):
        validate_runtime_config()


def test_validate_runtime_config_requires_database_url_in_production(monkeypatch):
    _set_valid_production_env(monkeypatch)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(StartupConfigError, match="DATABASE_URL"):
        validate_runtime_config()


def test_validate_runtime_config_requires_https_app_base_url_in_production(
    monkeypatch,
):
    _set_valid_production_env(monkeypatch)
    monkeypatch.setenv("APP_BASE_URL", "http://app.example.com")

    with pytest.raises(StartupConfigError, match="https"):
        validate_runtime_config()
