"""
Tests recommendation generation and persistence
"""

import os
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, Mock

import psycopg
import pytest

from core import recommendations
from core.db import check_database_connection, get_database_url
from core.recommendations_sql import FETCH_RUN_SQL, RANK_CANDIDATES_SQL
from core.vector_helper import vector_literal


def _mock_connection_with_cursor(cursor):
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor

    connect = MagicMock()
    connect.return_value.__enter__.return_value = connection
    return connect, cursor


def test_generate_recommendations_requires_rankable_run(monkeypatch):
    cursor = MagicMock()
    cursor.fetchone.side_effect = [(1,), None]
    connect, _ = _mock_connection_with_cursor(cursor)
    monkeypatch.setattr(recommendations.psycopg, "connect", connect)

    with pytest.raises(ValueError, match="must exist and be completed or failed"):
        recommendations.generate_recommendations(
            "run-123",
            user_id="default",
            profile_id="profile-1",
        )


def test_generate_recommendations_replaces_rows_deterministically(monkeypatch):
    cursor = MagicMock()
    cursor.fetchone.side_effect = [
        (1,),
        ("run-123", "cs.AI", 150),
        (3,),
    ]
    cursor.fetchall.return_value = [
        (
            1,
            "2601.00001",
            "Paper A",
            None,
            0,
            "7d",
            0.8,
            0.1,
            0.9,
        ),
        (
            2,
            "2601.00002",
            "Paper B",
            "abstract",
            1,
            "30d",
            0.75,
            0.05,
            0.8,
        ),
    ]

    connect, _ = _mock_connection_with_cursor(cursor)
    monkeypatch.setattr(recommendations.psycopg, "connect", connect)
    monkeypatch.setattr(recommendations, "get_daily_picks_k", Mock(return_value=3))
    monkeypatch.setattr(
        recommendations, "get_keyword_boost_cap", Mock(return_value=0.25)
    )
    monkeypatch.setattr(
        recommendations.uuid,
        "uuid4",
        Mock(side_effect=["rec-1", "rec-2"]),
    )

    results = recommendations.generate_recommendations(
        "run-123",
        user_id="default",
        profile_id="profile-1",
    )

    assert [result["rank"] for result in results] == [1, 2]
    assert [result["arxiv_id"] for result in results] == ["2601.00001", "2601.00002"]
    assert cursor.executemany.call_count == 1
    assert cursor.execute.call_count == 5

    delete_params = cursor.execute.call_args_list[4].args[1]
    assert delete_params == ("run-123", "profile-1")

    inserted_rows = cursor.executemany.call_args.args[1]
    assert inserted_rows[0][0] == "rec-1"
    assert inserted_rows[0][3] == "2601.00001"
    assert inserted_rows[0][4] == 1
    assert inserted_rows[0][5] == 0.8
    assert inserted_rows[0][6] == 0.1
    assert inserted_rows[0][7] == 0.9
    assert inserted_rows[0][8] == "7d"
    assert inserted_rows[0][9] == 0


def test_generate_recommendations_respects_k_override(monkeypatch):
    cursor = MagicMock()
    cursor.fetchone.side_effect = [(1,), ("run-123", "cs.AI", 150)]
    cursor.fetchall.return_value = []

    connect, _ = _mock_connection_with_cursor(cursor)
    monkeypatch.setattr(recommendations.psycopg, "connect", connect)
    monkeypatch.setattr(recommendations, "get_daily_picks_k", Mock(return_value=3))
    monkeypatch.setattr(
        recommendations, "get_keyword_boost_cap", Mock(return_value=0.25)
    )

    recommendations.generate_recommendations(
        "run-123",
        user_id="default",
        profile_id="profile-1",
        k_override=2,
    )

    rank_params = cursor.execute.call_args_list[2].args[1]
    assert rank_params == (
        "run-123",
        "profile-1",
        "profile-1",
        "profile-1",
        "profile-1",
        0.25,
        0.25,
        "profile-1",
        2,
    )


def test_generate_recommendations_rejects_invalid_override(monkeypatch):
    cursor = MagicMock()
    cursor.fetchone.side_effect = [(1,), ("run-123", "cs.AI", 150)]

    connect, _ = _mock_connection_with_cursor(cursor)
    monkeypatch.setattr(recommendations.psycopg, "connect", connect)

    with pytest.raises(ValueError, match="k_override must be >= 1"):
        recommendations.generate_recommendations(
            "run-123",
            user_id="default",
            profile_id="profile-1",
            k_override=0,
        )


