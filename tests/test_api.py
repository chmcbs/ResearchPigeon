"""
Tests FastAPI service helpers
"""

from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

import api.dependencies as dependencies
from api.queries.daily_picks import DailyPickRow
from api.queries.metrics import LatestRunRow, MetricsRowSet
from api.schemas import (
    FeedbackRequest,
    GenerateDailyPicksRequest,
    ManageProfileKeywordRequest,
    UpdateDigestSelectionRequest,
)
from api.services.daily_picks import (
    generate_daily_picks_payload,
    get_daily_picks_payload,
    get_debug_daily_picks_payload,
)
from api.services.feedback import save_feedback_payload
from api.services.errors import BadRequestError, InternalServerError
from api.services.metrics import get_metrics_payload
from api.services.profiles import (
    add_profile_keyword_payload,
    remove_profile_keyword_payload,
    update_digest_selection_payload,
)


def _pick_row(rank=1):
    return DailyPickRow(
        rank=rank,
        arxiv_id=f"2601.0000{rank}",
        title=f"Paper {rank}",
        abstract=f"Abstract {rank}",
        pdf_url=f"https://arxiv.org/pdf/2601.0000{rank}",
        run_id="run-123",
        category="cs.AI",
        generated_at=datetime(2026, 1, 2, 9, 30, tzinfo=timezone.utc),
        base_dense_score=0.75,
        keyword_boost=0.15,
        final_score=0.9,
        candidate_window="run",
        fallback_stage=0,
    )


def test_get_daily_picks_returns_empty_state():
    payload = get_daily_picks_payload(
        user_id="default",
        profile_id=None,
        resolve_profile=Mock(
            return_value={
                "profile_id": "profile-1",
                "profile_slot": 1,
                "category": "cs.AI",
                "interest_sentence": "Efficient LLM systems",
            }
        ),
        list_digest_selected_profile_ids=Mock(return_value=["profile-1"]),
        fetch_latest_picks=Mock(return_value=[]),
    )

    assert payload == {
        "user_id": "default",
        "profile_id": "profile-1",
        "needs_generation": True,
        "picks": [],
        "sections": [
            {
                "profile_id": "profile-1",
                "profile_slot": 1,
                "category": "cs.AI",
                "interest_sentence": "Efficient LLM systems",
                "needs_generation": True,
                "picks": [],
            }
        ],
    }


def test_get_daily_picks_returns_public_fields():
    payload = get_daily_picks_payload(
        user_id="default",
        profile_id=None,
        resolve_profile=Mock(
            return_value={
                "profile_id": "profile-1",
                "profile_slot": 1,
                "category": "cs.AI",
                "interest_sentence": "Efficient LLM systems",
            }
        ),
        list_digest_selected_profile_ids=Mock(return_value=["profile-1"]),
        fetch_latest_picks=Mock(return_value=[_pick_row()]),
    )

    assert payload["needs_generation"] is False
    assert payload["picks"] == [
        {
            "rank": 1,
            "arxiv_id": "2601.00001",
            "title": "Paper 1",
            "abstract": "Abstract 1",
            "pdf_url": "https://arxiv.org/pdf/2601.00001",
            "final_score": 0.9,
        }
    ]
    assert payload["sections"][0]["profile_id"] == "profile-1"
    assert payload["sections"][0]["category"] == "cs.AI"


def test_get_daily_picks_returns_multi_profile_sections():
    resolve_profile = Mock(
        side_effect=[
            {
                "profile_id": "profile-1",
                "profile_slot": 1,
                "category": "cs.AI",
                "interest_sentence": "Efficient LLM systems",
            },
            {
                "profile_id": "profile-2",
                "profile_slot": 2,
                "category": "cs.CL",
                "interest_sentence": "Robust NLP evaluation",
            },
        ]
    )
    fetch_latest_picks = Mock(side_effect=[[_pick_row(rank=1)], []])
    payload = get_daily_picks_payload(
        user_id="default",
        profile_id=None,
        resolve_profile=resolve_profile,
        list_digest_selected_profile_ids=Mock(return_value=["profile-1", "profile-2"]),
        fetch_latest_picks=fetch_latest_picks,
    )

    assert payload["profile_id"] == "profile-1"
    assert payload["needs_generation"] is True
    assert payload["picks"][0]["arxiv_id"] == "2601.00001"
    assert [section["profile_id"] for section in payload["sections"]] == [
        "profile-1",
        "profile-2",
    ]
    assert payload["sections"][1]["needs_generation"] is True
    assert payload["sections"][1]["picks"] == []


