"""
Tests user profile helpers
"""

from unittest.mock import MagicMock, Mock

import pytest

from core import profiles
from core.profiles import ProfileRow


def _mock_connection_with_cursor(cursor):
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor

    connect = MagicMock()
    connect.return_value.__enter__.return_value = connection
    return connect


def test_pick_next_available_slot_returns_first_gap():
    assert profiles._pick_next_available_slot({1, 3}) == 2


def test_pick_next_available_slot_raises_when_cap_is_reached():
    with pytest.raises(ValueError, match="profile cap"):
        profiles._pick_next_available_slot({1, 2, 3})


def test_validate_interest_sentence_rejects_blank():
    with pytest.raises(ValueError, match="interest_sentence must not be empty"):
        profiles._validate_interest_sentence("   ")


def test_validate_category_rejects_non_configured_values(monkeypatch):
    monkeypatch.setattr(profiles, "get_arxiv_categories", Mock(return_value=["cs.AI"]))

    with pytest.raises(ValueError, match="configured ARXIV_CATEGORIES"):
        profiles._validate_category("cs.CL")


def test_create_profile_inserts_with_next_slot(monkeypatch):
    monkeypatch.setattr(profiles.uuid, "uuid4", Mock(return_value="profile-123"))
    monkeypatch.setattr(profiles, "get_arxiv_categories", Mock(return_value=["cs.AI"]))

    cursor = MagicMock()
    cursor.fetchall.return_value = [(1,)]  # choose slot 2 if slot 1 is taken
    monkeypatch.setattr(
        profiles.psycopg, "connect", _mock_connection_with_cursor(cursor)
    )

    profile_id = profiles.create_profile(
        user_id="user-1",
        category="cs.AI",
        interest_sentence="Language model planning",
    )

    assert profile_id == "profile-123"
    assert cursor.execute.call_count == 2

    insert_params = cursor.execute.call_args_list[1].args[1]
    assert insert_params == (
        "profile-123",
        "user-1",
        2,
        "Profile 2",
        "cs.AI",
        "Language model planning",
    )


def test_create_profile_raises_when_user_has_three_profiles(monkeypatch):
    monkeypatch.setattr(profiles, "get_arxiv_categories", Mock(return_value=["cs.AI"]))

    cursor = MagicMock()
    cursor.fetchall.return_value = [(1,), (2,), (3,)]
    monkeypatch.setattr(
        profiles.psycopg, "connect", _mock_connection_with_cursor(cursor)
    )

    with pytest.raises(ValueError, match="3-profile cap"):
        profiles.create_profile(
            user_id="user-1", category="cs.AI", interest_sentence="test"
        )


def test_list_profiles_maps_rows_to_dicts(monkeypatch):
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        (
            "p-1",
            "user-1",
            1,
            "Systems",
            "cs.AI",
            "Interest A",
            "2026-01-01T00:00:00Z",
            True,
        ),
        (
            "p-2",
            "user-1",
            2,
            "Robustness",
            "cs.CL",
            "Interest B",
            "2026-01-02T00:00:00Z",
            False,
        ),
    ]
    monkeypatch.setattr(
        profiles.psycopg, "connect", _mock_connection_with_cursor(cursor)
    )

    results = profiles.list_profiles(user_id="user-1")

    assert [item.profile_id for item in results] == ["p-1", "p-2"]
    assert results[0].profile_slot == 1
    assert results[1].category == "cs.CL"
    assert results[0].profile_name == "Systems"
    assert results[0].digest_enabled is True
    assert results[1].digest_enabled is False


def test_get_profile_returns_none_when_not_found(monkeypatch):
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    monkeypatch.setattr(
        profiles.psycopg, "connect", _mock_connection_with_cursor(cursor)
    )

    assert profiles.get_profile("missing") is None


def test_resolve_profile_id_returns_uuid_string():
    assert profiles.resolve_profile_id(user_id="user-1", profile_id="p-99") == "p-99"


def test_resolve_profile_id_requires_value():
    with pytest.raises(ValueError, match="profile_id is required"):
        profiles.resolve_profile_id(user_id="user-1", profile_id=None)

    with pytest.raises(ValueError, match="profile_id is required"):
        profiles.resolve_profile_id(user_id="user-1", profile_id="")


def test_add_profile_keyword_inserts_normalized_value(monkeypatch):
    cursor = MagicMock()
    cursor.fetchone.side_effect = [
        (1,),  # profile ownership exists
        (0,),  # current count
        ("kv cache",),  # inserted
    ]
    cursor.fetchall.return_value = [("encoder transformers",), ("kv cache",)]
    monkeypatch.setattr(
        profiles.psycopg, "connect", _mock_connection_with_cursor(cursor)
    )

    keywords = profiles.add_profile_keyword(
        profile_id="profile-1",
        user_id="user-1",
        keyword="  KV Cache  ",
    )

    insert_params = cursor.execute.call_args_list[2].args[1]
    assert insert_params == ("profile-1", "kv cache")
    assert keywords == ["encoder transformers", "kv cache"]