def test_rank_sql_uses_seven_day_primary_window():
    sql = RANK_CANDIDATES_SQL
    assert "run_window" not in sql
    assert "run_rank" not in sql
    assert "max_results" not in sql
    assert "'run'::text" not in sql
    assert "all_seen_neutral" not in sql
    assert "stage4" not in sql
    assert "status IN ('completed', 'failed')" in sql
    assert "status IN ('completed', 'failed')" in FETCH_RUN_SQL
    stage0_sql = sql[sql.index("stage0 AS") : sql.index("stage1 AS")]
    assert "INTERVAL '7 days'" in stage0_sql
    assert "'7d'::text" in stage0_sql
    assert "sp.arxiv_id IS NULL" in stage0_sql
    assert sql.index("'7d'::text") < sql.index("'30d'::text")
    assert sql.index("'30d'::text") < sql.index("'1y'::text")
    assert sql.index("'1y'::text") < sql.index("'all'::text")
    prioritized = sql[sql.index("prioritized AS") : sql.index("ranked AS")]
    assert prioritized.index("fallback_stage ASC") < prioritized.index("LIMIT %s")


def _database_url_reachable() -> bool:
    if not os.getenv("DATABASE_URL", "").strip():
        return False
    try:
        check_database_connection(connect_timeout=2)
    except Exception:
        return False
    return True


def _unit_vector(*nonzero: tuple[int, float]) -> str:
    values = [0.0] * 384
    for index, value in nonzero:
        values[index] = value
    return vector_literal(values)


def _rank_candidates(cur, *, run_id: str, profile_id: str, k: int):
    cur.execute(
        RANK_CANDIDATES_SQL,
        (
            run_id,
            profile_id,
            profile_id,
            profile_id,
            profile_id,
            0.25,
            0.25,
            profile_id,
            k,
        ),
    )
    return cur.fetchall()