def test_get_daily_picks_anchored_run_ids_treat_empty_as_generated():
    payload = get_daily_picks_payload(
        user_id="default",
        profile_id=None,
        anchored_run_ids=["run-123"],
        resolve_profile=Mock(
            return_value={
                "profile_id": "profile-1",
                "profile_slot": 1,
                "category": "cs.AI",
                "interest_sentence": "Efficient LLM systems",
            }
        ),
        list_digest_selected_profile_ids=Mock(return_value=["profile-1"]),
        fetch_latest_picks=Mock(return_value=[]),
    )

    assert payload["needs_generation"] is False
    assert payload["sections"][0]["needs_generation"] is False
    assert payload["sections"][0]["picks"] == []


def test_get_debug_daily_picks_includes_ranking_metadata():
    payload = get_debug_daily_picks_payload(
        user_id="default",
        profile_id="profile-1",
        resolve_profile=Mock(return_value={"profile_id": "profile-1"}),
        fetch_latest_picks=Mock(return_value=[_pick_row()]),
    )

    assert payload["run_id"] == "run-123"
    assert payload["category"] == "cs.AI"
    assert payload["picks"][0]["final_score"] == 0.9
    assert payload["picks"][0]["base_dense_score"] == 0.75
    assert payload["picks"][0]["keyword_boost"] == 0.15
    assert payload["picks"][0]["candidate_window"] == "run"
    assert payload["picks"][0]["fallback_stage"] == 0


def test_generate_daily_picks_runs_pipeline_and_returns_picks():
    run_pipeline = Mock(
        return_value={
            "run_ids": ["run-123"],
            "embedded_count": 5,
            "recommendations_by_run_profile": {
                "run-123": {
                    "profile-1": [{"rank": 1}],
                    "profile-2": [{"rank": 2}],
                }
            },
            "recommendation_status_by_run_profile": {
                "run-123": {
                    "profile-1": {
                        "status": "succeeded",
                        "recommendation_count": 1,
                        "error_message": None,
                    },
                    "profile-2": {
                        "status": "succeeded",
                        "recommendation_count": 1,
                        "error_message": None,
                    },
                }
            },
        }
    )
    get_daily_picks = Mock(
        return_value={
            "user_id": "default",
            "profile_id": "profile-1",
            "needs_generation": False,
            "picks": [{"rank": 1, "arxiv_id": "2601.00001"}],
            "sections": [
                {
                    "profile_id": "profile-1",
                    "profile_slot": 1,
                    "category": "cs.AI",
                    "interest_sentence": "Efficient LLM systems",
                    "needs_generation": False,
                    "picks": [{"rank": 1, "arxiv_id": "2601.00001"}],
                },
                {
                    "profile_id": "profile-2",
                    "profile_slot": 2,
                    "category": "cs.CL",
                    "interest_sentence": "Robust NLP evaluation",
                    "needs_generation": False,
                    "picks": [{"rank": 1, "arxiv_id": "2601.00002"}],
                },
            ],
        }
    )

    payload = generate_daily_picks_payload(
        GenerateDailyPicksRequest(
            profile_ids=["profile-1", "profile-2"],
            max_results=123,
            embedding_limit=456,
        ),
        user_id="default",
        resolve_profile=Mock(
            side_effect=lambda user_id, profile_id: {"profile_id": profile_id}
        ),
        run_pipeline=run_pipeline,
        get_daily_picks_payload=get_daily_picks,
    )

    run_pipeline.assert_called_once_with(
        user_id="default",
        profile_ids=["profile-1", "profile-2"],
        max_results=123,
        embedding_limit=456,
    )
    get_daily_picks.assert_called_once_with(
        user_id="default",
        profile_id=None,
        run_ids=["run-123"],
    )
    assert payload["primary_profile_id"] == "profile-1"
    assert payload["requested_profile_ids"] == ["profile-1", "profile-2"]
    assert payload["run_ids"] == ["run-123"]
    assert payload["embedded_count"] == 5
    assert payload["has_failures"] is False
    assert payload["generation_runs"] == [
        {
            "run_id": "run-123",
            "profile_statuses": [
                {
                    "profile_id": "profile-1",
                    "status": "succeeded",
                    "recommendation_count": 1,
                    "error_message": None,
                },
                {
                    "profile_id": "profile-2",
                    "status": "succeeded",
                    "recommendation_count": 1,
                    "error_message": None,
                },
            ],
        }
    ]
    assert payload["picks"] == [{"rank": 1, "arxiv_id": "2601.00001"}]
    assert len(payload["sections"]) == 2


