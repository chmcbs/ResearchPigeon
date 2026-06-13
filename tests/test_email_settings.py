"""
Tests for user email subscription settings
"""

from unittest.mock import MagicMock, Mock

import pytest

from core import config
from core import db as db_module
from core import email_settings


def _mock_connection_with_cursor(cursor):
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor

    connect = MagicMock()
    connect.return_value.__enter__.return_value = connection
    return connect


def test_derive_unsubscribe_token_is_stable_for_user(monkeypatch):
    monkeypatch.setenv("EMAIL_UNSUBSCRIBE_SECRET", "test-secret")

    first = email_settings.derive_unsubscribe_token("user@example.com")
    second = email_settings.derive_unsubscribe_token("user@example.com")

    assert first == second
    assert len(first) == 64


def test_build_unsubscribe_url_includes_token(monkeypatch):
    monkeypatch.setenv("APP_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("EMAIL_UNSUBSCRIBE_SECRET", "test-secret")

    url = email_settings.build_unsubscribe_url("user@example.com")

    assert url.startswith("http://localhost:8000/email/unsubscribe?token=")
    assert url.endswith(email_settings.derive_unsubscribe_token("user@example.com"))


def test_get_digest_subscribed_defaults_true_when_missing_row(monkeypatch):
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    monkeypatch.setattr(
        db_module.psycopg,
        "connect",
        _mock_connection_with_cursor(cursor),
    )

    assert email_settings.get_digest_subscribed("user@example.com") is True


def test_set_digest_subscribed_updates_row(monkeypatch):
    cursor = MagicMock()
    cursor.fetchone.return_value = (False, "2026-06-13T00:00:00+00:00")
    monkeypatch.setattr(
        db_module.psycopg,
        "connect",
        _mock_connection_with_cursor(cursor),
    )
    monkeypatch.setattr(email_settings, "ensure_email_settings", Mock())

    payload = email_settings.set_digest_subscribed(
        "user@example.com",
        digest_subscribed=False,
    )

    assert payload["digest_subscribed"] is False
    assert payload["unsubscribed_at"] == "2026-06-13T00:00:00+00:00"


def test_unsubscribe_by_token_returns_user_id(monkeypatch):
    monkeypatch.setattr(
        email_settings,
        "resolve_user_id_from_token",
        Mock(return_value="user@example.com"),
    )
    set_subscribed = Mock(return_value={"digest_subscribed": False, "unsubscribed_at": None})
    monkeypatch.setattr(email_settings, "set_digest_subscribed", set_subscribed)

    user_id = email_settings.unsubscribe_by_token("token-value")

    assert user_id == "user@example.com"
    set_subscribed.assert_called_once_with(
        "user@example.com",
        digest_subscribed=False,
        conn=None,
    )


def test_unsubscribe_by_token_returns_none_for_invalid_token(monkeypatch):
    monkeypatch.setattr(
        email_settings,
        "resolve_user_id_from_token",
        Mock(return_value=None),
    )

    assert email_settings.unsubscribe_by_token("bad-token") is None


def test_get_email_unsubscribe_secret_requires_env_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("EMAIL_UNSUBSCRIBE_SECRET", raising=False)

    with pytest.raises(ValueError, match="EMAIL_UNSUBSCRIBE_SECRET"):
        config.get_email_unsubscribe_secret()
