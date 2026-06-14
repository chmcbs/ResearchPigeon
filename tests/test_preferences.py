"""
Tests preference embedding and feedback handling
"""

from unittest.mock import MagicMock, Mock

import pytest

from core import preferences


def test_mean_vector_averages_vectors():
    assert preferences.mean_vector(
        [
            [1.0, 2.0, 3.0],
            [3.0, 4.0, 5.0],
        ]
    ) == [2.0, 3.0, 4.0]


def test_mean_vector_returns_empty_for_no_vectors():
    assert preferences.mean_vector([]) == []


def test_blend_vectors_combines_initial_and_feedback_by_alpha():
    blended = preferences.blend_vectors(
        initial_vector=[1.0, 1.0],
        feedback_vector=[3.0, 5.0],
        alpha=0.25,
    )

    assert blended == [2.5, 4.0]


def test_feedback_alpha_decays_as_feedback_count_increases():
    assert preferences.feedback_alpha(0) == 1.0
    assert preferences.feedback_alpha(1) == 0.5
    assert preferences.feedback_alpha(3) == 0.25


def test_normalize_vector_scales_vector_to_unit_length():
    normalized = preferences.normalize_vector([3.0, 4.0])

    assert normalized == [0.6, 0.8]


def test_normalize_vector_returns_zero_vector_unchanged():
    assert preferences.normalize_vector([0.0, 0.0]) == [0.0, 0.0]


def test_compute_preference_vector_uses_liked_mean_when_no_dislikes():
    preference = preferences.compute_preference_vector(
        liked_vectors=[
            [1.0, 2.0],
            [3.0, 4.0],
        ],
        disliked_vectors=[],
    )

    assert preference == [2.0, 3.0]


def test_compute_preference_vector_subtracts_disliked_mean():
    preference = preferences.compute_preference_vector(
        liked_vectors=[
            [1.0, 2.0],
            [3.0, 4.0],
        ],
        disliked_vectors=[
            [0.5, 1.0],
            [1.5, 3.0],
        ],
        dislike_weight=0.5,
    )

    assert preference == [1.5, 2.0]


def test_compute_preference_vector_requires_liked_vector():
    with pytest.raises(ValueError, match="At least one liked paper"):
        preferences.compute_preference_vector([], [[1.0, 2.0]])


def test_save_feedback_rejects_invalid_label():
    with pytest.raises(ValueError, match="label must be 'like' or 'dislike'"):
        preferences.save_feedback(
            "2401.12345",
            "maybe",
            user_id="default",
            profile_id="profile-1",
        )


def test_save_feedback_upserts_database_row(monkeypatch):
    monkeypatch.setattr(preferences.uuid, "uuid4", Mock(return_value="feedback-123"))

    cursor = MagicMock()
    cursor.fetchone.side_effect = [(1,), ("feedback-123",)]
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor

    connect = MagicMock()
    connect.return_value.__enter__.return_value = connection
    monkeypatch.setattr(preferences.psycopg, "connect", connect)

    feedback_id = preferences.save_feedback(
        arxiv_id="2401.12345",
        label="like",
        user_id="default",
        profile_id="profile-1",
    )

    assert feedback_id == "feedback-123"
    assert cursor.execute.call_count == 2
    query = cursor.execute.call_args_list[1].args[0]
    params = cursor.execute.call_args_list[1].args[1]
    assert "ON CONFLICT (profile_id, arxiv_id)" in query
    assert "RETURNING feedback_id" in query
    assert params == ("feedback-123", "profile-1", "2401.12345", "like")


def test_initialize_preference_embedding_embeds_and_saves_interest_text(monkeypatch):
    monkeypatch.setattr(preferences, "embed_texts", Mock(return_value=[[0.1, 0.2]]))

    cursor = MagicMock()
    cursor.fetchone.return_value = (1,)

    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor

    connect = MagicMock()
    connect.return_value.__enter__.return_value = connection
    monkeypatch.setattr(preferences.psycopg, "connect", connect)

    preferences.initialize_preference_embedding(
        interest_text="language agents",
        user_id="default",
        profile_id="profile-1",
    )

    preferences.embed_texts.assert_called_once_with(["language agents"])
    assert cursor.execute.call_count == 2
    params = cursor.execute.call_args_list[1].args[1]
    assert params == ("profile-1", "[0.1,0.2]", "[0.1,0.2]")


def test_update_preference_embedding_computes_and_saves_from_feedback(monkeypatch):
    cursor = MagicMock()
    cursor.fetchone.return_value = (1,)
    cursor.fetchall.return_value = [
        ([1.0, 1.0], [1.0, 2.0], "like"),
        ([1.0, 1.0], [3.0, 4.0], "like"),
        ([1.0, 1.0], [0.5, 1.0], "dislike"),
    ]

    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor

    connect = MagicMock()
    connect.return_value.__enter__.return_value = connection
    monkeypatch.setattr(preferences.psycopg, "connect", connect)

    preferences.update_preference_embedding(user_id="default", profile_id="profile-1")

    assert cursor.execute.call_count == 3

    fetch_params = cursor.execute.call_args_list[1].args[1]
    save_params = cursor.execute.call_args_list[2].args[1]

    assert fetch_params == ("profile-1",)
    assert save_params[1] == "profile-1"
    assert save_params[0].startswith("[")
    assert save_params[0].endswith("]")


def test_update_preference_embedding_handles_string_vectors(monkeypatch):
    cursor = MagicMock()
    cursor.fetchone.return_value = (1,)
    cursor.fetchall.return_value = [
        ("[1.0,1.0]", "[1.0,2.0]", "like"),
        ("[1.0,1.0]", "[0.5,1.0]", "dislike"),
    ]

    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor

    connect = MagicMock()
    connect.return_value.__enter__.return_value = connection
    monkeypatch.setattr(preferences.psycopg, "connect", connect)

    preferences.update_preference_embedding(user_id="default", profile_id="profile-1")

    assert cursor.execute.call_count == 3
    save_params = cursor.execute.call_args_list[2].args[1]
    assert save_params[1] == "profile-1"
    assert save_params[0].startswith("[")
    assert save_params[0].endswith("]")
