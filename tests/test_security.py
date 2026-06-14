"""
Security-focused route tests for session auth and profile ownership
"""

from contextlib import contextmanager
from unittest.mock import Mock

import pytest
from starlette.testclient import TestClient

import api.dependencies as dependencies
import api.routes as routes
from core.rate_limit import reset_rate_limits
from core.security import resolve_safe_redirect_path


@pytest.fixture
def fake_api_uow(monkeypatch):
    sentinel_conn = object()
    sentinel_uow = type("Uow", (), {"conn": sentinel_conn})()

    @contextmanager
    def fake_uow(uow=None, conn=None):
        yield sentinel_uow

    monkeypatch.setattr(dependencies, "open_api_unit_of_work", fake_uow)
    return sentinel_conn


@pytest.fixture
def unauthenticated_client(monkeypatch):
    monkeypatch.setattr(
        routes,
        "require_authenticated_user_id",
        Mock(
            side_effect=routes.HTTPException(
                status_code=401, detail="Sign in required"
            )
        ),
    )
    return TestClient(routes.app)


@pytest.mark.parametrize(
    "method,path,json_body",
    [
        ("GET", "/api/profiles", None),
        ("GET", "/api/papers/hub", None),
        ("POST", "/api/profiles", {"category": "cs.AI", "interest_sentence": "test"}),
        (
            "POST",
            "/api/feedback",
            {
                "profile_id": "profile-1",
                "arxiv_id": "2601.00001",
                "label": "like",
            },
        ),
    ],
)
def test_product_routes_require_authentication(
    unauthenticated_client, method, path, json_body
):
    response = unauthenticated_client.request(method, path, json=json_body)
    assert response.status_code == 401
    assert response.json()["detail"] == "Sign in required"


def test_profiles_list_ignores_spoofed_user_id_query_param(monkeypatch):
    list_mock = Mock(return_value={"user_id": "user@example.com", "profiles": []})
    monkeypatch.setattr(routes, "list_profiles_payload", list_mock)

    client = TestClient(routes.app)
    response = client.get("/api/profiles?user_id=attacker@example.com")

    assert response.status_code == 200
    list_mock.assert_called_once_with(user_id="default")


