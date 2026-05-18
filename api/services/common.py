"""
Shared helpers used by multiple API services
"""

from typing import Callable

from api.queries.daily_picks import ResolvedProfileRow
from api.services.errors import BadRequestError, NotFoundError


def resolve_profile(
    user_id: str,
    profile_id: str | None,
    fetch_profile_by_id: Callable[[str, str], ResolvedProfileRow | None],
) -> dict:
    if not profile_id:
        raise BadRequestError("profile_id is required")

    profile_row = fetch_profile_by_id(profile_id, user_id)
    if profile_row is None:
        raise NotFoundError("profile not found for user")

    return {
        "profile_id": profile_row.profile_id,
        "user_id": profile_row.user_id,
        "profile_slot": profile_row.profile_slot,
        "profile_name": profile_row.profile_name,
        "category": profile_row.category,
        "interest_sentence": profile_row.interest_sentence,
        "created_at": profile_row.created_at,
    }
