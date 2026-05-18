"""
User profile model and helpers
"""

import uuid
from contextlib import contextmanager
from dataclasses import dataclass

import psycopg

from core.config import DEFAULT_INTEREST_TEXT, DEFAULT_USER_ID, get_arxiv_categories
from core.db import get_database_url
from core.keyword_search import MAX_KEYWORDS_PER_PROFILE, normalize_keyword


@dataclass(frozen=True)
class ProfileRow:
    profile_id: str
    user_id: str
    profile_slot: int
    profile_name: str
    category: str
    interest_sentence: str
    created_at: object
    digest_enabled: bool


MAX_PROFILES_PER_USER = 3

LOCK_OCCUPIED_SLOTS_SQL = """
SELECT profile_slot
FROM user_profiles
WHERE user_id = %s
ORDER BY profile_slot ASC
FOR UPDATE;
"""

INSERT_PROFILE_SQL = """
INSERT INTO user_profiles (
    profile_id,
    user_id,
    profile_slot,
    profile_name,
    category,
    interest_sentence
)
VALUES (%s, %s, %s, %s, %s, %s);
"""

LIST_PROFILES_SQL = """
SELECT
    profile_id::text,
    user_id,
    profile_slot,
    profile_name,
    category,
    interest_sentence,
    created_at,
    digest_enabled
FROM user_profiles
WHERE user_id = %s
ORDER BY profile_slot ASC;
"""

GET_PROFILE_SQL = """
SELECT
    profile_id::text,
    user_id,
    profile_slot,
    profile_name,
    category,
    interest_sentence,
    created_at,
    digest_enabled
FROM user_profiles
WHERE profile_id = %s;
"""

CHECK_PROFILE_OWNERSHIP_SQL = """
SELECT 1
FROM user_profiles
WHERE profile_id = %s
  AND user_id = %s;
"""

UPDATE_PROFILE_SQL = """
UPDATE user_profiles
SET
    profile_name = %s,
    category = %s,
    digest_enabled = %s,
    updated_at = NOW()
WHERE profile_id = %s
  AND user_id = %s;
"""

DELETE_PROFILE_SQL = """
DELETE FROM user_profiles
WHERE profile_id = %s
  AND user_id = %s;
"""

LIST_KEYWORDS_SQL = """
SELECT keyword
FROM profile_keywords
WHERE profile_id = %s
ORDER BY created_at ASC, keyword ASC;
"""

COUNT_KEYWORDS_SQL = """
SELECT COUNT(*)
FROM profile_keywords
WHERE profile_id = %s;
"""

INSERT_KEYWORD_SQL = """
INSERT INTO profile_keywords (profile_id, keyword)
VALUES (%s, %s)
ON CONFLICT (profile_id, keyword) DO NOTHING
RETURNING keyword;
"""

DELETE_KEYWORD_SQL = """
DELETE FROM profile_keywords
WHERE profile_id = %s
  AND keyword = %s;
"""

LIST_DIGEST_SELECTED_SQL = """
SELECT profile_id::text
FROM user_profiles
WHERE user_id = %s
  AND digest_enabled = TRUE
ORDER BY profile_slot ASC;
"""

MATCH_USER_PROFILES_SQL = """
SELECT profile_id::text
FROM user_profiles
WHERE user_id = %s
  AND profile_id = ANY(%s::uuid[]);
"""

DISABLE_ALL_DIGESTS_SQL = """
UPDATE user_profiles
SET digest_enabled = FALSE
WHERE user_id = %s;
"""

ENABLE_DIGESTS_SQL = """
UPDATE user_profiles
SET digest_enabled = TRUE
WHERE user_id = %s
  AND profile_id = ANY(%s::uuid[]);
"""


@contextmanager
def _connection_scope(conn=None):
    if conn is not None:
        yield conn
        return

    with psycopg.connect(get_database_url()) as owned_conn:
        yield owned_conn


def _validate_interest_sentence(interest_sentence: str) -> str:
    value = interest_sentence.strip()
    if not value:
        raise ValueError("interest_sentence must not be empty")
    return value


def _validate_category(category: str) -> str:
    value = category.strip()
    if not value:
        raise ValueError("category must not be empty")
    allowed_categories = set(get_arxiv_categories())
    if value not in allowed_categories:
        raise ValueError(
            "category must be one of configured ARXIV_CATEGORIES: "
            + ", ".join(sorted(allowed_categories))
        )
    return value