def _seed_rank_case(cur, *, papers: list[dict], seen: list[str]):
    suffix = uuid.uuid4().hex
    user_id = f"test-rank-{suffix}"
    profile_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    prior_run_id = str(uuid.uuid4())
    pref = _unit_vector((0, 1.0))

    cur.execute(
        """
        INSERT INTO user_profiles (
            profile_id, user_id, profile_slot, profile_name, category, interest_sentence
        )
        VALUES (%s, %s, 1, 'Rank test', 'cs.AI', 'ranking sql fixture')
        """,
        (profile_id, user_id),
    )
    cur.execute(
        """
        INSERT INTO profile_preferences (
            profile_id, initial_interest_embedding, preference_embedding
        )
        VALUES (%s, %s::vector, %s::vector)
        """,
        (profile_id, pref, pref),
    )
    cur.execute(
        """
        INSERT INTO runs (run_id, status, category, max_results)
        VALUES (%s, 'completed', 'cs.AI', 150), (%s, 'failed', 'cs.AI', 150)
        """,
        (run_id, prior_run_id),
    )

    for paper in papers:
        cur.execute(
            """
            INSERT INTO papers (
                arxiv_id, title, abstract, published_at, categories
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                paper["arxiv_id"],
                paper["title"],
                paper.get("abstract", "abstract"),
                paper["published_at"],
                ["cs.AI"],
            ),
        )
        cur.execute(
            """
            INSERT INTO paper_embeddings (arxiv_id, embedding, model_name)
            VALUES (%s, %s::vector, 'test')
            """,
            (paper["arxiv_id"], paper["embedding"]),
        )

    for arxiv_id in seen:
        cur.execute(
            """
            INSERT INTO recommendations (
                recommendation_id, run_id, profile_id, arxiv_id, rank,
                final_score, candidate_window, fallback_stage
            )
            VALUES (%s, %s, %s, %s, 1, 0, '7d', 0)
            """,
            (str(uuid.uuid4()), prior_run_id, profile_id, arxiv_id),
        )

    return run_id, profile_id


def _ranked_windows(rows):
    return [(row[1], int(row[4]), row[5]) for row in rows]


@pytest.mark.skipif(
    not _database_url_reachable(), reason="DATABASE_URL is not reachable"
)
def test_rank_sql_seven_day_window_beats_older_higher_score():
    now = datetime.now(UTC)
    newest = f"test.rank.{uuid.uuid4().hex}.new"
    midweek = f"test.rank.{uuid.uuid4().hex}.mid"
    old_best = f"test.rank.{uuid.uuid4().hex}.old"
    orthogonal = _unit_vector((1, 1.0))
    perfect = _unit_vector((0, 1.0))

    with psycopg.connect(get_database_url()) as conn:
        try:
            with conn.cursor() as cur:
                run_id, profile_id = _seed_rank_case(
                    cur,
                    papers=[
                        {
                            "arxiv_id": newest,
                            "title": "Newest weak match",
                            "published_at": now - timedelta(hours=1),
                            "embedding": orthogonal,
                        },
                        {
                            "arxiv_id": midweek,
                            "title": "Midweek weak match",
                            "published_at": now - timedelta(days=2),
                            "embedding": orthogonal,
                        },
                        {
                            "arxiv_id": old_best,
                            "title": "Old perfect match",
                            "published_at": now - timedelta(days=60),
                            "embedding": perfect,
                        },
                    ],
                    seen=[],
                )
                rows = _rank_candidates(cur, run_id=run_id, profile_id=profile_id, k=2)
        finally:
            conn.rollback()

    assert _ranked_windows(rows) == [
        (newest, 0, "7d"),
        (midweek, 0, "7d"),
    ]


@pytest.mark.skipif(
    not _database_url_reachable(), reason="DATABASE_URL is not reachable"
)
def test_rank_sql_fallback_fills_when_seven_day_pool_is_short():
    now = datetime.now(UTC)
    newest = f"test.rank.{uuid.uuid4().hex}.new"
    old_best = f"test.rank.{uuid.uuid4().hex}.old"
    orthogonal = _unit_vector((1, 1.0))
    perfect = _unit_vector((0, 1.0))

    with psycopg.connect(get_database_url()) as conn:
        try:
            with conn.cursor() as cur:
                run_id, profile_id = _seed_rank_case(
                    cur,
                    papers=[
                        {
                            "arxiv_id": newest,
                            "title": "Newest weak match",
                            "published_at": now - timedelta(hours=1),
                            "embedding": orthogonal,
                        },
                        {
                            "arxiv_id": old_best,
                            "title": "Old perfect match",
                            "published_at": now - timedelta(days=60),
                            "embedding": perfect,
                        },
                    ],
                    seen=[],
                )
                rows = _rank_candidates(cur, run_id=run_id, profile_id=profile_id, k=2)
        finally:
            conn.rollback()

    assert _ranked_windows(rows) == [
        (newest, 0, "7d"),
        (old_best, 2, "1y"),
    ]


@pytest.mark.skipif(
    not _database_url_reachable(), reason="DATABASE_URL is not reachable"
)
def test_rank_sql_skips_digest_sent_papers_inside_seven_day_window():
    now = datetime.now(UTC)
    newest = f"test.rank.{uuid.uuid4().hex}.new"
    next_unseen = f"test.rank.{uuid.uuid4().hex}.next"
    orthogonal = _unit_vector((1, 1.0))

    with psycopg.connect(get_database_url()) as conn:
        try:
            with conn.cursor() as cur:
                run_id, profile_id = _seed_rank_case(
                    cur,
                    papers=[
                        {
                            "arxiv_id": newest,
                            "title": "Already sent",
                            "published_at": now - timedelta(hours=1),
                            "embedding": orthogonal,
                        },
                        {
                            "arxiv_id": next_unseen,
                            "title": "Next unseen",
                            "published_at": now - timedelta(days=2),
                            "embedding": orthogonal,
                        },
                    ],
                    seen=[newest],
                )
                rows = _rank_candidates(cur, run_id=run_id, profile_id=profile_id, k=1)
        finally:
            conn.rollback()

    assert _ranked_windows(rows) == [(next_unseen, 0, "7d")]


@pytest.mark.skipif(
    not _database_url_reachable(), reason="DATABASE_URL is not reachable"
)
def test_rank_sql_six_day_match_can_beat_weaker_paper_from_today():
    now = datetime.now(UTC)
    today_weak = f"test.rank.{uuid.uuid4().hex}.today"
    week_best = f"test.rank.{uuid.uuid4().hex}.week"
    orthogonal = _unit_vector((1, 1.0))
    perfect = _unit_vector((0, 1.0))

    with psycopg.connect(get_database_url()) as conn:
        try:
            with conn.cursor() as cur:
                run_id, profile_id = _seed_rank_case(
                    cur,
                    papers=[
                        {
                            "arxiv_id": today_weak,
                            "title": "Today weak match",
                            "published_at": now - timedelta(hours=1),
                            "embedding": orthogonal,
                        },
                        {
                            "arxiv_id": week_best,
                            "title": "Six day perfect match",
                            "published_at": now - timedelta(days=6),
                            "embedding": perfect,
                        },
                    ],
                    seen=[],
                )
                rows = _rank_candidates(cur, run_id=run_id, profile_id=profile_id, k=1)
        finally:
            conn.rollback()

    assert _ranked_windows(rows) == [(week_best, 0, "7d")]

