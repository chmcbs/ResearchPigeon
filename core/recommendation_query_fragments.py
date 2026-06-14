"""
Shared SQL fragments for recommendation read queries
"""

LATEST_RUN_FOR_PROFILE_AND_RUNS_CTE = """
WITH latest_run AS (
    SELECT
        run_id,
        MAX(generated_at) AS generated_at
    FROM recommendations
    WHERE profile_id = %s
      AND run_id::text = ANY(%s)
    GROUP BY run_id
    ORDER BY MAX(generated_at) DESC
    LIMIT 1
)
"""
