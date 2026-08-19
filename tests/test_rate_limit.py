"""
Tests in-memory rate limiting helpers
"""

import time

import pytest

from core.rate_limit import RateLimitExceeded, check_rate_limit, reset_rate_limits


@pytest.fixture(autouse=True)
def _clear_limits(monkeypatch):
    monkeypatch.delenv("DISABLE_RATE_LIMIT", raising=False)
    reset_rate_limits()


def test_check_rate_limit_allows_up_to_max_attempts():
    for _ in range(3):
        check_rate_limit("key", max_attempts=3, window_seconds=60)


def test_check_rate_limit_blocks_additional_attempts():
    for _ in range(2):
        check_rate_limit("key", max_attempts=2, window_seconds=60)

    with pytest.raises(RateLimitExceeded, match="Too many sign-in attempts"):
        check_rate_limit("key", max_attempts=2, window_seconds=60)


def test_check_rate_limit_prunes_stale_in_memory_keys():
    check_rate_limit("stale-key", max_attempts=1, window_seconds=1)
    time.sleep(1.1)
    check_rate_limit("fresh-key", max_attempts=1, window_seconds=60)


def test_check_rate_limit_uses_database_backend_when_enabled(monkeypatch):
    import core.rate_limit as rate_limit_module

    monkeypatch.setattr(rate_limit_module, "is_database_rate_limit_enabled", lambda: True)
    calls: list[str] = []
    monkeypatch.setattr(
        rate_limit_module,
        "_check_rate_limit_database",
        lambda key, max_attempts, window_seconds: calls.append(key),
    )

    check_rate_limit("db-key", max_attempts=3, window_seconds=60)

    assert calls == ["db-key"]


def test_check_rate_limit_database_inserts_event(monkeypatch):
    from unittest.mock import MagicMock

    import core.rate_limit as rate_limit_module

    monkeypatch.setattr(rate_limit_module, "is_database_rate_limit_enabled", lambda: True)
    monkeypatch.setattr(rate_limit_module, "get_database_url", lambda: "postgresql://example")
    cursor = MagicMock()
    cursor.fetchone.return_value = (0,)
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    connect = MagicMock()
    connect.return_value.__enter__.return_value = connection
    monkeypatch.setattr(rate_limit_module.psycopg, "connect", connect)

    check_rate_limit("db-key", max_attempts=3, window_seconds=60)

    executed_sql = [call.args[0] for call in cursor.execute.call_args_list]
    assert any("INSERT INTO rate_limit_events" in sql for sql in executed_sql)
    assert cursor.execute.call_args.args == (
        rate_limit_module.INSERT_RATE_LIMIT_EVENT_SQL,
        ("db-key",),
    )


def test_check_rate_limit_database_blocks_when_at_limit(monkeypatch):
    from unittest.mock import MagicMock

    import core.rate_limit as rate_limit_module

    monkeypatch.setattr(rate_limit_module, "is_database_rate_limit_enabled", lambda: True)
    monkeypatch.setattr(rate_limit_module, "get_database_url", lambda: "postgresql://example")
    cursor = MagicMock()
    cursor.fetchone.return_value = (2,)
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    connect = MagicMock()
    connect.return_value.__enter__.return_value = connection
    monkeypatch.setattr(rate_limit_module.psycopg, "connect", connect)

    with pytest.raises(RateLimitExceeded, match="Too many sign-in attempts"):
        check_rate_limit("db-key", max_attempts=2, window_seconds=60)

    executed_sql = [call.args[0] for call in cursor.execute.call_args_list]
    assert not any("INSERT INTO rate_limit_events" in sql for sql in executed_sql)