def _validate_profile_name(profile_name: str) -> str:
    value = profile_name.strip()
    if not value:
        raise ValueError("profile_name must not be empty")
    if len(value) > 60:
        raise ValueError("profile_name must be <= 60 characters")
    return value


def _pick_next_available_slot(occupied_slots: set[int]) -> int:
    for slot in range(1, MAX_PROFILES_PER_USER + 1):
        if slot not in occupied_slots:
            return slot
    raise ValueError(f"user has reached the {MAX_PROFILES_PER_USER}-profile cap")


def create_profile(
    user_id: str = DEFAULT_USER_ID,
    category: str | None = None,
    interest_sentence: str = DEFAULT_INTEREST_TEXT,
    profile_name: str | None = None,
    conn=None,
) -> str:
    validated_interest = _validate_interest_sentence(interest_sentence)
    validated_category = _validate_category(category or get_arxiv_categories()[0])
    profile_id = str(uuid.uuid4())

    with _connection_scope(conn) as active_conn:
        with active_conn.cursor() as cur:
            cur.execute(LOCK_OCCUPIED_SLOTS_SQL, (user_id,))
            occupied_slots = {int(row[0]) for row in cur.fetchall()}

            profile_slot = _pick_next_available_slot(occupied_slots)
            default_profile_name = f"Profile {profile_slot}"
            validated_profile_name = _validate_profile_name(
                profile_name or default_profile_name
            )

            cur.execute(
                INSERT_PROFILE_SQL,
                (
                    profile_id,
                    user_id,
                    profile_slot,
                    validated_profile_name,
                    validated_category,
                    validated_interest,
                ),
            )

    return profile_id


def list_profiles(user_id: str = DEFAULT_USER_ID, conn=None) -> list[ProfileRow]:
    with _connection_scope(conn) as active_conn:
        with active_conn.cursor() as cur:
            cur.execute(LIST_PROFILES_SQL, (user_id,))
            rows = cur.fetchall()

    return [
        ProfileRow(
            profile_id=row[0],
            user_id=row[1],
            profile_slot=int(row[2]),
            profile_name=row[3],
            category=row[4],
            interest_sentence=row[5],
            created_at=row[6],
            digest_enabled=bool(row[7]),
        )
        for row in rows
    ]


def get_profile(profile_id: str, conn=None) -> ProfileRow | None:
    with _connection_scope(conn) as active_conn:
        with active_conn.cursor() as cur:
            cur.execute(GET_PROFILE_SQL, (profile_id,))
            row = cur.fetchone()

    if row is None:
        return None

    return ProfileRow(
        profile_id=row[0],
        user_id=row[1],
        profile_slot=int(row[2]),
        profile_name=row[3],
        category=row[4],
        interest_sentence=row[5],
        created_at=row[6],
        digest_enabled=bool(row[7]),
    )


def resolve_profile_id(
    user_id: str = DEFAULT_USER_ID,
    profile_id: str | None = None,
    conn=None,
) -> str:
    if not profile_id:
        raise ValueError("profile_id is required")
    return str(profile_id)


def list_profile_keywords(
    profile_id: str,
    user_id: str = DEFAULT_USER_ID,
    conn=None,
) -> list[str]:
    with _connection_scope(conn) as active_conn:
        with active_conn.cursor() as cur:
            cur.execute(CHECK_PROFILE_OWNERSHIP_SQL, (profile_id, user_id))
            if cur.fetchone() is None:
                raise ValueError("profile not found for user")

            cur.execute(LIST_KEYWORDS_SQL, (profile_id,))
            rows = cur.fetchall()

    return [row[0] for row in rows]


def add_profile_keyword(
    profile_id: str,
    keyword: str,
    user_id: str = DEFAULT_USER_ID,
    conn=None,
) -> list[str]:
    normalized_keyword = normalize_keyword(keyword)

    with _connection_scope(conn) as active_conn:
        with active_conn.cursor() as cur:
            cur.execute(CHECK_PROFILE_OWNERSHIP_SQL, (profile_id, user_id))
            if cur.fetchone() is None:
                raise ValueError("profile not found for user")

            cur.execute(COUNT_KEYWORDS_SQL, (profile_id,))
            current_count = int(cur.fetchone()[0])

            cur.execute(INSERT_KEYWORD_SQL, (profile_id, normalized_keyword))
            inserted = cur.fetchone()
            if inserted is not None and current_count >= MAX_KEYWORDS_PER_PROFILE:
                raise ValueError(
                    f"profile keyword cap reached ({MAX_KEYWORDS_PER_PROFILE})"
                )

            cur.execute(LIST_KEYWORDS_SQL, (profile_id,))
            rows = cur.fetchall()

    return [row[0] for row in rows]