def test_magic_link_redirect_rejects_unlisted_paths(monkeypatch):
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
    response = client.get(
        "/auth/magic-link/verify?token=abc&next=https://evil.example",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/profiles"


def test_magic_link_redirect_allows_debug_paths_for_admin(monkeypatch):
    monkeypatch.setenv("ALLOW_DEBUG_FEATURES", "1")
    monkeypatch.setenv("DEBUG_ADMIN_EMAILS", "admin@example.com")
    monkeypatch.setattr(
        routes,
        "verify_magic_link_payload",
        Mock(
            return_value={
                "verified": True,
                "session_id": "session-123",
                "user_id": "admin@example.com",
                "email": "admin@example.com",
            }
        ),
    )
    client = TestClient(routes.app)
    response = client.get(
        "/auth/magic-link/verify?token=abc&next=/digest",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/digest"
    assert "csrf_token=" in response.headers["set-cookie"]


def test_magic_link_redirect_rejects_digest_for_non_admin(monkeypatch):
    monkeypatch.setenv("ALLOW_DEBUG_FEATURES", "1")
    monkeypatch.setenv("DEBUG_ADMIN_EMAILS", "admin@example.com")
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
    response = client.get(
        "/auth/magic-link/verify?token=abc&next=/digest",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/profiles"


def test_validate_route_hidden_when_debug_disabled(monkeypatch):
    monkeypatch.delenv("ALLOW_DEBUG_FEATURES", raising=False)
    monkeypatch.delenv("ALLOW_DEBUG_DIGEST_DATA_RESET", raising=False)
    client = TestClient(routes.app)

    response = client.get("/validate")

    assert response.status_code == 404


def test_debug_routes_hidden_from_unauthenticated_users_when_debug_disabled(
    monkeypatch,
):
    monkeypatch.delenv("ALLOW_DEBUG_FEATURES", raising=False)
    monkeypatch.delenv("ALLOW_DEBUG_DIGEST_DATA_RESET", raising=False)
    monkeypatch.setattr(
        "api.dependencies.get_auth_session_payload",
        lambda *_args, **_kwargs: {
            "authenticated": False,
            "user_id": None,
            "email": None,
            "can_debug_access": False,
        },
    )
    client = TestClient(routes.app)

    for path in (
        "/validate",
        "/digest",
        "/metrics",
        "/test-generation",
        "/test-generation/debug?profile_id=p1",
    ):
        response = client.get(path)
        assert response.status_code == 404, path

    response = client.post("/debug/profile-data/reset")
    assert response.status_code == 404

    response = client.post("/debug/digest-data/reset")
    assert response.status_code == 404


def test_debug_routes_require_auth_when_debug_enabled(monkeypatch):
    monkeypatch.setenv("ALLOW_DEBUG_FEATURES", "1")
    monkeypatch.setenv("DEBUG_ADMIN_EMAILS", "admin@example.com")
    monkeypatch.setattr(
        "api.dependencies.get_auth_session_payload",
        lambda *_args, **_kwargs: {
            "authenticated": False,
            "user_id": None,
            "email": None,
            "can_debug_access": False,
        },
    )
    client = TestClient(routes.app)

    response = client.get("/validate")

    assert response.status_code == 401
    assert response.json()["detail"] == "Sign in required"


def test_validate_route_requires_admin_email(monkeypatch):
    monkeypatch.setenv("ALLOW_DEBUG_FEATURES", "1")
    monkeypatch.setenv("DEBUG_ADMIN_EMAILS", "admin@example.com")
    monkeypatch.setattr(
        "api.dependencies.get_auth_session_payload",
        Mock(
            return_value={
                "authenticated": True,
                "user_id": "other@example.com",
                "email": "other@example.com",
                "can_debug_access": False,
            }
        ),
    )
    client = TestClient(routes.app)

    response = client.get("/validate")

    assert response.status_code == 403


def test_metrics_requires_admin_email(monkeypatch):
    monkeypatch.setenv("ALLOW_DEBUG_FEATURES", "1")
    monkeypatch.setenv("DEBUG_ADMIN_EMAILS", "admin@example.com")
    monkeypatch.setattr(
        "api.dependencies.get_auth_session_payload",
        Mock(
            return_value={
                "authenticated": True,
                "user_id": "other@example.com",
                "email": "other@example.com",
                "can_debug_access": False,
            }
        ),
    )
    client = TestClient(routes.app)

    response = client.get("/metrics")

    assert response.status_code == 403


def test_test_generation_debug_requires_admin_email(monkeypatch):
    monkeypatch.setenv("ALLOW_DEBUG_FEATURES", "1")
    monkeypatch.setenv("DEBUG_ADMIN_EMAILS", "admin@example.com")
    monkeypatch.setattr(
        "api.dependencies.get_auth_session_payload",
        Mock(
            return_value={
                "authenticated": True,
                "user_id": "other@example.com",
                "email": "other@example.com",
                "can_debug_access": False,
            }
        ),
    )
    client = TestClient(routes.app)

    response = client.get("/test-generation/debug?profile_id=profile-1")

    assert response.status_code == 403


def test_mutating_route_requires_csrf_when_enabled(monkeypatch):
    monkeypatch.delenv("DISABLE_CSRF", raising=False)
    client = TestClient(routes.app)
    client.cookies.set("session_id", "session-123")

    response = client.post(
        "/api/profiles",
        json={"category": "cs.AI", "interest_sentence": "test"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "CSRF validation failed"


def test_mutating_route_accepts_matching_csrf_token(monkeypatch):
    monkeypatch.delenv("DISABLE_CSRF", raising=False)
    monkeypatch.setattr(
        routes,
        "create_profile_payload",
        Mock(
            return_value={
                "profile": {
                    "profile_id": "profile-1",
                    "user_id": "default",
                    "profile_slot": 1,
                    "profile_name": "Profile",
                    "category": "cs.AI",
                    "interest_sentence": "test",
                    "digest_enabled": False,
                    "keywords": [],
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "preference_updated_at": None,
                }
            }
        ),
    )
    client = TestClient(routes.app)
    client.cookies.set("session_id", "session-123")
    client.cookies.set("csrf_token", "csrf-abc")

    response = client.post(
        "/api/profiles",
        json={"category": "cs.AI", "interest_sentence": "test"},
        headers={"X-CSRF-Token": "csrf-abc"},
    )

    assert response.status_code == 200


def test_magic_link_request_omits_link_without_dev_flag(monkeypatch, fake_api_uow):
    monkeypatch.delenv("ALLOW_DEV_MAGIC_LINK_RESPONSE", raising=False)
    monkeypatch.setattr(
        "api.dependencies.create_magic_link",
        lambda email, conn=None: ("token-value", email.strip().lower()),
    )
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "api.dependencies.send_magic_link_email",
        lambda to_email, magic_link: sent.append((to_email, magic_link)),
    )
    client = TestClient(routes.app)
    response = client.post("/auth/magic-link/request", json={"email": "user@example.com"})

    assert response.status_code == 200
    assert response.json() == {"sent": True, "magic_link": None}
    assert sent == [
        ("user@example.com", "http://localhost:8000/auth/magic-link/verify?token=token-value")
    ]


def test_magic_link_request_is_rate_limited(monkeypatch, fake_api_uow):
    monkeypatch.delenv("DISABLE_RATE_LIMIT", raising=False)
    reset_rate_limits()
    monkeypatch.setenv("MAGIC_LINK_REQUEST_LIMIT_PER_EMAIL", "1")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "3600")
    monkeypatch.setattr(
        "api.dependencies.create_magic_link",
        lambda email, conn=None: ("token-value", email.strip().lower()),
    )
    client = TestClient(routes.app)

    first = client.post("/auth/magic-link/request", json={"email": "user@example.com"})
    second = client.post("/auth/magic-link/request", json={"email": "user@example.com"})

    assert first.status_code == 200
    assert second.status_code == 429


def test_test_generation_run_is_rate_limited_per_user(monkeypatch, fake_api_uow):
    from fastapi import HTTPException

    import api.dependencies as dependencies
    from api.schemas import TestGenerationRequest

    monkeypatch.delenv("DISABLE_RATE_LIMIT", raising=False)
    reset_rate_limits()
    monkeypatch.setenv("TEST_GENERATION_LIMIT_PER_USER", "1")
    monkeypatch.setattr(
        dependencies,
        "run_test_generation_payload_service",
        Mock(
            return_value={
                "user_id": "default",
                "primary_profile_id": "profile-1",
                "requested_profile_ids": ["profile-1"],
                "run_ids": ["run-1"],
                "embedded_count": 1,
                "generation_runs": [],
                "has_failures": False,
                "needs_generation": False,
                "picks": [],
                "sections": [],
                "email_status": None,
                "email_error": None,
            }
        ),
    )

    request = TestGenerationRequest(profile_ids=["profile-1"])
    dependencies.run_test_generation_payload(
        request,
        user_id="default",
        admin_email="admin@example.com",
    )

    with pytest.raises(HTTPException) as exc:
        dependencies.run_test_generation_payload(
            request,
            user_id="default",
            admin_email="admin@example.com",
        )

    assert exc.value.status_code == 429


def test_internal_cron_endpoint_is_not_exposed():
    client = TestClient(routes.app)
    response = client.post("/internal/cron/daily-digest")
    assert response.status_code == 404


def test_debug_reset_requires_admin_email(monkeypatch):
    monkeypatch.setenv("ALLOW_DEBUG_FEATURES", "1")
    monkeypatch.setenv("DEBUG_ADMIN_EMAILS", "admin@example.com")
    monkeypatch.setattr(
        "api.dependencies.get_auth_session_payload",
        Mock(
            return_value={
                "authenticated": True,
                "user_id": "other@example.com",
                "email": "other@example.com",
                "can_debug_access": False,
            }
        ),
    )
    client = TestClient(routes.app)
    client.cookies.set("session_id", "session-123")
    client.cookies.set("csrf_token", "csrf-abc")

    response = client.post(
        "/debug/profile-data/reset",
        headers={"X-CSRF-Token": "csrf-abc"},
    )

    assert response.status_code == 403
    assert "admin" in response.json()["detail"].lower()


def test_debug_reset_allows_configured_admin(monkeypatch, fake_api_uow):
    monkeypatch.setenv("ALLOW_DEBUG_FEATURES", "1")
    monkeypatch.setenv("DEBUG_ADMIN_EMAILS", "admin@example.com")
    monkeypatch.setattr(
        "api.dependencies.get_auth_session_payload",
        Mock(
            return_value={
                "authenticated": True,
                "user_id": "admin@example.com",
                "email": "admin@example.com",
                "can_debug_access": True,
            }
        ),
    )
    monkeypatch.setattr(
        "api.dependencies.reset_user_profiles",
        Mock(return_value={"deleted_profiles": 2}),
    )
    client = TestClient(routes.app)
    client.cookies.set("session_id", "session-123")
    client.cookies.set("csrf_token", "csrf-abc")

    response = client.post(
        "/debug/profile-data/reset",
        headers={"X-CSRF-Token": "csrf-abc"},
    )

    assert response.status_code == 200
    assert response.json()["deleted_profiles"] == 2


def test_auth_session_exposes_can_debug_access_for_admin(monkeypatch):
    monkeypatch.setenv("ALLOW_DEBUG_FEATURES", "1")
    monkeypatch.setenv("DEBUG_ADMIN_EMAILS", "admin@example.com")
    monkeypatch.setattr(
        routes,
        "get_auth_session_payload",
        Mock(
            return_value={
                "authenticated": True,
                "user_id": "admin@example.com",
                "email": "admin@example.com",
                "can_debug_access": True,
            }
        ),
    )
    client = TestClient(routes.app)

    response = client.get("/auth/session")

    assert response.status_code == 200
    assert response.json()["can_debug_access"] is True


def test_security_headers_are_present(monkeypatch):
    monkeypatch.setattr(
        routes,
        "list_profiles_payload",
        Mock(return_value={"user_id": "default", "profiles": []}),
    )
    client = TestClient(routes.app)
    response = client.get("/api/profiles")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"


@pytest.mark.parametrize(
    "next_path,email,expected",
    [
        ("/digest", None, "/profiles"),
        ("//evil.example", None, "/profiles"),
        ("/admin", None, "/profiles"),
        ("/digest", "admin@example.com", "/digest"),
        ("/validate", "admin@example.com", "/validate"),
        ("/validate", "other@example.com", "/profiles"),
        ("/validate", None, "/profiles"),
    ],
)
def test_resolve_safe_redirect_path(next_path, email, expected, monkeypatch):
    monkeypatch.setenv("ALLOW_DEBUG_FEATURES", "1")
    monkeypatch.setenv("DEBUG_ADMIN_EMAILS", "admin@example.com")
    assert resolve_safe_redirect_path(next_path, email=email) == expected
