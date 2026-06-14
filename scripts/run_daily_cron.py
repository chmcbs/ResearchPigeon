#!/usr/bin/env python3
"""
Run the daily digest cron directly from the worker process
"""

from core.cron import run_daily_digest_for_all_users


def main() -> int:
    payload = run_daily_digest_for_all_users()
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
