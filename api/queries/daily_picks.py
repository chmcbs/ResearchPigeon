"""
SQL queries for daily pick retrieval and profile resolution
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Callable
from core.recommendation_query_fragments import LATEST_RUN_FOR_PROFILE_AND_RUNS_CTE

LATEST_DAILY_PICKS_SQL = """
WITH latest_run AS (
    SELECT
        run_id,
        MAX(generated_at) AS generated_at
    FROM recommendations
    WHERE profile_id = %s
    GROUP BY run_id
    ORDER BY MAX(generated_at) DESC
    LIMIT 1
)
SELECT
    rec.rank,
    p.arxiv_id,
    p.title,
    COALESCE(p.abstract, '') AS abstract,
    d.description,
    p.pdf_url,
    rec.run_id::text,
    r.category,
    rec.generated_at,
    rec.base_dense_score,
    rec.keyword_boost,
    rec.final_score,
    rec.candidate_window,
    rec.fallback_stage
FROM latest_run lr
JOIN recommendations rec
  ON rec.run_id = lr.run_id
 AND rec.profile_id = %s
JOIN papers p ON p.arxiv_id = rec.arxiv_id
LEFT JOIN descriptions d ON d.arxiv_id = p.arxiv_id
JOIN runs r ON r.run_id = rec.run_id
ORDER BY rec.rank ASC;
"""

LATEST_DAILY_PICKS_FOR_RUNS_SQL = (
    LATEST_RUN_FOR_PROFILE_AND_RUNS_CTE
    + """
SELECT
    rec.rank,
    p.arxiv_id,
    p.title,
    COALESCE(p.abstract, '') AS abstract,
    d.description,
    p.pdf_url,
    rec.run_id::text,
    r.category,
    rec.generated_at,
    rec.base_dense_score,
    rec.keyword_boost,
    rec.final_score,
    rec.candidate_window,
    rec.fallback_stage
FROM latest_run lr
JOIN recommendations rec
  ON rec.run_id = lr.run_id
 AND rec.profile_id = %s
JOIN papers p ON p.arxiv_id = rec.arxiv_id
LEFT JOIN descriptions d ON d.arxiv_id = p.arxiv_id
JOIN runs r ON r.run_id = rec.run_id
ORDER BY rec.rank ASC;
"""
)

RESOLVE_PROFILE_SQL = """
SELECT profile_id::text, user_id, profile_slot, profile_name, category, interest_sentence, created_at
FROM user_profiles
WHERE profile_id = %s
  AND user_id = %s;
"""


@dataclass(frozen=True)
class DailyPickRow:
    rank: int
    arxiv_id: str
    title: str
    abstract: str
    description: str | None
    pdf_url: str | None
    run_id: str
    category: str
    generated_at: datetime
    base_dense_score: float
    keyword_boost: float
    final_score: float
    candidate_window: str
    fallback_stage: int


@dataclass(frozen=True)
class ResolvedProfileRow:
    profile_id: str
    user_id: str
    profile_slot: int
    profile_name: str
    category: str
    interest_sentence: str
    created_at: datetime


def fetch_latest_picks(
    profile_id: str,
    connect: Callable,
    database_url: str,
    run_ids: list[str] | None = None,
    conn=None,
) -> list[DailyPickRow]:
    query = LATEST_DAILY_PICKS_SQL
    params = (profile_id, profile_id)
    if run_ids:
        query = LATEST_DAILY_PICKS_FOR_RUNS_SQL
        params = (profile_id, list(dict.fromkeys(run_ids)), profile_id)

    if conn is None:
        with connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
    else:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()

    return [
        DailyPickRow(
            rank=int(row[0]),
            arxiv_id=row[1],
            title=row[2],
            abstract=row[3],
            description=row[4],
            pdf_url=row[5],
            run_id=row[6],
            category=row[7],
            generated_at=row[8],
            base_dense_score=float(row[9]),
            keyword_boost=float(row[10]),
            final_score=float(row[11]),
            candidate_window=row[12],
            fallback_stage=int(row[13]),
        )
        for row in rows
    ]


def fetch_profile_by_id(
    profile_id: str,
    user_id: str,
    connect: Callable,
    database_url: str,
    conn=None,
) -> ResolvedProfileRow | None:
    if conn is None:
        with connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(RESOLVE_PROFILE_SQL, (profile_id, user_id))
                row = cur.fetchone()
    else:
        with conn.cursor() as cur:
            cur.execute(RESOLVE_PROFILE_SQL, (profile_id, user_id))
            row = cur.fetchone()

    if row is None:
        return None

    return ResolvedProfileRow(
        profile_id=row[0],
        user_id=row[1],
        profile_slot=int(row[2]),
        profile_name=row[3],
        category=row[4],
        interest_sentence=row[5],
        created_at=row[6],
    )
