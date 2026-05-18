"""
Tests for feedback hub query and service
"""

from datetime import datetime, timezone

from api.queries.feedback_hub import UserPaperHistoryRow
from api.services.feedback_hub import get_feedback_hub_payload


def _row(
    arxiv_id: str,
    *,
    generated_at: datetime,
    final_score: float,
    feedback_label: str | None = None,
    profile_id: str = "p-1",
    profile_name: str = "Research",
) -> UserPaperHistoryRow:
    return UserPaperHistoryRow(
        arxiv_id=arxiv_id,
        title=f"Paper {arxiv_id}",
        pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
        profile_id=profile_id,
        profile_name=profile_name,
        category="cs.AI",
        generated_at=generated_at,
        final_score=final_score,
        rank=1,
        feedback_label=feedback_label,
    )


def test_get_feedback_hub_splits_sections():
    older = datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc)
    newer = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc)

    rows = [
        _row("seen-1", generated_at=newer, final_score=0.9, feedback_label=None),
        _row("liked-1", generated_at=newer, final_score=0.8, feedback_label="like"),
        _row("disliked-1", generated_at=older, final_score=0.7, feedback_label="dislike"),
    ]

    payload = get_feedback_hub_payload(
        user_id="user-1",
        fetch_user_paper_history=lambda _uid, profile_id=None: rows,
    )

    assert payload["user_id"] == "user-1"
    assert [p["arxiv_id"] for p in payload["seen"]] == ["seen-1"]
    assert [p["arxiv_id"] for p in payload["liked"]] == ["liked-1"]
    assert [p["arxiv_id"] for p in payload["disliked"]] == ["disliked-1"]
    assert payload["seen"][0]["profile_name"] == "Research"
    assert payload["seen"][0]["category"] == "cs.AI"
    assert payload["seen"][0]["final_score"] == 0.9


def test_get_feedback_hub_passes_profile_filter():
    captured = {}

    def fetch(user_id, profile_id=None):
        captured["user_id"] = user_id
        captured["profile_id"] = profile_id
        return []

    get_feedback_hub_payload(
        user_id="user-1",
        profile_id="profile-abc",
        fetch_user_paper_history=fetch,
    )

    assert captured == {"user_id": "user-1", "profile_id": "profile-abc"}