def test_add_profile_keyword_enforces_cap(monkeypatch):
    cursor = MagicMock()
    cursor.fetchone.side_effect = [
        (1,),  # profile ownership exists
        (20,),  # current count
        ("new keyword",),  # inserted (but should rollback with error)
    ]
    monkeypatch.setattr(
        profiles.psycopg, "connect", _mock_connection_with_cursor(cursor)
    )

    with pytest.raises(ValueError, match="cap reached"):
        profiles.add_profile_keyword(
            profile_id="profile-1",
            user_id="user-1",
            keyword="new keyword",
        )


def test_remove_profile_keyword_returns_remaining_list(monkeypatch):
    cursor = MagicMock()
    cursor.fetchone.return_value = (1,)
    cursor.fetchall.return_value = [("encoder transformers",)]
    monkeypatch.setattr(
        profiles.psycopg, "connect", _mock_connection_with_cursor(cursor)
    )

    keywords = profiles.remove_profile_keyword(
        profile_id="profile-1",
        user_id="user-1",
        keyword="KV Cache",
    )

    delete_params = cursor.execute.call_args_list[1].args[1]
    assert delete_params == ("profile-1", "kv cache")
    assert keywords == ["encoder transformers"]


def test_list_digest_selected_profile_ids_returns_slot_order(monkeypatch):
    cursor = MagicMock()
    cursor.fetchall.return_value = [("p-2",), ("p-3",)]
    monkeypatch.setattr(
        profiles.psycopg, "connect", _mock_connection_with_cursor(cursor)
    )

    selected = profiles.list_digest_selected_profile_ids(user_id="user-1")

    assert selected == ["p-2", "p-3"]


def test_set_digest_profile_selection_allows_empty_list(monkeypatch):
    cursor = MagicMock()
    monkeypatch.setattr(
        profiles.psycopg, "connect", _mock_connection_with_cursor(cursor)
    )

    selected = profiles.set_digest_profile_selection(profile_ids=[], user_id="user-1")
    assert selected == []


def test_set_digest_profile_selection_updates_selected_profiles(monkeypatch):
    cursor = MagicMock()
    cursor.fetchall.side_effect = [
        [("p-1",), ("p-3",)],  # ownership validation
        [("p-1",), ("p-3",)],  # selected after update
    ]
    monkeypatch.setattr(
        profiles.psycopg, "connect", _mock_connection_with_cursor(cursor)
    )

    selected = profiles.set_digest_profile_selection(
        profile_ids=["p-1", "p-3", "p-1"],
        user_id="user-1",
    )

    assert selected == ["p-1", "p-3"]
    ownership_params = cursor.execute.call_args_list[0].args[1]
    assert ownership_params == ("user-1", ["p-1", "p-3"])


def test_set_digest_profile_selection_rejects_non_owned_profiles(monkeypatch):
    cursor = MagicMock()
    cursor.fetchall.return_value = [("p-1",)]
    monkeypatch.setattr(
        profiles.psycopg, "connect", _mock_connection_with_cursor(cursor)
    )

    with pytest.raises(ValueError, match="do not belong"):
        profiles.set_digest_profile_selection(
            profile_ids=["p-1", "p-2"],
            user_id="user-1",
        )


def test_update_profile_updates_name_category_and_digest(monkeypatch):
    monkeypatch.setattr(profiles, "get_arxiv_categories", Mock(return_value=["cs.AI", "cs.CL"]))
    existing = ProfileRow(
        profile_id="p-1",
        user_id="user-1",
        profile_slot=1,
        profile_name="Old",
        category="cs.AI",
        interest_sentence="Interest",
        created_at=None,
        digest_enabled=True,
    )
    updated = ProfileRow(
        profile_id="p-1",
        user_id="user-1",
        profile_slot=1,
        profile_name="New Name",
        category="cs.CL",
        interest_sentence="Interest",
        created_at=None,
        digest_enabled=False,
    )
    monkeypatch.setattr(profiles, "get_profile", Mock(side_effect=[existing, updated]))

    cursor = MagicMock()
    monkeypatch.setattr(
        profiles.psycopg, "connect", _mock_connection_with_cursor(cursor)
    )

    result = profiles.update_profile(
        profile_id="p-1",
        user_id="user-1",
        profile_name="New Name",
        category="cs.CL",
        digest_enabled=False,
    )

    assert result.profile_name == "New Name"
    assert cursor.execute.call_args_list[0].args[1] == (
        "New Name",
        "cs.CL",
        False,
        "p-1",
        "user-1",
    )


def test_delete_profile_returns_false_when_missing(monkeypatch):
    cursor = MagicMock()
    cursor.rowcount = 0
    monkeypatch.setattr(
        profiles.psycopg, "connect", _mock_connection_with_cursor(cursor)
    )
    assert profiles.delete_profile(profile_id="missing", user_id="user-1") is False
