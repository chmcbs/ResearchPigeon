"""
Shared pytest fixtures for the test suite
"""

import pytest


@pytest.fixture(autouse=True)
def _authenticated_test_session(monkeypatch) -> None:
    monkeypatch.setenv("DISABLE_CSRF", "1")
    monkeypatch.setenv("DISABLE_RATE_LIMIT", "1")
    monkeypatch.setenv("ALLOW_DEV_MAGIC_LINK_RESPONSE", "1")
    monkeypatch.setenv("ALLOW_DEBUG_FEATURES", "1")
    monkeypatch.setenv("DEBUG_ADMIN_EMAILS", "test@example.com")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setattr(
        "api.dependencies.get_auth_session_payload",
        lambda *_args, **_kwargs: {
            "authenticated": True,
            "user_id": "default",
            "email": "test@example.com",
        },
    )
