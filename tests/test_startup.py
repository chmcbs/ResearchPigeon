"""
Tests production startup configuration validation
"""

import pytest

from core.startup import StartupConfigError, validate_runtime_config


def test_validate_runtime_config_allows_development_defaults(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("DISABLE_CSRF", raising=False)

    validate_runtime_config()


def test_validate_runtime_config_rejects_disabled_csrf_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DISABLE_CSRF", "1")
    monkeypatch.setenv("INTERNAL_CRON_TOKEN", "x" * 32)

    with pytest.raises(StartupConfigError, match="DISABLE_CSRF"):
        validate_runtime_config()


def test_validate_runtime_config_requires_strong_cron_token_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("DISABLE_CSRF", raising=False)
    monkeypatch.delenv("DISABLE_RATE_LIMIT", raising=False)
    monkeypatch.delenv("ALLOW_DEV_MAGIC_LINK_RESPONSE", raising=False)
    monkeypatch.setenv("INTERNAL_CRON_TOKEN", "short")

    with pytest.raises(StartupConfigError, match="INTERNAL_CRON_TOKEN"):
        validate_runtime_config()
