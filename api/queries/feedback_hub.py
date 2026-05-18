"""
SQL queries for the feedback hub
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

USER_PAPER_HISTORY_SQL = """
SELECT
    rec.arxiv_id,
    COALESCE(p.title, rec.arxiv_id) AS title,
    p.pdf_url,
    rec.profile_id::text,
    up.profile_name,
    r.category,
    rec.generated_at,
    rec.final_score,
    rec.rank,
    pf.label
FROM recommendations rec
JOIN user_profiles up ON up.profile_id = rec.profile_id
JOIN papers p ON p.arxiv_id = rec.arxiv_id
JOIN runs r ON r.run_id = rec.run_id
LEFT JOIN paper_feedback pf
  ON pf.profile_id = rec.profile_id
 AND pf.arxiv_id = rec.arxiv_id
WHERE up.user_id = %s
  AND (%s::uuid IS NULL OR rec.profile_id = %s::uuid)
ORDER BY DATE(rec.generated_at) DESC, rec.final_score DESC, rec.rank ASC;
"""


@dataclass(frozen=True)
class UserPaperHistoryRow:
    arxiv_id: str
    title: str
    pdf_url: str | None
    profile_id: str
    profile_name: str
    category: str
    generated_at: datetime
    final_score: float
    rank: int
    feedback_label: str | None


def fetch_user_paper_history(
    user_id: str,
    connect: Callable,
    database_url: str,
    conn=None,
    profile_id: str | None = None,
) -> list[UserPaperHistoryRow]:
    params = (user_id, profile_id, profile_id)
    if conn is None:
        with connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(USER_PAPER_HISTORY_SQL, params)
                rows = cur.fetchall()
    else:
        with conn.cursor() as cur:
            cur.execute(USER_PAPER_HISTORY_SQL, params)
            rows = cur.fetchall()

    return [
        UserPaperHistoryRow(
            arxiv_id=row[0],
            title=row[1],
            pdf_url=row[2],
            profile_id=row[3],
            profile_name=row[4],
            category=row[5],
            generated_at=row[6],
            final_score=float(row[7]),
            rank=int(row[8]),
            feedback_label=row[9],
        )
        for row in rows
    ]
