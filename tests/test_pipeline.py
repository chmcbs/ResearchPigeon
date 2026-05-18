"""
Tests the full recommendation pipeline
"""

from unittest.mock import Mock

from core import pipeline


def test_run_pipeline_calls_steps_in_order(monkeypatch):
    calls = []

    monkeypatch.setattr(
        pipeline,
        "setup_database",
        Mock(side_effect=lambda: calls.append("setup_database")),
    )
    monkeypatch.setattr(
        pipeline,
        "run_ingestion",
        Mock(
            side_effect=lambda max_results: calls.append(("run_ingestion", max_results))
            or ["run-1", "run-2"]
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "run_embeddings",
        Mock(side_effect=lambda limit: calls.append(("run_embeddings", limit)) or 5),
    )
    monkeypatch.setattr(
        pipeline,
        "generate_recommendations",
        Mock(
            side_effect=lambda run_id, user_id, profile_id: calls.append(
                ("generate_recommendations", run_id, user_id, profile_id)
            )
            or [{"rank": 1}]
        ),
    )

    summary = pipeline.run_pipeline(
        user_id="default",
        profile_id="profile-1",
        max_results=123,
        embedding_limit=456,
    )

    assert calls == [
        "setup_database",
        ("run_ingestion", 123),
        ("run_embeddings", 456),
        ("generate_recommendations", "run-1", "default", "profile-1"),
        ("generate_recommendations", "run-2", "default", "profile-1"),
    ]
    assert summary["run_ids"] == ["run-1", "run-2"]
    assert summary["embedded_count"] == 5
    assert summary["recommendations_by_run"] == {
        "run-1": [{"rank": 1}],
        "run-2": [{"rank": 1}],
    }
    assert summary["recommendation_status_by_run_profile"] == {
        "run-1": {
            "profile-1": {
                "status": "succeeded",
                "recommendation_count": 1,
                "error_message": None,
            }
        },
        "run-2": {
            "profile-1": {
                "status": "succeeded",
                "recommendation_count": 1,
                "error_message": None,
            }
        },
    }


def test_run_pipeline_continues_when_recommendation_fails(monkeypatch):
    monkeypatch.setattr(pipeline, "setup_database", Mock())
    monkeypatch.setattr(
        pipeline, "run_ingestion", Mock(return_value=["run-1", "run-2"])
    )
    monkeypatch.setattr(pipeline, "run_embeddings", Mock(return_value=3))
    monkeypatch.setattr(
        pipeline,
        "generate_recommendations",
        Mock(side_effect=[RuntimeError("boom"), [{"rank": 1}]]),
    )

    summary = pipeline.run_pipeline(user_id="default", profile_id="profile-1")

    assert summary["recommendations_by_run"] == {
        "run-1": [],
        "run-2": [{"rank": 1}],
    }
    assert summary["recommendation_status_by_run_profile"] == {
        "run-1": {
            "profile-1": {
                "status": "failed",
                "recommendation_count": 0,
                "error_message": "boom",
            }
        },
        "run-2": {
            "profile-1": {
                "status": "succeeded",
                "recommendation_count": 1,
                "error_message": None,
            }
        },
    }


def test_run_pipeline_generates_for_multiple_profiles(monkeypatch):
    monkeypatch.setattr(pipeline, "setup_database", Mock())
    monkeypatch.setattr(pipeline, "run_ingestion", Mock(return_value=["run-1"]))
    monkeypatch.setattr(pipeline, "run_embeddings", Mock(return_value=2))
    monkeypatch.setattr(
        pipeline,
        "generate_recommendations",
        Mock(side_effect=[[{"rank": 1}], [{"rank": 1}, {"rank": 2}]]),
    )

    summary = pipeline.run_pipeline(
        user_id="default",
        profile_ids=["profile-1", "profile-2"],
    )

    assert summary["recommendations_by_run_profile"] == {
        "run-1": {
            "profile-1": [{"rank": 1}],
            "profile-2": [{"rank": 1}, {"rank": 2}],
        }
    }
    assert summary["recommendations_by_run"] == {
        "run-1": [
            {"profile_id": "profile-1", "rank": 1},
            {"profile_id": "profile-2", "rank": 1},
            {"profile_id": "profile-2", "rank": 2},
        ]
    }
    assert summary["recommendation_status_by_run_profile"] == {
        "run-1": {
            "profile-1": {
                "status": "succeeded",
                "recommendation_count": 1,
                "error_message": None,
            },
            "profile-2": {
                "status": "succeeded",
                "recommendation_count": 2,
                "error_message": None,
            },
        }
    }
