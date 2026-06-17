"""
Route-level tests for FastAPI HTTP contracts
"""

from unittest.mock import Mock

from starlette.testclient import TestClient

import api.routes as routes


def test_feedback_hub_route_returns_sections(monkeypatch):
    generated_at = "2026-05-18T12:00:00+00:00"
    monkeypatch.setattr(
        routes,
        "get_feedback_hub_payload",
        Mock(
            return_value={
                "user_id": "default",
                "seen": [
                    {
                        "arxiv_id": "2601.00001",
                        "title": "Seen paper",
                        "pdf_url": "https://arxiv.org/pdf/2601.00001",
                        "profile_id": "profile-1",
                        "profile_name": "Research",
                        "category": "cs.AI",
                        "generated_at": generated_at,
                        "final_score": 0.91,
                        "rank": 1,
                    }
                ],
                "liked": [],
                "disliked": [],
            }
        ),
    )

    client = TestClient(routes.app)
    response = client.get("/api/papers/hub")

    assert response.status_code == 200
    body = response.json()
    assert body["seen"][0]["arxiv_id"] == "2601.00001"
    assert body["liked"] == []


def test_test_generation_progress_route_returns_snapshot(monkeypatch):
    monkeypatch.setattr(
        routes,
        "get_test_generation_progress_payload",
        Mock(
            return_value={
                "active": True,
                "step": "embeddings",
                "label": "Generating embeddings…",
                "detail": "Embedded 12 paper(s)",
                "updated_at": "2026-05-27T12:00:00+00:00",
            }
        ),
    )

    client = TestClient(routes.app)
    response = client.get("/test-generation/progress")

    assert response.status_code == 200
    body = response.json()
    assert body["active"] is True
    assert body["step"] == "embeddings"
    assert body["label"] == "Generating embeddings…"
    assert body["detail"] == "Embedded 12 paper(s)"
    assert body["updated_at"].startswith("2026-05-27T12:00:00")


