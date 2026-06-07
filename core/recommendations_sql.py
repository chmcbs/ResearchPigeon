"""
SQL constants for recommendation generation
"""

from core.keyword_search import SEARCH_DICTIONARY, paper_search_vector_sql

FETCH_RUN_SQL = """
SELECT run_id, category, max_results
FROM runs
WHERE run_id = %s
  AND status = 'completed';
"""

FETCH_EFFECTIVE_K_SQL = """
SELECT COALESCE(daily_k, %s)
FROM profile_preferences
WHERE profile_id = %s;
"""

RANK_CANDIDATES_SQL = f"""
WITH run_context AS (
    SELECT category, max_results
    FROM runs
    WHERE run_id = %s
      AND status = 'completed'
),
preference_context AS (
    SELECT preference_embedding
    FROM profile_preferences
    WHERE profile_id = %s
),
feedback_excluded AS (
    SELECT DISTINCT arxiv_id
    FROM paper_feedback
    WHERE profile_id = %s
      AND label IN ('like', 'dislike')
    UNION
    SELECT arxiv_id
    FROM profile_dismissed_papers
    WHERE profile_id = %s
),
seen_papers AS (
    SELECT DISTINCT arxiv_id
    FROM recommendations
    WHERE profile_id = %s
),
base_papers AS (
    SELECT
        p.arxiv_id,
        p.title,
        p.abstract,
        p.published_at,
        e.embedding
    FROM papers p
    JOIN paper_embeddings e ON e.arxiv_id = p.arxiv_id
    JOIN run_context rc ON rc.category = ANY(p.categories)
    LEFT JOIN feedback_excluded fe ON fe.arxiv_id = p.arxiv_id
    WHERE fe.arxiv_id IS NULL
),
run_window AS (
    SELECT
        bp.*,
        ROW_NUMBER() OVER (
            ORDER BY bp.published_at DESC NULLS LAST, bp.arxiv_id ASC
        ) AS run_rank
    FROM base_papers bp
),
stage0 AS (
    SELECT
        rw.arxiv_id,
        rw.title,
        rw.abstract,
        rw.published_at,
        rw.embedding,
        0::smallint AS fallback_stage,
        'run'::text AS candidate_window
    FROM run_window rw
    CROSS JOIN run_context rc
    LEFT JOIN seen_papers sp ON sp.arxiv_id = rw.arxiv_id
    WHERE rw.run_rank <= rc.max_results
      AND sp.arxiv_id IS NULL
),
stage1 AS (
    SELECT
        bp.arxiv_id,
        bp.title,
        bp.abstract,
        bp.published_at,
        bp.embedding,
        1::smallint AS fallback_stage,
        '7d'::text AS candidate_window
    FROM base_papers bp
    LEFT JOIN seen_papers sp ON sp.arxiv_id = bp.arxiv_id
    WHERE bp.published_at >= NOW() - INTERVAL '7 days'
      AND sp.arxiv_id IS NULL
),
stage2 AS (
    SELECT
        bp.arxiv_id,
        bp.title,
        bp.abstract,
        bp.published_at,
        bp.embedding,
        2::smallint AS fallback_stage,
        '30d'::text AS candidate_window
    FROM base_papers bp
    LEFT JOIN seen_papers sp ON sp.arxiv_id = bp.arxiv_id
    WHERE bp.published_at >= NOW() - INTERVAL '30 days'
      AND sp.arxiv_id IS NULL
),
stage3 AS (
    SELECT
        bp.arxiv_id,
        bp.title,
        bp.abstract,
        bp.published_at,
        bp.embedding,
        3::smallint AS fallback_stage,
        '1y'::text AS candidate_window
    FROM base_papers bp
    LEFT JOIN seen_papers sp ON sp.arxiv_id = bp.arxiv_id
    WHERE bp.published_at >= NOW() - INTERVAL '1 year'
      AND sp.arxiv_id IS NULL
),
stage4 AS (
    SELECT
        bp.arxiv_id,
        bp.title,
        bp.abstract,
        bp.published_at,
        bp.embedding,
        4::smallint AS fallback_stage,
        'all'::text AS candidate_window
    FROM base_papers bp
    LEFT JOIN seen_papers sp ON sp.arxiv_id = bp.arxiv_id
    WHERE sp.arxiv_id IS NULL
),
stage5 AS (
    SELECT
        bp.arxiv_id,
        bp.title,
        bp.abstract,
        bp.published_at,
        bp.embedding,
        5::smallint AS fallback_stage,
        'all_seen_neutral'::text AS candidate_window
    FROM base_papers bp
    JOIN seen_papers sp ON sp.arxiv_id = bp.arxiv_id
),
all_candidates AS (
    SELECT * FROM stage0
    UNION ALL
    SELECT * FROM stage1
    UNION ALL
    SELECT * FROM stage2
    UNION ALL
    SELECT * FROM stage3
    UNION ALL
    SELECT * FROM stage4
    UNION ALL
    SELECT * FROM stage5
),
scored AS (
    SELECT
        c.arxiv_id,
        c.title,
        c.abstract,
        c.published_at,
        c.fallback_stage,
        c.candidate_window,
        1 - (c.embedding <=> pc.preference_embedding) AS base_dense_score,
        LEAST(
            COALESCE(keyword_scores.keyword_score_sum, 0.0),
            %s
        ) AS keyword_boost,
        (1 - (c.embedding <=> pc.preference_embedding)) + LEAST(
            COALESCE(keyword_scores.keyword_score_sum, 0.0),
            %s
        ) AS final_score
    FROM all_candidates c
    CROSS JOIN preference_context pc
    LEFT JOIN LATERAL (
        SELECT
            SUM(
                ts_rank_cd(
                    {paper_search_vector_sql("c")},
                    websearch_to_tsquery('{SEARCH_DICTIONARY}', pk.keyword)
                )
            ) AS keyword_score_sum
        FROM profile_keywords pk
        WHERE pk.profile_id = %s
          AND {paper_search_vector_sql("c")} @@ websearch_to_tsquery('{SEARCH_DICTIONARY}', pk.keyword)
    ) AS keyword_scores ON TRUE
),
deduped AS (
    SELECT DISTINCT ON (arxiv_id)
        arxiv_id,
        title,
        abstract,
        published_at,
        fallback_stage,
        candidate_window,
        base_dense_score,
        keyword_boost,
        final_score
    FROM scored
    ORDER BY
        arxiv_id,
        fallback_stage ASC,
        final_score DESC,
        published_at DESC NULLS LAST
),
prioritized AS (
    SELECT
        arxiv_id,
        title,
        abstract,
        published_at,
        fallback_stage,
        candidate_window,
        base_dense_score,
        keyword_boost,
        final_score
    FROM deduped
    ORDER BY
        fallback_stage ASC,
        final_score DESC,
        published_at DESC NULLS LAST,
        arxiv_id ASC
    LIMIT %s
),
ranked AS (
    SELECT
        ROW_NUMBER() OVER (
            ORDER BY
                fallback_stage ASC,
                final_score DESC,
                published_at DESC NULLS LAST,
                arxiv_id ASC
        ) AS rank,
        arxiv_id,
        title,
        abstract,
        fallback_stage,
        candidate_window,
        base_dense_score,
        keyword_boost,
        final_score
    FROM prioritized
)
SELECT
    rank,
    arxiv_id,
    title,
    abstract,
    fallback_stage,
    candidate_window,
    base_dense_score,
    keyword_boost,
    final_score
FROM ranked
ORDER BY rank ASC;
"""

DELETE_EXISTING_SQL = """
DELETE FROM recommendations
WHERE run_id = %s
  AND profile_id = %s;
"""

INSERT_RECOMMENDATION_SQL = """
INSERT INTO recommendations (
    recommendation_id,
    run_id,
    profile_id,
    arxiv_id,
    rank,
    base_dense_score,
    keyword_boost,
    final_score,
    candidate_window,
    fallback_stage
)
VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
);
"""
