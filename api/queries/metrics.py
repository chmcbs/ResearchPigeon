"""
SQL queries for API metrics endpoint
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

RUN_STATUS_COUNTS_SQL = """
SELECT status, COUNT(*)
FROM runs
GROUP BY status
ORDER BY status ASC;
"""

LATEST_RUNS_SQL = """
SELECT
    run_id::text,
    status,
    category,
    max_results,
    fetched_count,
    saved_count,
    started_at,
    finished_at,
    error_message
FROM runs
ORDER BY started_at DESC
LIMIT %s;
"""

RECOMMENDATION_TOTAL_SQL = """
SELECT COUNT(*)
FROM recommendations;
"""

RECOMMENDATIONS_BY_PROFILE_SQL = """
SELECT profile_id::text, COUNT(*)
FROM recommendations
GROUP BY profile_id
ORDER BY profile_id ASC;
"""


@dataclass(frozen=True)
class LatestRunRow:
    run_id: str
    status: str
    category: str
    max_results: int
    fetched_count: int
    saved_count: int
    started_at: datetime
    finished_at: datetime | None
    error_message: str | None


@dataclass(frozen=True)
class MetricsRowSet:
    run_status_counts: dict[str, int]
    latest_runs: list[LatestRunRow]
    total_recommendations: int
    recommendations_by_profile: dict[str, int]


def _load_latest_run_rows(rows) -> list[LatestRunRow]:
    return [
        LatestRunRow(
            run_id=row[0],
            status=row[1],
            category=row[2],
            max_results=int(row[3]),
            fetched_count=int(row[4] or 0),
            saved_count=int(row[5] or 0),
            started_at=row[6],
            finished_at=row[7],
            error_message=row[8],
        )
        for row in rows
    ]


def fetch_metrics_rows(
    latest_runs_limit: int,
    connect: Callable,
    database_url: str,
    conn=None,
) -> MetricsRowSet:
    def _query(cur) -> MetricsRowSet:
        cur.execute(RUN_STATUS_COUNTS_SQL)
        run_status_counts = {status: int(count) for status, count in cur.fetchall()}

        cur.execute(LATEST_RUNS_SQL, (latest_runs_limit,))
        latest_runs = _load_latest_run_rows(cur.fetchall())

        cur.execute(RECOMMENDATION_TOTAL_SQL)
        total_recommendations = int(cur.fetchone()[0])

        cur.execute(RECOMMENDATIONS_BY_PROFILE_SQL)
        recommendations_by_profile = {
            profile_id: int(count) for profile_id, count in cur.fetchall()
        }

        return MetricsRowSet(
            run_status_counts=run_status_counts,
            latest_runs=latest_runs,
            total_recommendations=total_recommendations,
            recommendations_by_profile=recommendations_by_profile,
        )

    if conn is None:
        with connect(database_url) as active_conn:
            with active_conn.cursor() as cur:
                return _query(cur)

    with conn.cursor() as cur:
        return _query(cur)