def remove_profile_keyword(
    profile_id: str,
    keyword: str,
    user_id: str = DEFAULT_USER_ID,
    conn=None,
) -> list[str]:
    normalized_keyword = normalize_keyword(keyword)

    with _connection_scope(conn) as active_conn:
        with active_conn.cursor() as cur:
            cur.execute(CHECK_PROFILE_OWNERSHIP_SQL, (profile_id, user_id))
            if cur.fetchone() is None:
                raise ValueError("profile not found for user")

            cur.execute(DELETE_KEYWORD_SQL, (profile_id, normalized_keyword))

            cur.execute(LIST_KEYWORDS_SQL, (profile_id,))
            rows = cur.fetchall()

    return [row[0] for row in rows]


def list_digest_selected_profile_ids(
    user_id: str = DEFAULT_USER_ID, conn=None
) -> list[str]:
    with _connection_scope(conn) as active_conn:
        with active_conn.cursor() as cur:
            cur.execute(LIST_DIGEST_SELECTED_SQL, (user_id,))
            rows = cur.fetchall()

    return [row[0] for row in rows]


def set_digest_profile_selection(
    profile_ids: list[str],
    user_id: str = DEFAULT_USER_ID,
    conn=None,
) -> list[str]:
    requested_profile_ids = list(dict.fromkeys(profile_ids))
    if not requested_profile_ids:
        with _connection_scope(conn) as active_conn:
            with active_conn.cursor() as cur:
                cur.execute(DISABLE_ALL_DIGESTS_SQL, (user_id,))
        return []

    with _connection_scope(conn) as active_conn:
        with active_conn.cursor() as cur:
            cur.execute(MATCH_USER_PROFILES_SQL, (user_id, requested_profile_ids))
            matched_ids = {row[0] for row in cur.fetchall()}
            missing_ids = sorted(set(requested_profile_ids) - matched_ids)
            if missing_ids:
                raise ValueError("some profile_ids do not belong to user")

            cur.execute(DISABLE_ALL_DIGESTS_SQL, (user_id,))
            cur.execute(ENABLE_DIGESTS_SQL, (user_id, requested_profile_ids))

            cur.execute(LIST_DIGEST_SELECTED_SQL, (user_id,))
            rows = cur.fetchall()

    selected = [row[0] for row in rows]
    return selected


def update_profile(
    profile_id: str,
    user_id: str = DEFAULT_USER_ID,
    profile_name: str | None = None,
    category: str | None = None,
    digest_enabled: bool | None = None,
    conn=None,
) -> ProfileRow:
    existing_profile = get_profile(profile_id=profile_id, conn=conn)
    if existing_profile is None or existing_profile.user_id != user_id:
        raise ValueError("profile not found for user")

    next_profile_name = _validate_profile_name(
        profile_name if profile_name is not None else existing_profile.profile_name
    )
    next_category = _validate_category(
        category if category is not None else existing_profile.category
    )
    next_digest_enabled = (
        digest_enabled
        if digest_enabled is not None
        else bool(existing_profile.digest_enabled)
    )

    with _connection_scope(conn) as active_conn:
        with active_conn.cursor() as cur:
            cur.execute(
                UPDATE_PROFILE_SQL,
                (
                    next_profile_name,
                    next_category,
                    next_digest_enabled,
                    profile_id,
                    user_id,
                ),
            )
            if cur.rowcount == 0:
                raise ValueError("profile not found for user")

    updated_profile = get_profile(profile_id=profile_id, conn=conn)
    if updated_profile is None:
        raise ValueError("failed to load updated profile")
    return updated_profile


def delete_profile(
    profile_id: str,
    user_id: str = DEFAULT_USER_ID,
    conn=None,
) -> bool:
    with _connection_scope(conn) as active_conn:
        with active_conn.cursor() as cur:
            cur.execute(DELETE_PROFILE_SQL, (profile_id, user_id))
            return cur.rowcount > 0