def test_generate_daily_picks_allows_zero_recommendations_when_generation_succeeds():
    payload = generate_daily_picks_payload(
        GenerateDailyPicksRequest(
            profile_ids=["profile-1"],
            max_results=123,
            embedding_limit=456,
        ),
        user_id="default",
        resolve_profile=Mock(return_value={"profile_id": "profile-1"}),
        run_pipeline=Mock(
            return_value={
                "run_ids": ["run-123"],
                "embedded_count": 5,
                "recommendations_by_run_profile": {"run-123": {"profile-1": []}},
                "recommendation_status_by_run_profile": {
                    "run-123": {
                        "profile-1": {
                            "status": "succeeded",
                            "recommendation_count": 0,
                            "error_message": None,
                        }
                    }
                },
            }
        ),
        get_daily_picks_payload=Mock(
            return_value={
                "user_id": "default",
                "profile_id": "profile-1",
                "needs_generation": False,
                "picks": [],
                "sections": [
                    {
                        "profile_id": "profile-1",
                        "profile_slot": 1,
                        "category": "cs.AI",
                        "interest_sentence": "Efficient LLM systems",
                        "needs_generation": False,
                        "picks": [],
                    }
                ],
            }
        ),
    )

    assert payload["has_failures"] is False
    assert payload["generation_runs"][0]["profile_statuses"][0]["status"] == "succeeded"
    assert (
        payload["generation_runs"][0]["profile_statuses"][0]["recommendation_count"]
        == 0
    )
    assert payload["picks"] == []


def test_generate_daily_picks_fails_when_all_targets_fail():
    with pytest.raises(InternalServerError) as error:
        generate_daily_picks_payload(
            GenerateDailyPicksRequest(profile_ids=["profile-1"]),
            user_id="default",
            resolve_profile=Mock(return_value={"profile_id": "profile-1"}),
            run_pipeline=Mock(
                return_value={
                    "run_ids": ["run-123"],
                    "embedded_count": 5,
                    "recommendations_by_run_profile": {"run-123": {"profile-1": []}},
                    "recommendation_status_by_run_profile": {
                        "run-123": {
                            "profile-1": {
                                "status": "failed",
                                "recommendation_count": 0,
                                "error_message": "boom",
                            }
                        }
                    },
                }
            ),
            get_daily_picks_payload=Mock(
                return_value={
                    "user_id": "default",
                    "profile_id": "profile-1",
                    "needs_generation": False,
                    "picks": [],
                    "sections": [],
                }
            ),
        )

    assert "NO_SUCCESSFUL_GENERATION" in str(error.value)


def test_generate_daily_picks_request_requires_profile_ids():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        GenerateDailyPicksRequest(profile_ids=[])


