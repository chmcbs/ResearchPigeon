"""
Smoke tests for worker cron entrypoint
"""

from unittest.mock import Mock

import scripts.run_daily_cron as run_daily_cron


def test_worker_cron_main_calls_core_runner_and_prints_payload(monkeypatch, capsys):
    monkeypatch.setattr(
        run_daily_cron,
        "run_daily_digest_for_all_users",
        Mock(return_value={"users_seen": 1, "users_succeeded": 1}),
    )

    exit_code = run_daily_cron.main()
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "users_seen" in captured.out
