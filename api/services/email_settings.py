"""
Service functions for email settings endpoints
"""

from typing import Callable


def get_email_settings_payload(
    user_id: str,
    get_email_settings: Callable[[str], dict],
) -> dict:
    settings = get_email_settings(user_id)
    return {
        "user_id": user_id,
        "digest_subscribed": settings["digest_subscribed"],
        "unsubscribed_at": settings["unsubscribed_at"],
    }


def update_email_settings_payload(
    request,
    user_id: str,
    set_digest_subscribed: Callable[..., dict],
) -> dict:
    settings = set_digest_subscribed(
        user_id,
        digest_subscribed=request.digest_subscribed,
    )
    return {
        "user_id": user_id,
        "digest_subscribed": settings["digest_subscribed"],
        "unsubscribed_at": settings["unsubscribed_at"],
    }