def test_save_feedback_payload_updates_preferences():
    save_feedback = Mock(return_value="feedback-123")
    update_preference_embedding = Mock()
    payload = save_feedback_payload(
        FeedbackRequest(
            profile_id="profile-1",
            arxiv_id="2601.00001",
            label="like",
        ),
        user_id="default",
        resolve_profile=Mock(return_value={"profile_id": "profile-1"}),
        save_feedback=save_feedback,
        update_preference_embedding=update_preference_embedding,
    )

    save_feedback.assert_called_once_with(
        arxiv_id="2601.00001",
        label="like",
        user_id="default",
        profile_id="profile-1",
    )
    update_preference_embedding.assert_called_once_with(
        user_id="default",
        profile_id="profile-1",
    )
    assert payload == {
        "feedback_id": "feedback-123",
        "user_id": "default",
        "profile_id": "profile-1",
        "arxiv_id": "2601.00001",
        "label": "like",
        "preference_updated": True,
    }


def test_add_profile_keyword_payload_maps_response():
    add_profile_keyword = Mock(return_value=["encoder transformers", "kv cache"])
    payload = add_profile_keyword_payload(
        profile_id="profile-1",
        request=ManageProfileKeywordRequest(
            keyword="KV Cache",
        ),
        user_id="default",
        add_profile_keyword=add_profile_keyword,
    )

    add_profile_keyword.assert_called_once_with(
        profile_id="profile-1",
        user_id="default",
        keyword="KV Cache",
    )
    assert payload == {
        "user_id": "default",
        "profile_id": "profile-1",
        "keywords": ["encoder transformers", "kv cache"],
    }


def test_remove_profile_keyword_payload_maps_response():
    remove_profile_keyword = Mock(return_value=["encoder transformers"])
    payload = remove_profile_keyword_payload(
        profile_id="profile-1",
        request=ManageProfileKeywordRequest(
            keyword="KV Cache",
        ),
        user_id="default",
        remove_profile_keyword=remove_profile_keyword,
    )

    remove_profile_keyword.assert_called_once_with(
        profile_id="profile-1",
        user_id="default",
        keyword="KV Cache",
    )
    assert payload == {
        "user_id": "default",
        "profile_id": "profile-1",
        "keywords": ["encoder transformers"],
    }


def test_update_digest_selection_payload_maps_response():
    set_digest_profile_selection = Mock(return_value=["profile-2", "profile-3"])
    payload = update_digest_selection_payload(
        UpdateDigestSelectionRequest(
            profile_ids=["profile-2", "profile-3"],
        ),
        user_id="default",
        set_digest_profile_selection=set_digest_profile_selection,
    )

    set_digest_profile_selection.assert_called_once_with(
        profile_ids=["profile-2", "profile-3"],
        user_id="default",
    )
    assert payload == {
        "user_id": "default",
        "selected_profile_ids": ["profile-2", "profile-3"],
    }


def test_get_metrics_payload_returns_run_and_recommendation_counts():
    metrics_rows = MetricsRowSet(
        run_status_counts={"completed": 2, "failed": 1},
        latest_runs=[
            LatestRunRow(
                run_id="run-123",
                status="completed",
                category="cs.AI",
                max_results=150,
                fetched_count=100,
                saved_count=100,
                started_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                finished_at=datetime(2026, 1, 2, 1, tzinfo=timezone.utc),
                error_message=None,
            )
        ],
        total_recommendations=3,
        recommendations_by_profile={"profile-1": 3},
    )
    payload = get_metrics_payload(
        latest_runs_limit=5,
        fetch_metrics_rows=Mock(return_value=metrics_rows),
    )

    assert payload["run_status_counts"] == {"completed": 2, "failed": 1}
    assert payload["latest_runs"][0]["run_id"] == "run-123"
    assert payload["total_recommendations"] == 3
    assert payload["recommendations_by_profile"] == {"profile-1": 3}


