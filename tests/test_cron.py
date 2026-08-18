"""
Tests scheduled digest cron helpers
"""

from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import MagicMock, Mock

import pytest

from core import cron
from core import db as db_module

_REAL_CLAIM_CRON_WINDOW = cron._claim_cron_window
_REAL_GET_DIGEST_SEND_OUTCOME = cron.get_digest_send_outcome
_REAL_RECORD_DIGEST_SEND_OUTCOME = cron.record_digest_send_outcome


@pytest.fixture(autouse=True)
def _monitor_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("MONITOR_STATE_PATH", str(tmp_path / "monitor-state.json"))
    monkeypatch.setenv("MONITOR_DAILY_SUMMARY_ENABLED", "0")
    lock_conn = MagicMock()
    monkeypatch.setattr(cron, "_open_cron_lock_connection", Mock(return_value=lock_conn))
    monkeypatch.setattr(cron, "_acquire_cron_orchestration_lock", Mock(return_value=True))
    monkeypatch.setattr(cron, "_release_cron_orchestration_lock", Mock())
    monkeypatch.setattr(cron, "_claim_cron_window", Mock(return_value=True))
    monkeypatch.setattr(cron, "_get_window_shared_run_ids", Mock(return_value=None))
    monkeypatch.setattr(cron, "_set_window_shared_run_ids", Mock())
    monkeypatch.setattr(cron, "_mark_cron_window_completed", Mock())
    monkeypatch.setattr(cron, "_mark_cron_window_failed", Mock())
    monkeypatch.setattr(cron, "get_digest_send_outcome", Mock(return_value=None))
    monkeypatch.setattr(cron, "record_digest_send_outcome", Mock())
    monkeypatch.setattr(cron, "wait_until_digest_send_time", Mock())


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
    cron.wait_until_digest_send_time.assert_called_once()
    cron._mark_cron_window_completed.assert_called_once()
    cron._mark_cron_window_failed.assert_not_called()
    cron._set_window_shared_run_ids.assert_called_once()


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
    cron.record_digest_send_outcome.assert_called_once_with(
        user_id="user-1",
        window_key=cron._cron_window_key(datetime.fromisoformat(payload["started_at"])),
        outcome="sent",
        conn=None,
    )


def test_claim_cron_window_sql_reclaims_failed_or_running_rows():
    assert "status IN ('failed', 'running')" in cron.CLAIM_CRON_WINDOW_SQL
    update_sql = cron.CLAIM_CRON_WINDOW_SQL.split("DO UPDATE", 1)[1]
    set_sql = update_sql.split("WHERE", 1)[0]
    assert "shared_run_ids" not in set_sql


def test_claim_cron_window_returns_true_when_row_returned(monkeypatch):
    monkeypatch.setattr(cron, "_claim_cron_window", _REAL_CLAIM_CRON_WINDOW)
    cursor = MagicMock()
    cursor.fetchone.return_value = ("daily-digest:2026-08-18",)
    lock_conn = MagicMock()
    lock_conn.cursor.return_value.__enter__.return_value = cursor

    claimed = cron._claim_cron_window(
        lock_conn=lock_conn,
        window_key="daily-digest:2026-08-18",
        cron_run_id="11111111-1111-1111-1111-111111111111",
        started_at=datetime(2026, 8, 18, tzinfo=UTC),
    )

    assert claimed is True
    lock_conn.commit.assert_called_once()
    assert "status IN ('failed', 'running')" in cursor.execute.call_args.args[0]


