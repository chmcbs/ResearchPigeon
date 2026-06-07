"""
Service functions for permanently deleting papers from a profile
"""

from typing import Callable


def delete_paper_payload(
    request,
    user_id: str,
    resolve_profile: Callable[[str, str | None], dict],
    dismiss_paper: Callable[..., dict],
) -> dict:
    profile = resolve_profile(user_id=user_id, profile_id=request.profile_id)
    resolved_profile_id = str(profile["profile_id"])
    result = dismiss_paper(
        arxiv_id=request.arxiv_id,
        user_id=user_id,
        profile_id=resolved_profile_id,
    )

    return {
        "user_id": user_id,
        **result,
    }
