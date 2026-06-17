"""
Rate limiting for sensitive authentication endpoints
"""

import threading
import time
from datetime import UTC, datetime, timedelta

import psycopg

from core.auth_messages import RATE_LIMIT_USER_MESSAGE
from core.config import is_database_rate_limit_enabled, is_rate_limit_disabled
from core.db import get_database_url


class RateLimitExceeded(ValueError):
    """Raised when a caller exceeds a configured rate limit."""


DELETE_EXPIRED_RATE_LIMIT_EVENTS_SQL = """
DELETE FROM rate_limit_events
WHERE attempted_at < %s;
"""

COUNT_RATE_LIMIT_EVENTS_SQL = """
SELECT COUNT(*)
FROM rate_limit_events
WHERE bucket_key = %s
  AND attempted_at >= %s;
"""

INSERT_RATE_LIMIT_EVENT_SQL = """
INSERT INTO rate_limit_events (bucket_key)
VALUES (%s);
"""


_lock = threading.Lock()
_attempts: dict[str, list[float]] = {}


def check_rate_limit(key: str, *, max_attempts: int, window_seconds: int) -> None:
    if is_rate_limit_disabled():
        return
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    if window_seconds < 1:
        raise ValueError("window_seconds must be >= 1")

    if is_database_rate_limit_enabled():
        _check_rate_limit_database(key, max_attempts=max_attempts, window_seconds=window_seconds)
        return

    _check_rate_limit_in_memory(key, max_attempts=max_attempts, window_seconds=window_seconds)


def _check_rate_limit_in_memory(
    key: str,
    *,
    max_attempts: int,
    window_seconds: int,
) -> None:
    now = time.monotonic()
    cutoff = now - window_seconds

    with _lock:
        # Rebuild buckets on each call to drop expired timestamps in one pass without background cleanup
        pruned: dict[str, list[float]] = {}
        for bucket_key, timestamps in _attempts.items():
            active = [timestamp for timestamp in timestamps if timestamp >= cutoff]
            if active:
                pruned[bucket_key] = active

        bucket = pruned.get(key, [])
        if len(bucket) >= max_attempts:
            raise RateLimitExceeded(RATE_LIMIT_USER_MESSAGE)

        bucket.append(now)
        pruned[key] = bucket
        _attempts.clear()
        _attempts.update(pruned)


def _check_rate_limit_database(
    key: str,
    *,
    max_attempts: int,
    window_seconds: int,
) -> None:
    cutoff = datetime.now(UTC) - timedelta(seconds=window_seconds)

    with psycopg.connect(get_database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(DELETE_EXPIRED_RATE_LIMIT_EVENTS_SQL, (cutoff,))
            cur.execute(COUNT_RATE_LIMIT_EVENTS_SQL, (key, cutoff))
            attempt_count = int(cur.fetchone()[0])
            if attempt_count >= max_attempts:
                raise RateLimitExceeded(RATE_LIMIT_USER_MESSAGE)
            cur.execute(INSERT_RATE_LIMIT_EVENT_SQL, (key,))


def reset_rate_limits() -> None:
    with _lock:
        _attempts.clear()