def test_run_daily_digest_skips_users_already_sent_today(monkeypatch):
    monkeypatch.setattr(
        cron,
        "list_users_with_digest_selection",
        Mock(return_value=["user-1", "user-2"]),
    )
    monkeypatch.setattr(
        cron,
        "get_digest_send_outcome",
        Mock(side_effect=["sent", None]),
    )
    monkeypatch.setattr(
        cron,
        "list_digest_selected_profile_ids",
        Mock(return_value=["profile-2"]),
    )
    run_shared = Mock(return_value={"run_ids": ["run-shared"], "embedded_count": 1})
    run_recommendations = Mock()
    deliver_email = Mock(return_value={"status": "sent", "error_message": None})
    monkeypatch.setattr(cron, "list_digest_categories", Mock(return_value=["cs.AI"]))
    monkeypatch.setattr(cron, "run_shared_pipeline_steps", run_shared)
    monkeypatch.setattr(cron, "run_recommendations_for_profiles", run_recommendations)
    monkeypatch.setattr(
        cron,
        "run_description_batch_for_recommendations",
        Mock(return_value={"attempted": 0}),
    )
    monkeypatch.setattr(cron, "deliver_digest_email_for_user", deliver_email)

    payload = cron.run_daily_digest_for_all_users()

    assert payload["users_skipped"] == 1
    assert payload["users_succeeded"] == 1
    assert payload["results"][0]["email_status"] == "skipped_already_sent"
    assert payload["results"][0]["error_message"] == "already sent today"
    run_recommendations.assert_called_once_with(
        user_id="user-2",
        profile_ids=["profile-2"],
        run_ids=["run-shared"],
    )
    deliver_email.assert_called_once()
    cron.record_digest_send_outcome.assert_called_once_with(
        user_id="user-2",
        window_key=cron._cron_window_key(datetime.fromisoformat(payload["started_at"])),
        outcome="sent",
        conn=None,
    )


def test_run_daily_digest_skips_shared_pipeline_when_all_users_already_recorded(
    monkeypatch,
):
    monkeypatch.setattr(
        cron,
        "list_users_with_digest_selection",
        Mock(return_value=["user-1"]),
    )
    monkeypatch.setattr(cron, "get_digest_send_outcome", Mock(return_value="skipped_empty"))
    run_shared = Mock()
    monkeypatch.setattr(cron, "run_shared_pipeline_steps", run_shared)
    monkeypatch.setattr(cron, "run_recommendations_for_profiles", Mock())

    payload = cron.run_daily_digest_for_all_users()

    assert payload["users_skipped"] == 1
    assert payload["results"][0]["error_message"] == "already skipped empty today"
    run_shared.assert_not_called()


def test_run_daily_digest_records_empty_skip(monkeypatch):
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
        Mock(return_value={"run_ids": ["run-shared"], "embedded_count": 0}),
    )
    monkeypatch.setattr(cron, "run_recommendations_for_profiles", Mock())
    monkeypatch.setattr(
        cron,
        "run_description_batch_for_recommendations",
        Mock(return_value={"attempted": 0}),
    )
    monkeypatch.setattr(
        cron,
        "deliver_digest_email_for_user",
        Mock(return_value={"status": "skipped_no_picks", "error_message": None}),
    )

    payload = cron.run_daily_digest_for_all_users()

    assert payload["results"][0]["email_status"] == "skipped_no_picks"
    cron.record_digest_send_outcome.assert_called_once_with(
        user_id="user-1",
        window_key=cron._cron_window_key(datetime.fromisoformat(payload["started_at"])),
        outcome="skipped_empty",
        conn=None,
    )


def test_run_daily_digest_does_not_record_failed_email(monkeypatch):
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
        Mock(return_value={"run_ids": ["run-shared"], "embedded_count": 0}),
    )
    monkeypatch.setattr(cron, "run_recommendations_for_profiles", Mock())
    monkeypatch.setattr(
        cron,
        "run_description_batch_for_recommendations",
        Mock(return_value={"attempted": 0}),
    )
    monkeypatch.setattr(
        cron,
        "deliver_digest_email_for_user",
        Mock(return_value={"status": "failed", "error_message": "smtp timeout"}),
    )

    payload = cron.run_daily_digest_for_all_users()

    assert payload["results"][0]["email_status"] == "failed"
    cron.record_digest_send_outcome.assert_not_called()
    cron._mark_cron_window_failed.assert_called_once()
    cron._mark_cron_window_completed.assert_not_called()


