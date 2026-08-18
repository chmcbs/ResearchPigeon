"""
UK clock for the daily digest worker: start at 4am, send at 6am.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from core.logging import get_logger

logger = get_logger(__name__)

LONDON_TZ = ZoneInfo("Europe/London")
DIGEST_START_HOUR = 4
DIGEST_SEND_HOUR = 6


def london_now(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(LONDON_TZ)
    if now.tzinfo is None:
        return now.replace(tzinfo=LONDON_TZ)
    return now.astimezone(LONDON_TZ)


def _today_at(hour: int, now: datetime) -> datetime:
    current = london_now(now)
    return current.replace(hour=hour, minute=0, second=0, microsecond=0)


def seconds_until_today_start(now: datetime | None = None) -> float:
    current = london_now(now)
    start = _today_at(DIGEST_START_HOUR, current)
    if current >= start:
        return 0.0
    return (start - current).total_seconds()


def seconds_until_next_start(now: datetime | None = None) -> float:
    current = london_now(now)
    start = _today_at(DIGEST_START_HOUR, current)
    if current < start:
        return (start - current).total_seconds()
    next_start = start + timedelta(days=1)
    return (next_start - current).total_seconds()


def seconds_until_send(now: datetime | None = None) -> float:
    current = london_now(now)
    send_at = _today_at(DIGEST_SEND_HOUR, current)
    if current >= send_at:
        return 0.0
    return (send_at - current).total_seconds()


def _sleep_until(*, seconds: float, reason: str, sleep_fn=time.sleep) -> None:
    wait_s = max(0.0, seconds)
    if wait_s <= 0:
        logger.info(
            "Digest schedule wait skipped",
            extra={"event": "cron.schedule.wait_skipped", "reason": reason},
        )
        return
    logger.info(
        "Digest schedule waiting",
        extra={
            "event": "cron.schedule.waiting",
            "reason": reason,
            "wait_s": int(wait_s),
        },
    )
    sleep_fn(wait_s)


def wait_until_today_start(*, now: datetime | None = None, sleep_fn=time.sleep) -> None:
    _sleep_until(
        seconds=seconds_until_today_start(now),
        reason="today-start",
        sleep_fn=sleep_fn,
    )


def wait_until_next_start(*, now: datetime | None = None, sleep_fn=time.sleep) -> None:
    _sleep_until(
        seconds=seconds_until_next_start(now),
        reason="next-start",
        sleep_fn=sleep_fn,
    )


def wait_until_digest_send_time(*, now: datetime | None = None, sleep_fn=time.sleep) -> None:
    _sleep_until(
        seconds=seconds_until_send(now),
        reason="send",
        sleep_fn=sleep_fn,
    )


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if args == ["wait-start"]:
        wait_until_today_start()
        return 0
    if args == ["wait-next-start"]:
        wait_until_next_start()
        return 0
    raise SystemExit(
        "Usage: python -m core.cron_schedule wait-start|wait-next-start"
    )


if __name__ == "__main__":
    raise SystemExit(main())
