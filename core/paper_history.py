"""
Permanent paper dismissal for a profile
"""

from core.db import connection_scope
from core.preferences import remove_feedback, update_preference_embedding
from core.profiles import require_profile_id

DELETE_PROFILE_RECOMMENDATIONS_FOR_PAPER_SQL = """
DELETE FROM recommendations
WHERE profile_id = %s
  AND arxiv_id = %s;
"""

INSERT_DISMISSED_PAPER_SQL = """
INSERT INTO profile_dismissed_papers (profile_id, arxiv_id)
VALUES (%s, %s)
ON CONFLICT (profile_id, arxiv_id) DO NOTHING;
"""


def dismiss_paper(
    arxiv_id: str,
    user_id: str,
    profile_id: str | None = None,
    conn=None,
) -> dict:
    resolved_profile_id = require_profile_id(
        user_id=user_id, profile_id=profile_id, conn=conn
    )

    feedback_removed = remove_feedback(
        arxiv_id=arxiv_id,
        user_id=user_id,
        profile_id=resolved_profile_id,
        conn=conn,
    )

    with connection_scope(conn) as active_conn:
        with active_conn.cursor() as cur:
            cur.execute(
                DELETE_PROFILE_RECOMMENDATIONS_FOR_PAPER_SQL,
                (resolved_profile_id, arxiv_id),
            )
            recommendations_removed = cur.rowcount
            cur.execute(
                INSERT_DISMISSED_PAPER_SQL,
                (resolved_profile_id, arxiv_id),
            )

    if feedback_removed:
        update_preference_embedding(
            user_id=user_id,
            profile_id=resolved_profile_id,
            conn=conn,
        )

    return {
        "profile_id": resolved_profile_id,
        "arxiv_id": arxiv_id,
        "feedback_removed": feedback_removed,
        "recommendations_removed": recommendations_removed,
        "preference_updated": feedback_removed,
        "dismissed": True,
    }
