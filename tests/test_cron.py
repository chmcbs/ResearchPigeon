"""
Tests scheduled digest cron helpers
"""

from unittest.mock import MagicMock, Mock

from core import cron
from core import db as db_module


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
    monkeypatch.setattr(cron, "run_shared_pipeline_steps", run_shared)
    monkeypatch.setattr(cron, "run_recommendations_for_profiles", run_recommendations)

    payload = cron.run_daily_digest_for_all_users()

    assert payload["users_succeeded"] == 2
    run_shared.assert_called_once_with(max_results=150, embedding_limit=600)
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
