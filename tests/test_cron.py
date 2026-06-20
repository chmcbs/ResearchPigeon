"""
Tests scheduled digest cron helpers
"""

from unittest.mock import MagicMock, Mock

import pytest

from core import cron
from core import db as db_module


@pytest.fixture(autouse=True)
def _monitor_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("MONITOR_STATE_PATH", str(tmp_path / "monitor-state.json"))
    monkeypatch.setenv("MONITOR_DAILY_SUMMARY_ENABLED", "0")
    lock_conn = MagicMock()
    monkeypatch.setattr(cron, "_open_cron_lock_connection", Mock(return_value=lock_conn))
    monkeypatch.setattr(cron, "_acquire_cron_orchestration_lock", Mock(return_value=True))
    monkeypatch.setattr(cron, "_release_cron_orchestration_lock", Mock())
    monkeypatch.setattr(cron, "_claim_cron_window", Mock(return_value=True))
    monkeypatch.setattr(cron, "_mark_cron_window_completed", Mock())
    monkeypatch.setattr(cron, "_mark_cron_window_failed", Mock())


def test_list_users_with_digest_selection_returns_distinct_user_ids(monkeypatch):
    cursor = MagicMock()
    cursor.fetchall.return_value = [("user-a",), ("user-b",)]
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    connect = MagicMock()
    connect.return_value.__enter__.return_value = connection
    monkeypatch.setattr(db_module.psycopg, "connect", connect)

    assert cron.list_users_with_digest_selection() == ["user-a", "user-b"]


def test_run_daily_digest_for_all_users_skips_users_without_profiles(monkeypatch):
    monkeypatch.setattr(cron, "list_users_with_digest_selection", Mock(return_value=["user-1"]))
    monkeypatch.setattr(cron, "list_digest_selected_profile_ids", Mock(return_value=[]))
    run_shared = Mock()
    run_recommendations = Mock()
    monkeypatch.setattr(cron, "run_shared_pipeline_steps", run_shared)
    monkeypatch.setattr(cron, "run_recommendations_for_profiles", run_recommendations)

    payload = cron.run_daily_digest_for_all_users()

    assert payload["users_seen"] == 1
    assert payload["users_skipped"] == 1
    assert payload["users_succeeded"] == 0
    run_shared.assert_not_called()
    run_recommendations.assert_not_called()


def test_run_daily_digest_for_all_users_skips_when_locked(monkeypatch):
    monkeypatch.setattr(cron, "_acquire_cron_orchestration_lock", Mock(return_value=False))

    payload = cron.run_daily_digest_for_all_users()

    assert payload["status"] == "locked"
    assert payload["results"] == []
    assert payload["users_seen"] == 0


def test_run_daily_digest_for_all_users_skips_when_window_already_ran(monkeypatch):
    monkeypatch.setattr(cron, "_claim_cron_window", Mock(return_value=False))

    payload = cron.run_daily_digest_for_all_users()

    assert payload["status"] == "already-ran-window"
    assert payload["results"] == []
    assert payload["users_seen"] == 0


def test_run_daily_digest_for_all_users_runs_shared_steps_once(monkeypatch):
    monkeypatch.setattr(
        cron,
        "list_users_with_digest_selection",
        Mock(return_value=["user-1", "user-2"]),
    )
    monkeypatch.setattr(
        cron,
        "list_digest_selected_profile_ids",
        Mock(side_effect=[["profile-1"], ["profile-2"]]),
    )
    run_shared = Mock(return_value={"run_ids": ["run-shared"], "embedded_count": 3})
    run_recommendations = Mock()
    description_batch = Mock(return_value={"succeeded": 1})
    deliver_email = Mock(return_value={"status": "sent", "error_message": None})
    monkeypatch.setattr(cron, "list_digest_categories", Mock(return_value=["cs.AI"]))
    monkeypatch.setattr(cron, "run_shared_pipeline_steps", run_shared)
    monkeypatch.setattr(cron, "run_recommendations_for_profiles", run_recommendations)
    monkeypatch.setattr(cron, "run_description_batch_for_recommendations", description_batch)
    monkeypatch.setattr(cron, "deliver_digest_email_for_user", deliver_email)

    payload = cron.run_daily_digest_for_all_users()

    assert payload["users_succeeded"] == 2
    run_shared.assert_called_once_with(
        categories=["cs.AI"],
        max_results=150,
        embedding_limit=600,
    )
    assert run_recommendations.call_count == 2
    run_recommendations.assert_any_call(
        user_id="user-1",
        profile_ids=["profile-1"],
        run_ids=["run-shared"],
    )
    run_recommendations.assert_any_call(
        user_id="user-2",
        profile_ids=["profile-2"],
        run_ids=["run-shared"],
    )
    assert payload["results"][0]["run_ids"] == ["run-shared"]
    assert payload["results"][1]["run_ids"] == ["run-shared"]
    description_batch.assert_called_once_with(
        run_ids=["run-shared"],
        conn=None,
    )
    assert deliver_email.call_count == 2
    assert payload["results"][0]["email_status"] == "sent"
    assert payload["results"][1]["email_status"] == "sent"


