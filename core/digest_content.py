"""
Load digest sections from recommendations for email delivery
"""

from dataclasses import dataclass

from core.arxiv_text import format_arxiv_display_text
from core.db import connection_scope
from core.profiles import get_profile
from core.recommendation_query_fragments import LATEST_RUN_FOR_PROFILE_AND_RUNS_CTE

LATEST_PICKS_FOR_RUNS_SQL = (
    LATEST_RUN_FOR_PROFILE_AND_RUNS_CTE
    + """
SELECT
    rec.rank,
    p.arxiv_id,
    p.title,
    d.description,
    p.pdf_url,
    rec.final_score
FROM latest_run lr
JOIN recommendations rec
  ON rec.run_id = lr.run_id
 AND rec.profile_id = %s
JOIN papers p ON p.arxiv_id = rec.arxiv_id
LEFT JOIN descriptions d ON d.arxiv_id = p.arxiv_id
ORDER BY rec.rank ASC;
"""
)


@dataclass(frozen=True)
class DigestPick:
    rank: int
    arxiv_id: str
    title: str
    description: str | None
    pdf_url: str | None
    final_score: float


@dataclass(frozen=True)
class DigestSection:
    profile_name: str
    profile_slot: int
    category: str
    picks: tuple[DigestPick, ...]


def _section_heading(profile_name: str, profile_slot: int) -> str:
    name = profile_name.strip()
    if name:
        return name
    return f"Profile {profile_slot}"


def build_digest_sections(
    *,
    user_id: str,
    profile_ids: list[str],
    run_ids: list[str],
    conn=None,
) -> list[DigestSection]:
    if not profile_ids or not run_ids:
        return []

    unique_run_ids = list(dict.fromkeys(run_ids))
    sections: list[DigestSection] = []

    with connection_scope(conn) as active_conn:
        for profile_id in profile_ids:
            profile = get_profile(profile_id=profile_id, conn=active_conn)
            if profile is None or profile.user_id != user_id:
                continue

            with active_conn.cursor() as cur:
                cur.execute(
                    LATEST_PICKS_FOR_RUNS_SQL,
                    (profile_id, unique_run_ids, profile_id),
                )
                rows = cur.fetchall()

            if not rows:
                continue

            picks = tuple(
                DigestPick(
                    rank=int(row[0]),
                    arxiv_id=row[1],
                    title=format_arxiv_display_text(row[2]),
                    description=format_arxiv_display_text(row[3]) if row[3] else None,
                    pdf_url=row[4],
                    final_score=float(row[5]),
                )
                for row in rows
            )
            sections.append(
                DigestSection(
                    profile_name=_section_heading(
                        profile.profile_name,
                        profile.profile_slot,
                    ),
                    profile_slot=profile.profile_slot,
                    category=profile.category,
                    picks=picks,
                )
            )

    return sections


def count_digest_picks(sections: list[DigestSection]) -> int:
    return sum(len(section.picks) for section in sections)
