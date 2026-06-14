"""
Service functions for profile endpoints
"""

from typing import Callable

from api.mappers import to_profile_summary


def create_profile_payload(
    request,
    user_id: str,
    create_profile: Callable[..., str],
    initialize_preference_embedding: Callable[..., None],
    list_profiles_payload: Callable[[str], dict],
) -> dict:
    profile_id = create_profile(
        user_id=user_id,
        profile_name=request.profile_name,
        category=request.category,
        interest_sentence=request.interest_sentence,
    )
    initialize_preference_embedding(
        interest_text=request.interest_sentence,
        user_id=user_id,
        profile_id=profile_id,
    )

    profiles = list_profiles_payload(user_id)["profiles"]
    created_profile = next((item for item in profiles if item["profile_id"] == profile_id), None)
    if created_profile is None:
        raise ValueError("created profile was not found")
    return {"profile": created_profile}


def list_profiles_payload(
    user_id: str,
    fetch_profiles_for_user: Callable[[str], list],
) -> dict:
    profile_rows = fetch_profiles_for_user(user_id)
    return {
        "user_id": user_id,
        "profiles": [to_profile_summary(row) for row in profile_rows],
    }


def update_digest_selection_payload(
    request,
    user_id: str,
    set_digest_profile_selection: Callable[..., list[str]],
) -> dict:
    selected_profile_ids = set_digest_profile_selection(
        profile_ids=request.profile_ids,
        user_id=user_id,
    )
    return {
        "user_id": user_id,
        "selected_profile_ids": selected_profile_ids,
    }


def reorder_profiles_payload(
    request,
    user_id: str,
    reorder_profiles: Callable[..., list[str]],
) -> dict:
    ordered_profile_ids = reorder_profiles(
        profile_ids=request.profile_ids,
        user_id=user_id,
    )
    return {
        "user_id": user_id,
        "profile_ids": ordered_profile_ids,
    }


def add_profile_keyword_payload(
    profile_id: str,
    request,
    user_id: str,
    add_profile_keyword: Callable[..., list[str]],
) -> dict:
    keywords = add_profile_keyword(
        profile_id=profile_id,
        user_id=user_id,
        keyword=request.keyword,
    )
    return {
        "user_id": user_id,
        "profile_id": profile_id,
        "keywords": keywords,
    }


def remove_profile_keyword_payload(
    profile_id: str,
    request,
    user_id: str,
    remove_profile_keyword: Callable[..., list[str]],
) -> dict:
    keywords = remove_profile_keyword(
        profile_id=profile_id,
        user_id=user_id,
        keyword=request.keyword,
    )
    return {
        "user_id": user_id,
        "profile_id": profile_id,
        "keywords": keywords,
    }


def list_profile_keywords_payload(
    profile_id: str,
    user_id: str,
    list_profile_keywords: Callable[..., list[str]],
) -> dict:
    keywords = list_profile_keywords(profile_id=profile_id, user_id=user_id)
    return {
        "user_id": user_id,
        "profile_id": profile_id,
        "keywords": keywords,
    }


def update_profile_payload(
    profile_id: str,
    request,
    user_id: str,
    update_profile: Callable[..., object],
    fetch_profiles_for_user: Callable[[str], list],
) -> dict:
    update_profile(
        profile_id=profile_id,
        user_id=user_id,
        profile_name=request.profile_name,
        category=request.category,
        digest_enabled=request.digest_enabled,
    )
    profiles = fetch_profiles_for_user(user_id)
    updated_profile = next(
        (profile for profile in profiles if str(profile.profile_id) == profile_id),
        None,
    )
    if updated_profile is None:
        raise ValueError("updated profile was not found")
    return {"profile": to_profile_summary(updated_profile)}


def delete_profile_payload(
    profile_id: str,
    user_id: str,
    delete_profile: Callable[..., bool],
) -> dict:
    deleted = delete_profile(
        profile_id=profile_id,
        user_id=user_id,
    )
    return {
        "profile_id": profile_id,
        "deleted": deleted,
    }