def test_run_daily_digest_for_all_users_marks_users_failed_when_shared_steps_fail(
    monkeypatch,
):
    monkeypatch.setattr(
        cron,
        "list_users_with_digest_selection",
        Mock(return_value=["user-1", "user-2"]),
    )
    monkeypatch.setattr(
        cron,
        "list_digest_selected_profile_ids",
        Mock(side_effect=[["profile-1"], ["profile-2"]]),
    )
    monkeypatch.setattr(cron, "list_digest_categories", Mock(return_value=["cs.AI"]))
    monkeypatch.setattr(
        cron,
        "run_shared_pipeline_steps",
        Mock(side_effect=RuntimeError("ingestion failed")),
    )
    run_recommendations = Mock()
    monkeypatch.setattr(cron, "run_recommendations_for_profiles", run_recommendations)

    payload = cron.run_daily_digest_for_all_users()

    assert payload["users_failed"] == 2
    assert payload["users_succeeded"] == 0
    run_recommendations.assert_not_called()
    assert payload["results"][0]["error_message"] == "ingestion failed"


def test_run_daily_digest_for_all_users_alerts_admin_when_blurb_batch_fails(
    monkeypatch,
):
    monkeypatch.setattr(
        cron,
        "list_users_with_digest_selection",
        Mock(return_value=["user-1"]),
    )
    monkeypatch.setattr(
        cron,
        "list_digest_selected_profile_ids",
        Mock(return_value=["profile-1"]),
    )
    monkeypatch.setattr(cron, "list_digest_categories", Mock(return_value=["cs.AI"]))
    monkeypatch.setattr(
        cron,
        "run_shared_pipeline_steps",
        Mock(return_value={"run_ids": ["run-shared"], "embedded_count": 3}),
    )
    monkeypatch.setattr(cron, "run_recommendations_for_profiles", Mock())
    monkeypatch.setattr(
        cron,
        "run_description_batch_for_recommendations",
        Mock(side_effect=RuntimeError("llm unavailable")),
    )
    deliver_user_email = Mock(return_value={"status": "sent", "error_message": None})
    monkeypatch.setattr(cron, "deliver_digest_email_for_user", deliver_user_email)
    monkeypatch.setattr(cron, "get_debug_admin_emails", lambda: frozenset({"admin@example.com"}))
    monkeypatch.setattr(cron, "is_email_delivery_configured", lambda: True)
    monkeypatch.setattr(cron, "get_product_name", lambda: "Paper Radar")
    monkeypatch.setattr(cron, "get_email_from", lambda: "noreply@example.com")
    send_admin_alert = Mock()
    monkeypatch.setattr(cron, "deliver_email_message", send_admin_alert)

    payload = cron.run_daily_digest_for_all_users()

    assert payload["users_succeeded"] == 1
    assert payload["description_batch"] == {}
    deliver_user_email.assert_called_once()
    send_admin_alert.assert_called_once()
    message = send_admin_alert.call_args.args[0]
    assert message["To"] == "admin@example.com"
    assert "LLM blurb batch failed" in message["Subject"]
    assert "User digests continued to send without descriptions." in message.get_content()