def test_test_generation_run_route_returns_200_with_generation_status(monkeypatch):
    monkeypatch.setattr(
        routes,
        "run_test_generation_payload",
        Mock(
            return_value={
                "user_id": "default",
                "primary_profile_id": "profile-1",
                "requested_profile_ids": ["profile-1"],
                "run_ids": ["run-123"],
                "embedded_count": 5,
                "generation_runs": [
                    {
                        "run_id": "run-123",
                        "profile_statuses": [
                            {
                                "profile_id": "profile-1",
                                "status": "succeeded",
                                "recommendation_count": 1,
                                "error_message": None,
                            }
                        ],
                    }
                ],
                "has_failures": False,
                "needs_generation": False,
                "picks": [
                    {
                        "rank": 1,
                        "arxiv_id": "2601.00001",
                        "title": "Paper 1",
                        "abstract": "Abstract 1",
                        "pdf_url": "https://arxiv.org/pdf/2601.00001",
                        "final_score": 0.9,
                    }
                ],
                "sections": [
                    {
                        "profile_id": "profile-1",
                        "profile_slot": 1,
                        "category": "cs.AI",
                        "interest_sentence": "Efficient LLM systems",
                        "needs_generation": False,
                        "picks": [
                            {
                                "rank": 1,
                                "arxiv_id": "2601.00001",
                                "title": "Paper 1",
                                "abstract": "Abstract 1",
                                "pdf_url": "https://arxiv.org/pdf/2601.00001",
                                "final_score": 0.9,
                            }
                        ],
                    }
                ],
            }
        ),
    )

    client = TestClient(routes.app)
    response = client.post(
        "/test-generation/run",
        json={
            "profile_ids": ["profile-1"],
            "max_results": 123,
            "embedding_limit": 456,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["primary_profile_id"] == "profile-1"
    assert payload["has_failures"] is False
    assert payload["generation_runs"][0]["profile_statuses"][0]["status"] == "succeeded"


def test_test_generation_run_route_returns_500_for_internal_failure(monkeypatch):
    monkeypatch.setattr(
        routes,
        "run_test_generation_payload",
        Mock(
            side_effect=routes.HTTPException(
                status_code=500,
                detail="NO_SUCCESSFUL_GENERATION: generation failed for all run/profile targets",
            )
        ),
    )

    client = TestClient(routes.app)
    response = client.post(
        "/test-generation/run",
        json={
            "profile_ids": ["profile-1"],
            "max_results": 123,
            "embedding_limit": 456,
        },
    )

    assert response.status_code == 500
    payload = response.json()
    assert "NO_SUCCESSFUL_GENERATION" in payload["detail"]


def test_profiles_digest_selection_route_uses_static_handler(monkeypatch):
    update_digest_selection_mock = Mock(
        return_value={"user_id": "default", "selected_profile_ids": ["profile-1"]}
    )
    update_profile_mock = Mock(
        return_value={
            "profile": {
                "profile_id": "profile-1",
                "user_id": "default",
                "profile_slot": 1,
                "profile_name": "Profile 1",
                "category": "cs.AI",
                "interest_sentence": "Efficient LLM systems",
                "digest_enabled": True,
                "keywords": [],
                "created_at": "2026-01-01T00:00:00",
                "preference_updated_at": None,
            }
        }
    )
    monkeypatch.setattr(routes, "update_digest_selection_payload", update_digest_selection_mock)
    monkeypatch.setattr(routes, "update_profile_payload", update_profile_mock)

    client = TestClient(routes.app)
    response = client.put(
        "/api/profiles/digest-selection",
        json={"profile_ids": ["profile-1"]},
    )

    assert response.status_code == 200
    assert response.json()["selected_profile_ids"] == ["profile-1"]
    assert update_digest_selection_mock.call_count == 1
    assert update_profile_mock.call_count == 0


def test_profiles_delete_works_without_request_body(monkeypatch):
    delete_mock = Mock(
        return_value={"profile_id": "profile-1", "deleted": True}
    )
    monkeypatch.setattr(routes, "delete_profile_payload", delete_mock)

    client = TestClient(routes.app)
    response = client.delete("/api/profiles/profile-1")

    assert response.status_code == 200
    assert response.json() == {"profile_id": "profile-1", "deleted": True}
    delete_mock.assert_called_once()
    _args, kwargs = delete_mock.call_args
    assert kwargs["profile_id"] == "profile-1"
    assert kwargs["user_id"] == "default"


def test_validate_route_returns_internal_validation_ui():
    client = TestClient(routes.app)
    response = client.get("/validate")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Validation UI" in response.text
    assert "POST /test-generation/run" in response.text
    assert "Profile Keywords" in response.text


def test_site_config_route_returns_product_name(monkeypatch):
    monkeypatch.setenv("PRODUCT_NAME", "Paper Radar")
    client = TestClient(routes.app)

    response = client.get("/site-config")

    assert response.status_code == 200
    assert response.json() == {"product_name": "Paper Radar"}


def test_landing_profiles_and_digest_pages_are_served():
    client = TestClient(routes.app)

    landing = client.get("/")
    profiles = client.get("/profiles")
    preferences_redirect = client.get("/preferences", follow_redirects=False)
    digest = client.get("/digest")
    papers = client.get("/papers")

    assert landing.status_code == 200
    assert "<title>ResearchPigeon</title>" in landing.text
    assert profiles.status_code == 200
    assert "<title>Profiles - ResearchPigeon</title>" in profiles.text
    assert preferences_redirect.status_code == 307
    assert preferences_redirect.headers["location"] == "/profiles"
    assert digest.status_code == 200
    assert "<title>Dev - ResearchPigeon</title>" in digest.text
    assert papers.status_code == 200
    assert "<title>Papers - ResearchPigeon</title>" in papers.text


def test_magic_link_request_route_returns_payload(monkeypatch):
    monkeypatch.setattr(
        routes,
        "request_magic_link_payload",
        Mock(
            return_value={
                "sent": True,
                "magic_link": "http://localhost:8000/auth/magic-link/verify?token=t",
            }
        ),
    )
    client = TestClient(routes.app)
    response = client.post("/auth/magic-link/request", json={"email": "x@example.com"})

    assert response.status_code == 200
    assert response.json()["sent"] is True


def test_magic_link_verify_sets_session_cookie_and_redirects(monkeypatch):
    monkeypatch.setattr(
        routes,
        "verify_magic_link_payload",
        Mock(
            return_value={
                "verified": True,
                "session_id": "session-123",
                "user_id": "x@example.com",
                "email": "x@example.com",
            }
        ),
    )
    client = TestClient(routes.app)
    response = client.get("/auth/magic-link/verify?token=abc", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/profiles"
    assert "session_id=session-123" in response.headers["set-cookie"]


def test_magic_link_verify_supports_safe_next_redirect_for_admin(monkeypatch):
    monkeypatch.setenv("DEBUG_ADMIN_EMAILS", "admin@example.com")
    monkeypatch.setattr(
        routes,
        "verify_magic_link_payload",
        Mock(
            return_value={
                "verified": True,
                "session_id": "session-456",
                "user_id": "admin@example.com",
                "email": "admin@example.com",
            }
        ),
    )
    client = TestClient(routes.app)
    response = client.get(
        "/auth/magic-link/verify?token=abc&next=/digest", follow_redirects=False
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/digest"


def test_email_unsubscribe_redirects_to_preferences(monkeypatch):
    monkeypatch.setattr(
        routes,
        "unsubscribe_by_token_payload",
        Mock(return_value={"user_id": "reader@example.com"}),
    )
    client = TestClient(routes.app)
    response = client.get(
        "/email/unsubscribe?token=abc123",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/email/preferences?status=unsubscribed"


def test_email_unsubscribe_invalid_token_redirects_to_error_state(monkeypatch):
    monkeypatch.setattr(
        routes,
        "unsubscribe_by_token_payload",
        Mock(return_value={"user_id": None}),
    )
    client = TestClient(routes.app)
    response = client.get(
        "/email/unsubscribe?token=bad",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/email/preferences?status=invalid"


def test_email_settings_get_route_returns_payload(monkeypatch):
    monkeypatch.setattr(
        routes,
        "get_email_settings_payload",
        Mock(
            return_value={
                "user_id": "default",
                "digest_subscribed": True,
                "unsubscribed_at": None,
            }
        ),
    )
    client = TestClient(routes.app)
    response = client.get("/api/email-settings")

    assert response.status_code == 200
    assert response.json()["digest_subscribed"] is True