def test_run_daily_digest_does_not_record_unconfigured_email(monkeypatch):
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
        Mock(return_value={"run_ids": ["run-shared"], "embedded_count": 0}),
    )
    monkeypatch.setattr(cron, "run_recommendations_for_profiles", Mock())
    monkeypatch.setattr(
        cron,
        "run_description_batch_for_recommendations",
        Mock(return_value={"attempted": 0}),
    )
    monkeypatch.setattr(
        cron,
        "deliver_digest_email_for_user",
        Mock(return_value={"status": "skipped_unconfigured", "error_message": None}),
    )

    payload = cron.run_daily_digest_for_all_users()

    assert payload["results"][0]["email_status"] == "skipped_unconfigured"
    cron.record_digest_send_outcome.assert_not_called()


def test_get_digest_send_outcome_returns_stored_value(monkeypatch):
    monkeypatch.setattr(cron, "get_digest_send_outcome", _REAL_GET_DIGEST_SEND_OUTCOME)
    cursor = MagicMock()
    cursor.fetchone.return_value = ("sent",)
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor

    @contextmanager
    def fake_scope(conn=None):
        yield connection

    monkeypatch.setattr(cron, "connection_scope", fake_scope)

    assert (
        cron.get_digest_send_outcome(
            user_id="user@example.com",
            window_key="daily-digest:2026-08-18",
        )
        == "sent"
    )


def test_record_digest_send_outcome_inserts_terminal_row(monkeypatch):
    monkeypatch.setattr(
        cron, "record_digest_send_outcome", _REAL_RECORD_DIGEST_SEND_OUTCOME
    )
    cursor = MagicMock()
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor

    @contextmanager
    def fake_scope(conn=None):
        yield connection

    monkeypatch.setattr(cron, "connection_scope", fake_scope)

    cron.record_digest_send_outcome(
        user_id="user@example.com",
        window_key="daily-digest:2026-08-18",
        outcome="skipped_empty",
    )

    assert cursor.execute.call_args.args[0] == cron.INSERT_DIGEST_SEND_OUTCOME_SQL
    assert cursor.execute.call_args.args[1]["outcome"] == "skipped_empty"


def test_record_digest_send_outcome_rejects_non_terminal_values():
    with pytest.raises(ValueError, match="unsupported digest send outcome"):
        _REAL_RECORD_DIGEST_SEND_OUTCOME(
            user_id="user@example.com",
            window_key="daily-digest:2026-08-18",
            outcome="failed",
        )


def test_run_daily_digest_skips_when_production_config_is_unsafe(monkeypatch):
    monkeypatch.setattr(
        cron,
        "validate_runtime_config",
        Mock(side_effect=cron.StartupConfigError("APP_BASE_URL must use https")),
    )
    open_lock = Mock()
    monkeypatch.setattr(cron, "_open_cron_lock_connection", open_lock)

    payload = cron.run_daily_digest_for_all_users()

    assert payload["status"] == "unsafe-config"
    open_lock.assert_not_called()
    cron.wait_until_digest_send_time.assert_not_called()


def test_run_daily_digest_does_not_wait_to_send_when_nobody_succeeded(monkeypatch):
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
        Mock(side_effect=RuntimeError("ingestion failed")),
    )

    payload = cron.run_daily_digest_for_all_users()

    assert payload["users_failed"] == 1
    cron.wait_until_digest_send_time.assert_not_called()


def test_cron_window_key_uses_london_date():
    started_at = datetime(2026, 8, 18, 3, 0, tzinfo=UTC)
    assert cron._cron_window_key(started_at) == "daily-digest:2026-08-18"


def test_run_daily_digest_treats_all_failed_picks_as_user_failure(monkeypatch):
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
        Mock(return_value={"run_ids": ["run-shared"], "embedded_count": 1}),
    )
    monkeypatch.setattr(
        cron,
        "run_recommendations_for_profiles",
        Mock(
            return_value={
                "recommendation_status_by_run_profile": {
                    "run-shared": {"profile-1": {"status": "failed"}}
                }
            }
        ),
    )
    deliver_email = Mock()
    monkeypatch.setattr(cron, "deliver_digest_email_for_user", deliver_email)

    payload = cron.run_daily_digest_for_all_users()

    assert payload["users_failed"] == 1
    assert payload["users_succeeded"] == 0
    deliver_email.assert_not_called()
    cron.wait_until_digest_send_time.assert_not_called()
    cron._mark_cron_window_failed.assert_called_once()
    cron._mark_cron_window_completed.assert_not_called()