def test_run_daily_digest_for_all_users_skips_alert_when_no_admin_recipients(
    monkeypatch,
):
    monkeypatch.setattr(
        cron,
        "list_users_with_digest_selection",
        Mock(return_value=["user-1"]),
    )
    monkeypatch.setattr(
        cron,
        "list_digest_selected_profile_ids",
        Mock(return_value=["profile-1"]),
    )
    monkeypatch.setattr(cron, "list_digest_categories", Mock(return_value=["cs.AI"]))
    monkeypatch.setattr(
        cron,
        "run_shared_pipeline_steps",
        Mock(return_value={"run_ids": ["run-shared"], "embedded_count": 3}),
    )
    monkeypatch.setattr(cron, "run_recommendations_for_profiles", Mock())
    monkeypatch.setattr(
        cron,
        "run_description_batch_for_recommendations",
        Mock(side_effect=RuntimeError("llm unavailable")),
    )
    monkeypatch.setattr(
        cron,
        "deliver_digest_email_for_user",
        Mock(return_value={"status": "sent", "error_message": None}),
    )
    monkeypatch.setattr(cron, "get_debug_admin_emails", lambda: frozenset())
    send_admin_alert = Mock()
    monkeypatch.setattr(cron, "deliver_email_message", send_admin_alert)

    payload = cron.run_daily_digest_for_all_users()

    assert payload["users_succeeded"] == 1
    send_admin_alert.assert_not_called()


def test_run_daily_digest_for_all_users_alerts_when_failure_threshold_exceeded(
    monkeypatch,
):
    monkeypatch.setattr(
        cron,
        "list_users_with_digest_selection",
        Mock(return_value=["user-1"]),
    )
    monkeypatch.setattr(
        cron,
        "list_digest_selected_profile_ids",
        Mock(return_value=["profile-1"]),
    )
    monkeypatch.setattr(cron, "list_digest_categories", Mock(return_value=["cs.AI"]))
    monkeypatch.setattr(
        cron,
        "run_shared_pipeline_steps",
        Mock(return_value={"run_ids": ["run-shared"], "embedded_count": 3}),
    )
    monkeypatch.setattr(cron, "run_recommendations_for_profiles", Mock())
    monkeypatch.setattr(
        cron,
        "run_description_batch_for_recommendations",
        Mock(
            return_value={
                "attempted": 10,
                "succeeded": 6,
                "failed": 2,
                "skipped_timeout": 1,
                "skipped_validation": 1,
                "skipped_budget": 0,
            }
        ),
    )
    monkeypatch.setattr(
        cron,
        "deliver_digest_email_for_user",
        Mock(return_value={"status": "sent", "error_message": None}),
    )
    monkeypatch.setattr(cron, "get_debug_admin_emails", lambda: frozenset({"admin@example.com"}))
    monkeypatch.setattr(cron, "is_email_delivery_configured", lambda: True)
    monkeypatch.setattr(cron, "get_product_name", lambda: "Paper Radar")
    monkeypatch.setattr(cron, "get_email_from", lambda: "noreply@example.com")
    monkeypatch.setattr(cron, "get_llm_failure_alert_threshold", lambda: 0.10)
    send_admin_alert = Mock()
    monkeypatch.setattr(cron, "deliver_email_message", send_admin_alert)

    payload = cron.run_daily_digest_for_all_users()

    assert payload["users_succeeded"] == 1
    send_admin_alert.assert_called_once()
    message = send_admin_alert.call_args.args[0]
    assert "LLM blurb quality degraded" in message["Subject"]
    assert "Failure rate: 40.0%" in message.get_content()


def test_run_daily_digest_retries_failed_email_delivery(monkeypatch):
    monkeypatch.setattr(
        cron,
        "list_users_with_digest_selection",
        Mock(return_value=["user-1"]),
    )
    monkeypatch.setattr(
        cron,
        "list_digest_selected_profile_ids",
        Mock(return_value=["profile-1"]),
    )
    monkeypatch.setattr(cron, "list_digest_categories", Mock(return_value=["cs.AI"]))
    monkeypatch.setattr(
        cron,
        "run_shared_pipeline_steps",
        Mock(return_value={"run_ids": ["run-shared"], "embedded_count": 3}),
    )
    monkeypatch.setattr(cron, "run_recommendations_for_profiles", Mock())
    monkeypatch.setattr(
        cron,
        "run_description_batch_for_recommendations",
        Mock(return_value={"attempted": 0}),
    )
    deliver_email = Mock(
        side_effect=[
            {"status": "failed", "error_message": "smtp timeout"},
            {"status": "sent", "error_message": None},
        ]
    )
    monkeypatch.setattr(cron, "deliver_digest_email_for_user", deliver_email)

    payload = cron.run_daily_digest_for_all_users()

    assert deliver_email.call_count == 2
    assert payload["results"][0]["email_status"] == "sent"
