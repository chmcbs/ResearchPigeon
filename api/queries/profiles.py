"""
SQL queries for profile list reads
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

PROFILE_LIST_SQL = """
SELECT
    p.profile_id::text,
    p.user_id,
    p.profile_slot,
    p.profile_name,
    p.category,
    p.interest_sentence,
    p.digest_enabled,
    p.created_at,
    pp.updated_at,
    COALESCE(
        ARRAY(
            SELECT pk.keyword
            FROM profile_keywords pk
            WHERE pk.profile_id = p.profile_id
            ORDER BY pk.created_at ASC, pk.keyword ASC
        ),
        ARRAY[]::text[]
    ) AS keywords
FROM user_profiles p
LEFT JOIN profile_preferences pp ON pp.profile_id = p.profile_id
WHERE p.user_id = %s
ORDER BY p.profile_slot ASC;
"""


@dataclass(frozen=True)
class ProfileSummaryRow:
    profile_id: str
    user_id: str
    profile_slot: int
    profile_name: str
    category: str
    interest_sentence: str
    digest_enabled: bool
    created_at: datetime
    preference_updated_at: datetime | None
    keywords: list[str]


def fetch_profiles_for_user(
    user_id: str,
    connect: Callable,
    database_url: str,
    conn=None,
) -> list[ProfileSummaryRow]:
    if conn is None:
        with connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(PROFILE_LIST_SQL, (user_id,))
                rows = cur.fetchall()
    else:
        with conn.cursor() as cur:
            cur.execute(PROFILE_LIST_SQL, (user_id,))
            rows = cur.fetchall()

    return [
        ProfileSummaryRow(
            profile_id=row[0],
            user_id=row[1],
            profile_slot=int(row[2]),
            profile_name=row[3],
            category=row[4],
            interest_sentence=row[5],
            digest_enabled=bool(row[6]),
            created_at=row[7],
            preference_updated_at=row[8],
            keywords=list(row[9] or []),
        )
        for row in rows
    ]