def test_dependencies_get_daily_picks_reuses_single_connection(monkeypatch):
    sentinel_conn = object()
    sentinel_uow = type("Uow", (), {"conn": sentinel_conn, "generated_run_ids": []})()
    seen = {}

    @contextmanager
    def fake_uow(uow=None, conn=None):
        assert uow is None
        assert conn is None
        yield sentinel_uow

    def fake_service(**kwargs):
        kwargs["resolve_profile"]("default", "profile-1")
        kwargs["list_digest_selected_profile_ids"]("default")
        kwargs["fetch_latest_picks"]("profile-1")
        return {"ok": True}

    monkeypatch.setattr(dependencies, "open_api_unit_of_work", fake_uow)
    monkeypatch.setattr(dependencies, "get_daily_picks_payload_service", fake_service)
    monkeypatch.setattr(
        dependencies,
        "_resolve_profile",
        lambda user_id, profile_id, conn=None: seen.setdefault("resolve_conn", conn)
        or {},
    )
    monkeypatch.setattr(
        dependencies,
        "list_digest_selected_profile_ids",
        lambda user_id, conn=None: seen.setdefault("list_conn", conn) or [],
    )
    monkeypatch.setattr(
        dependencies,
        "_fetch_latest_picks",
        lambda profile_id, run_ids=None, conn=None: seen.setdefault("picks_conn", conn)
        or [],
    )

    payload = dependencies.get_daily_picks_payload(
        user_id="default", profile_id="profile-1"
    )

    assert payload == {"ok": True}
    assert seen["resolve_conn"] is sentinel_conn
    assert seen["list_conn"] is sentinel_conn
    assert seen["picks_conn"] is sentinel_conn


def test_dependencies_get_daily_picks_passes_run_ids_to_pick_lookup(monkeypatch):
    sentinel_conn = object()
    sentinel_uow = type("Uow", (), {"conn": sentinel_conn, "generated_run_ids": []})()
    seen = {}

    @contextmanager
    def fake_uow(uow=None, conn=None):
        assert uow is None
        assert conn is None
        yield sentinel_uow

    def fake_service(**kwargs):
        kwargs["fetch_latest_picks"]("profile-1")
        return {"ok": True}

    monkeypatch.setattr(dependencies, "open_api_unit_of_work", fake_uow)
    monkeypatch.setattr(dependencies, "get_daily_picks_payload_service", fake_service)
    monkeypatch.setattr(
        dependencies,
        "_resolve_profile",
        lambda user_id, profile_id, conn=None: {},
    )
    monkeypatch.setattr(
        dependencies,
        "list_digest_selected_profile_ids",
        lambda user_id, conn=None: [],
    )
    monkeypatch.setattr(
        dependencies,
        "_fetch_latest_picks",
        lambda profile_id, run_ids=None, conn=None: seen.setdefault(
            "call",
            {"profile_id": profile_id, "run_ids": run_ids, "conn": conn},
        )
        or [],
    )

    payload = dependencies.get_daily_picks_payload(
        user_id="default",
        profile_id="profile-1",
        run_ids=["run-1", "run-2"],
    )

    assert payload == {"ok": True}
    assert seen["call"] == {
        "profile_id": "profile-1",
        "run_ids": ["run-1", "run-2"],
        "conn": sentinel_conn,
    }


def test_dependencies_generate_daily_picks_maps_internal_failures_to_http_500(
    monkeypatch,
):
    sentinel_conn = object()
    sentinel_uow = type("Uow", (), {"conn": sentinel_conn, "generated_run_ids": []})()

    @contextmanager
    def fake_uow(uow=None, conn=None):
        assert uow is None
        assert conn is None
        yield sentinel_uow

    monkeypatch.setattr(dependencies, "open_api_unit_of_work", fake_uow)
    monkeypatch.setattr(
        dependencies,
        "generate_daily_picks_payload_service",
        Mock(side_effect=InternalServerError("NO_SUCCESSFUL_GENERATION: failed")),
    )

    with pytest.raises(HTTPException) as error:
        dependencies.generate_daily_picks_payload(
            GenerateDailyPicksRequest(profile_ids=["profile-1"]),
            user_id="default",
        )

    assert error.value.status_code == 500
    assert "NO_SUCCESSFUL_GENERATION" in error.value.detail
