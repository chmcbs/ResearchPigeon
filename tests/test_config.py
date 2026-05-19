"""
Tests config module helpers
"""

import pytest

from core import config


def test_get_arxiv_categories_uses_default(monkeypatch):
    monkeypatch.delenv("ARXIV_CATEGORIES", raising=False)

    assert config.get_arxiv_categories() == ["cs.AI"]


def test_get_arxiv_categories_parses_comma_separated(monkeypatch):
    monkeypatch.setenv("ARXIV_CATEGORIES", "cs.AI, cs.CL, cs.LG")

    assert config.get_arxiv_categories() == ["cs.AI", "cs.CL", "cs.LG"]


def test_get_arxiv_categories_rejects_empty(monkeypatch):
    monkeypatch.setenv("ARXIV_CATEGORIES", "  ,  , ")

    with pytest.raises(ValueError, match="At least one"):
        config.get_arxiv_categories()


def test_get_daily_picks_k_uses_default():
    assert config.get_daily_picks_k() >= 1


def test_get_daily_picks_k_rejects_invalid_value(monkeypatch):
    monkeypatch.setattr(config, "DEFAULT_DAILY_K", 0)

    with pytest.raises(ValueError, match="must be >= 1"):
        config.get_daily_picks_k()


def test_get_keyword_boost_cap_uses_default(monkeypatch):
    monkeypatch.delenv("KEYWORD_BOOST_CAP", raising=False)
    assert config.get_keyword_boost_cap() == 0.25


def test_get_keyword_boost_cap_reads_environment(monkeypatch):
    monkeypatch.setenv("KEYWORD_BOOST_CAP", "0.4")
    assert config.get_keyword_boost_cap() == 0.4


def test_get_keyword_boost_cap_rejects_negative(monkeypatch):
    monkeypatch.setenv("KEYWORD_BOOST_CAP", "-0.1")
    with pytest.raises(ValueError, match="non-negative"):
        config.get_keyword_boost_cap()


def test_get_debug_admin_emails_parses_comma_separated(monkeypatch):
    monkeypatch.setenv("DEBUG_ADMIN_EMAILS", " Admin@Example.com , dev@test.io ")

    assert config.get_debug_admin_emails() == frozenset(
        {"admin@example.com", "dev@test.io"}
    )


def test_get_debug_admin_emails_empty_when_unset(monkeypatch):
    monkeypatch.delenv("DEBUG_ADMIN_EMAILS", raising=False)

    assert config.get_debug_admin_emails() == frozenset()


def test_is_production_reads_app_env(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    assert config.is_production() is True

    monkeypatch.setenv("APP_ENV", "development")
    assert config.is_production() is False
