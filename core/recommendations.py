"""
Generates top-K recommendations per (run_id, profile_id)
"""

import uuid
from dataclasses import dataclass

import psycopg

from core.config import DEFAULT_USER_ID, get_daily_picks_k, get_keyword_boost_cap
from core.db import get_database_url
from core.profiles import require_profile_id
from core.recommendations_sql import (
    DELETE_EXISTING_SQL,
    FETCH_EFFECTIVE_K_SQL,
    FETCH_RUN_SQL,
    INSERT_RECOMMENDATION_SQL,
    RANK_CANDIDATES_SQL,
)


@dataclass(frozen=True)
class RankedCandidateRow:
    rank: int
    arxiv_id: str
    title: str
    abstract: str
    fallback_stage: int
    candidate_window: str
    base_dense_score: float
    keyword_boost: float
    final_score: float


# Resolve the number of items to return (override > user preference > default)
def _get_effective_k(cur, profile_id: str, k_override: int | None) -> int:
    if k_override is not None:
        if k_override < 1:
            raise ValueError("k_override must be >= 1")
        return k_override

    default_k = get_daily_picks_k()
    cur.execute(FETCH_EFFECTIVE_K_SQL, (default_k, profile_id))
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"No preference profile found for profile_id={profile_id}")

    return int(row[0])


def _ensure_completed_run(cur, run_id: str) -> tuple[str, str, int]:
    cur.execute(FETCH_RUN_SQL, (run_id,))
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"Run {run_id} must exist and be completed")
    return str(row[0]), str(row[1]), int(row[2])


# Rank papers for a completed run and persist as recommendations
def generate_recommendations(
    run_id: str,
    user_id: str = DEFAULT_USER_ID,
    profile_id: str | None = None,
    k_override: int | None = None,
) -> list[dict]:
    resolved_profile_id = require_profile_id(user_id=user_id, profile_id=profile_id)

    with psycopg.connect(get_database_url()) as conn:
        with conn.cursor() as cur:
            _ensure_completed_run(cur, run_id)
            effective_k = _get_effective_k(cur, resolved_profile_id, k_override)

            cur.execute(
                RANK_CANDIDATES_SQL,
                (
                    run_id,
                    resolved_profile_id,
                    resolved_profile_id,
                    resolved_profile_id,
                    resolved_profile_id,
                    get_keyword_boost_cap(),
                    get_keyword_boost_cap(),
                    resolved_profile_id,
                    effective_k,
                ),
            )
            raw_rows = cur.fetchall()

            candidates = [
                RankedCandidateRow(
                    rank=int(row[0]),
                    arxiv_id=row[1],
                    title=row[2],
                    abstract=row[3] or "",
                    fallback_stage=int(row[4]),
                    candidate_window=row[5],
                    base_dense_score=float(row[6]),
                    keyword_boost=float(row[7]),
                    final_score=float(row[8]),
                )
                for row in raw_rows
            ]

            cur.execute(DELETE_EXISTING_SQL, (run_id, resolved_profile_id))

            inserts = [
                (
                    str(uuid.uuid4()),
                    run_id,
                    resolved_profile_id,
                    c.arxiv_id,
                    c.rank,
                    c.base_dense_score,
                    c.keyword_boost,
                    c.final_score,
                    c.candidate_window,
                    c.fallback_stage,
                )
                for c in candidates
            ]

            if inserts:
                cur.executemany(INSERT_RECOMMENDATION_SQL, inserts)

    return [
        {
            "rank": c.rank,
            "arxiv_id": c.arxiv_id,
            "title": c.title,
            "abstract": c.abstract,
            "fallback_stage": c.fallback_stage,
            "candidate_window": c.candidate_window,
            "base_dense_score": c.base_dense_score,
            "keyword_boost": c.keyword_boost,
            "final_score": c.final_score,
        }
        for c in candidates
    ]


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        raise SystemExit(
            "Usage: python -m core.recommendations <run_id> <profile_id> [user_id]"
        )

    cli_run_id = sys.argv[1]
    cli_profile_id = sys.argv[2]
    cli_user_id = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_USER_ID
    generated = generate_recommendations(
        cli_run_id,
        user_id=cli_user_id,
        profile_id=cli_profile_id,
    )

    for row in generated:
        print(
            f"{row['rank']}. {row['arxiv_id']} "
            f"score={row['final_score']:.4f} "
            f"stage={row['fallback_stage']} "
            f"window={row['candidate_window']}"
        )
