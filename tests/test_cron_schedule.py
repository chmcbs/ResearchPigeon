"""
Tests UK digest schedule helpers
"""

from datetime import datetime

from core.cron_schedule import (
    LONDON_TZ,
    main,
    seconds_until_next_start,
    seconds_until_send,
    seconds_until_today_start,
    wait_until_digest_send_time,
    wait_until_next_start,
    wait_until_today_start,
)


def _london(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=LONDON_TZ)


def test_before_4am_waits_for_today_start_and_send():
    now = _london(2026, 8, 18, 3, 30)
    assert seconds_until_today_start(now) == 30 * 60
    assert seconds_until_send(now) == (2 * 60 + 30) * 60
    assert seconds_until_next_start(now) == 30 * 60


def test_between_4am_and_6am_starts_now_and_waits_to_send():
    now = _london(2026, 8, 18, 4, 40)
    assert seconds_until_today_start(now) == 0
    assert seconds_until_send(now) == 80 * 60
    assert seconds_until_next_start(now) == (23 * 60 + 20) * 60


def test_after_6am_sends_immediately_and_next_start_is_tomorrow():
    now = _london(2026, 8, 18, 6, 15)
    assert seconds_until_today_start(now) == 0
    assert seconds_until_send(now) == 0
    assert seconds_until_next_start(now) == (21 * 60 + 45) * 60


def test_wait_helpers_sleep_only_when_needed():
    slept = []
    wait_until_today_start(now=_london(2026, 8, 18, 5, 0), sleep_fn=slept.append)
    wait_until_digest_send_time(now=_london(2026, 8, 18, 7, 0), sleep_fn=slept.append)
    wait_until_next_start(now=_london(2026, 8, 18, 4, 0), sleep_fn=slept.append)
    assert slept == [24 * 60 * 60]


def test_wait_until_send_sleeps_before_6am():
    slept = []
    wait_until_digest_send_time(now=_london(2026, 8, 18, 5, 0), sleep_fn=slept.append)
    assert slept == [60 * 60]


def test_schedule_cli_dispatches_wait_start(monkeypatch):
    called = []
    monkeypatch.setattr("core.cron_schedule.wait_until_today_start", lambda: called.append("start"))
    assert main(["wait-start"]) == 0
    assert called == ["start"]


def test_schedule_cli_dispatches_wait_next_start(monkeypatch):
    called = []
    monkeypatch.setattr("core.cron_schedule.wait_until_next_start", lambda: called.append("next"))
    assert main(["wait-next-start"]) == 0
    assert called == ["next"]
