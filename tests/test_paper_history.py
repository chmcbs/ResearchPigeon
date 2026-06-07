"""
Tests for permanent paper dismissal
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, Mock, call

from core import paper_history
from core.paper_history import (
    DELETE_PROFILE_RECOMMENDATIONS_FOR_PAPER_SQL,
    INSERT_DISMISSED_PAPER_SQL,
)


def _patch_connection_scope(monkeypatch, cursor):
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor

    @contextmanager
    def fake_scope(conn=None):
        yield connection

    monkeypatch.setattr(paper_history, "connection_scope", fake_scope)


def test_dismiss_paper_removes_feedback_recommendations_and_records_dismissal(monkeypatch):
    cursor = MagicMock()
    cursor.rowcount = 2
    monkeypatch.setattr(
        paper_history,
        "require_profile_id",
        Mock(return_value="profile-1"),
    )
    remove_feedback = Mock(return_value=True)
    update_embedding = Mock()
    monkeypatch.setattr(paper_history, "remove_feedback", remove_feedback)
    monkeypatch.setattr(paper_history, "update_preference_embedding", update_embedding)
    _patch_connection_scope(monkeypatch, cursor)

    result = paper_history.dismiss_paper(
        arxiv_id="2401.12345",
        user_id="user-1",
        profile_id="profile-1",
    )

    remove_feedback.assert_called_once_with(
        arxiv_id="2401.12345",
        user_id="user-1",
        profile_id="profile-1",
        conn=None,
    )
    assert cursor.execute.call_args_list == [
        call(DELETE_PROFILE_RECOMMENDATIONS_FOR_PAPER_SQL, ("profile-1", "2401.12345")),
        call(INSERT_DISMISSED_PAPER_SQL, ("profile-1", "2401.12345")),
    ]
    update_embedding.assert_called_once_with(
        user_id="user-1",
        profile_id="profile-1",
        conn=None,
    )
    assert result == {
        "profile_id": "profile-1",
        "arxiv_id": "2401.12345",
        "feedback_removed": True,
        "recommendations_removed": 2,
        "preference_updated": True,
        "dismissed": True,
    }


def test_dismiss_paper_skips_embedding_update_without_feedback(monkeypatch):
    cursor = MagicMock()
    cursor.rowcount = 1
    monkeypatch.setattr(
        paper_history,
        "require_profile_id",
        Mock(return_value="profile-1"),
    )
    remove_feedback = Mock(return_value=False)
    update_embedding = Mock()
    monkeypatch.setattr(paper_history, "remove_feedback", remove_feedback)
    monkeypatch.setattr(paper_history, "update_preference_embedding", update_embedding)
    _patch_connection_scope(monkeypatch, cursor)

    result = paper_history.dismiss_paper(
        arxiv_id="2401.12345",
        user_id="user-1",
        profile_id="profile-1",
    )

    update_embedding.assert_not_called()
    assert result["feedback_removed"] is False
    assert result["preference_updated"] is False
