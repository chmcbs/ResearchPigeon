"""
Service functions for magic-link authentication routes
"""

from typing import Callable


def request_magic_link_payload(
    request,
    create_magic_link: Callable[[str], tuple[str, str]],
    send_magic_link_email: Callable[[str, str], None],
    app_base_url: str,
    *,
    expose_magic_link: bool,
) -> dict:
    token, _ = create_magic_link(request.email)
    magic_link = (
        f"{app_base_url.rstrip('/')}/auth/magic-link/verify?token={token}"
    )
    if expose_magic_link:
        return {"sent": True, "magic_link": magic_link}

    send_magic_link_email(request.email, magic_link)
    return {"sent": True, "magic_link": None}


def verify_magic_link_payload(
    token: str,
    verify_magic_link: Callable[[str], tuple[str, str, str]],
) -> dict:
    session_id, user_id, email = verify_magic_link(token)
    return {
        "verified": True,
        "session_id": session_id,
        "user_id": user_id,
        "email": email,
    }


def verify_digest_login_payload(
    token: str,
    login_from_digest_token: Callable[[str], tuple[str, str, str]],
) -> dict:
    session_id, user_id, email = login_from_digest_token(token)
    return {
        "verified": True,
        "session_id": session_id,
        "user_id": user_id,
        "email": email,
    }