def test_run_daily_digest_sends_when_some_topics_succeed(monkeypatch):
    monkeypatch.setattr(
        cron,
        "list_users_with_digest_selection",
        Mock(return_value=["user-1"]),
    )
    monkeypatch.setattr(
        cron,
        "list_digest_selected_profile_ids",
        Mock(return_value=["profile-1", "profile-2"]),
    )
    monkeypatch.setattr(cron, "list_digest_categories", Mock(return_value=["cs.AI"]))
    monkeypatch.setattr(
        cron,
        "run_shared_pipeline_steps",
        Mock(return_value={"run_ids": ["run-shared"], "embedded_count": 1}),
    )
    monkeypatch.setattr(
        cron,
        "run_recommendations_for_profiles",
        Mock(
            return_value={
                "recommendation_status_by_run_profile": {
                    "run-shared": {
                        "profile-1": {"status": "failed"},
                        "profile-2": {"status": "succeeded", "recommendation_count": 3},
                    }
                }
            }
        ),
    )
    monkeypatch.setattr(
        cron,
        "run_description_batch_for_recommendations",
        Mock(return_value={"attempted": 0}),
    )
    deliver_email = Mock(return_value={"status": "sent", "error_message": None})
    monkeypatch.setattr(cron, "deliver_digest_email_for_user", deliver_email)

    payload = cron.run_daily_digest_for_all_users()

    assert payload["users_succeeded"] == 1
    deliver_email.assert_called_once()
    cron.wait_until_digest_send_time.assert_called_once()
    cron._mark_cron_window_completed.assert_called_once()


def test_run_daily_digest_reuses_stored_run_ids_on_leftover_day(monkeypatch):
    monkeypatch.setattr(
        cron,
        "_get_window_shared_run_ids",
        Mock(return_value=["run-from-crash"]),
    )
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
    run_shared = Mock(return_value={"run_ids": ["run-from-crash"], "embedded_count": 0})
    monkeypatch.setattr(cron, "run_shared_pipeline_steps", run_shared)
    monkeypatch.setattr(cron, "run_recommendations_for_profiles", Mock())
    monkeypatch.setattr(
        cron,
        "run_description_batch_for_recommendations",
        Mock(return_value={"attempted": 0}),
    )
    deliver_email = Mock(return_value={"status": "sent", "error_message": None})
    monkeypatch.setattr(cron, "deliver_digest_email_for_user", deliver_email)

    payload = cron.run_daily_digest_for_all_users()

    run_shared.assert_called_once_with(
        categories=["cs.AI"],
        max_results=150,
        embedding_limit=600,
        existing_run_ids=["run-from-crash"],
    )
    cron._set_window_shared_run_ids.assert_not_called()
    deliver_email.assert_called_once()
    assert payload["results"][0]["run_ids"] == ["run-from-crash"]
    cron._mark_cron_window_completed.assert_called_once()


def test_digest_window_still_owed_when_email_or_picks_fail():
    users = [("user-1", ["profile-1"])]
    assert cron._digest_window_still_owed(
        users_to_process=users,
        results=[{"user_id": "user-1", "status": "failed"}],
    )
    assert cron._digest_window_still_owed(
        users_to_process=users,
        results=[
            {
                "user_id": "user-1",
                "status": "succeeded",
                "email_status": "failed",
            }
        ],
    )
    assert not cron._digest_window_still_owed(
        users_to_process=users,
        results=[
            {
                "user_id": "user-1",
                "status": "succeeded",
                "email_status": "sent",
            }
        ],
    )
    assert not cron._digest_window_still_owed(users_to_process=[], results=[])


def test_load_monitor_state_resets_corrupt_file(tmp_path, caplog):
    path = tmp_path / "monitor-state.json"
    path.write_text("{not-json", encoding="utf-8")

    with caplog.at_level("WARNING"):
        state = cron._load_monitor_state()

    assert state["zero_output_streak"] == 0
    assert state["alert_last_sent_at"] == {}
    assert "Monitor state file was unreadable" in caplog.text


