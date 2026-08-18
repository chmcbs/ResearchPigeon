#!/usr/bin/env python3
"""
Run the daily digest cron directly from the worker process
"""

from core.cron import run_daily_digest_for_all_users
from core.logging import configure_logging, get_logger

logger = get_logger(__name__)


def main() -> int:
    configure_logging()
    try:
        payload = run_daily_digest_for_all_users()
    except Exception:
        logger.exception(
            "Daily digest cron crashed",
            extra={"event": "cron.daily_digest.crashed"},
        )
        return 1
    print(payload)
    if payload.get("status") == "unsafe-config":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
