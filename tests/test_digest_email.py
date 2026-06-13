"""
Tests for digest email formatting and delivery
"""

from datetime import UTC, datetime
from unittest.mock import Mock, patch

import pytest

from core.digest_content import DigestPick, DigestSection
from core.digest_email import (
    build_digest_email_body,
    build_digest_email_html,
    build_digest_email_subject,
    deliver_digest_email_for_user,
    format_pick_plain_lines,
    score_display_percent,
    send_digest_email,
    star_rating_from_percent,
    stars_display,
)
from core.email import EmailDeliveryError


def _sample_section(**kwargs) -> DigestSection:
    defaults = {
        "profile_name": "ML Papers",
        "profile_slot": 1,
        "category": "cs.LG",
        "picks": (),
    }
    defaults.update(kwargs)
    return DigestSection(**defaults)


def test_score_display_percent_clamps_to_range():
    assert score_display_percent(0.0) == 0
    assert score_display_percent(0.78) == 78
    assert score_display_percent(1.5) == 100


def test_star_rating_from_percent_matches_web_thresholds():
    assert star_rating_from_percent(54) == 0
    assert star_rating_from_percent(55) == 1
    assert star_rating_from_percent(65) == 2
    assert star_rating_from_percent(75) == 3


def test_stars_display_uses_star_emoji():
    assert stars_display(80) == "⭐⭐⭐"
    assert stars_display(40) == ""


def test_format_pick_plain_lines_puts_stars_below_title_and_blurb():
    pick = DigestPick(
        rank=1,
        arxiv_id="2601.00001",
        title="Sample Paper",
        description="Adds a new training trick.",
        pdf_url="https://arxiv.org/pdf/2601.00001",
        final_score=0.78,
    )
    lines = format_pick_plain_lines(1, pick)
    assert lines == [
        "1. Sample Paper",
        "   Adds a new training trick.",
        "   ⭐⭐⭐",
        "   https://arxiv.org/pdf/2601.00001",
    ]


def test_build_digest_email_subject_includes_date():
    subject = build_digest_email_subject(
        generated_at=datetime(2026, 6, 2, tzinfo=UTC),
    )
    assert subject == "Your daily research digest — 2 Jun 2026"


def test_build_digest_email_body_includes_picks_stars_category_and_footer(monkeypatch):
    monkeypatch.setenv("APP_BASE_URL", "http://localhost:8000")
    sections = [
        _sample_section(
            picks=(
                DigestPick(
                    rank=1,
                    arxiv_id="2601.00001",
                    title="Sample Paper",
                    description="Adds a new training trick.",
                    pdf_url="https://arxiv.org/pdf/2601.00001",
                    final_score=0.78,
                ),
            ),
        )
    ]

    body = build_digest_email_body(sections)

    assert "ML Papers · cs.LG" in body
    assert "1. Sample Paper" in body
    assert "Adds a new training trick." in body
    assert "   ⭐⭐⭐" in body
    assert "% match" not in body
    assert "https://arxiv.org/pdf/2601.00001" in body
    assert "Rate papers: http://localhost:8000/papers" in body
    assert "Manage preferences: http://localhost:8000/profiles" in body
    assert "Unsubscribe: http://localhost:8000/email/unsubscribe" in body
    assert "Not affiliated with arXiv" in body


def test_build_digest_email_html_matches_preview_layout(monkeypatch):
    monkeypatch.setenv("APP_BASE_URL", "http://localhost:8000")
    sections = [
        _sample_section(
            picks=(
                DigestPick(
                    rank=1,
                    arxiv_id="2601.00001",
                    title="Sample Paper",
                    description="Adds a new training trick.",
                    pdf_url="https://arxiv.org/pdf/2601.00001",
                    final_score=0.78,
                ),
            ),
        )
    ]

    html = build_digest_email_html(sections)

    assert ">cs.LG</td>" in html
    assert "Sample Paper" in html
    assert "Adds a new training trick." in html
    assert "⭐⭐⭐" in html
    assert 'href="http://localhost:8000/papers"' in html
    assert "Rate papers" in html
    assert 'href="http://localhost:8000/profiles"' in html
    assert "Manage preferences" in html
    assert "Unsubscribe from digest emails" in html
    assert html.index("Rate papers") < html.index("Manage preferences")
    assert "text-align:center" in html
    assert 'align="center"' in html
    assert "<h1" in html
    assert html.index("<h1") < html.index("background:#ffffff")
    assert html.index("background:#ffffff") < html.index("Not affiliated with arXiv")
    assert "text-align:center" in html.split("background:#ffffff")[0]
    assert "% match" not in html


def test_build_digest_email_html_separates_profile_sections(monkeypatch):
    monkeypatch.setenv("APP_BASE_URL", "http://localhost:8000")
    pick = DigestPick(
        rank=1,
        arxiv_id="2601.00001",
        title="Sample Paper",
        description=None,
        pdf_url="https://arxiv.org/pdf/2601.00001",
        final_score=0.78,
    )
    sections = [
        _sample_section(profile_name="ML Papers", profile_slot=1, category="cs.LG", picks=(pick,)),
        _sample_section(profile_name="Vision", profile_slot=2, category="cs.CV", picks=(pick,)),
    ]

    html = build_digest_email_html(sections)

    assert html.count("border-top:1px solid #e5e7eb") >= 2


def test_build_digest_email_body_omits_blurb_and_stars_when_missing(monkeypatch):
    monkeypatch.setenv("APP_BASE_URL", "http://localhost:8000")
    sections = [
        _sample_section(
            profile_name="Profile 2",
            profile_slot=2,
            category="cs.AI",
            picks=(
                DigestPick(
                    rank=1,
                    arxiv_id="2601.00002",
                    title="No Blurb Paper",
                    description=None,
                    pdf_url=None,
                    final_score=0.4,
                ),
            ),
        )
    ]

    body = build_digest_email_body(sections)

    assert "1. No Blurb Paper" in body
    assert "https://arxiv.org/abs/2601.00002" in body
    assert "⭐" not in body


def test_deliver_digest_email_for_user_skips_when_unconfigured(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("EMAIL_FROM", raising=False)

    result = deliver_digest_email_for_user(
        user_id="reader@example.com",
        profile_ids=["profile-1"],
        run_ids=["run-1"],
    )

    assert result == {"status": "skipped_unconfigured", "error_message": None}


def test_deliver_digest_email_for_user_skips_when_no_picks(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "mailpit")
    monkeypatch.setenv("EMAIL_FROM", "noreply@localhost")
    monkeypatch.setattr(
        "core.digest_email.build_digest_sections",
        Mock(return_value=[]),
    )

    result = deliver_digest_email_for_user(
        user_id="reader@example.com",
        profile_ids=["profile-1"],
        run_ids=["run-1"],
    )

    assert result == {"status": "skipped_no_picks", "error_message": None}


def test_deliver_digest_email_for_user_sends_when_picks_exist(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "mailpit")
    monkeypatch.setenv("EMAIL_FROM", "noreply@localhost")
    sections = [
        _sample_section(
            picks=(
                DigestPick(
                    rank=1,
                    arxiv_id="2601.00001",
                    title="Sample Paper",
                    description=None,
                    pdf_url="https://arxiv.org/pdf/2601.00001",
                    final_score=0.5,
                ),
            ),
        )
    ]
    monkeypatch.setattr(
        "core.digest_email.build_digest_sections",
        Mock(return_value=sections),
    )
    monkeypatch.setattr("core.digest_email.ensure_email_settings", Mock())
    monkeypatch.setattr(
        "core.digest_email.build_unsubscribe_url",
        Mock(return_value="http://localhost:8000/email/unsubscribe?token=abc"),
    )
    send = Mock()
    monkeypatch.setattr("core.digest_email.send_digest_email", send)

    result = deliver_digest_email_for_user(
        user_id="reader@example.com",
        profile_ids=["profile-1"],
        run_ids=["run-1"],
    )

    assert result == {"status": "sent", "error_message": None}
    send.assert_called_once()
    assert send.call_args.kwargs["to_email"] == "reader@example.com"
    assert "plain_body" in send.call_args.kwargs
    assert "html_body" in send.call_args.kwargs


def test_deliver_digest_email_for_user_logs_failure_without_raising(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "mailpit")
    monkeypatch.setenv("EMAIL_FROM", "noreply@localhost")
    sections = [
        _sample_section(
            picks=(
                DigestPick(
                    rank=1,
                    arxiv_id="2601.00001",
                    title="Sample Paper",
                    description=None,
                    pdf_url="https://arxiv.org/pdf/2601.00001",
                    final_score=0.5,
                ),
            ),
        )
    ]
    monkeypatch.setattr(
        "core.digest_email.build_digest_sections",
        Mock(return_value=sections),
    )
    monkeypatch.setattr("core.digest_email.ensure_email_settings", Mock())
    monkeypatch.setattr(
        "core.digest_email.build_unsubscribe_url",
        Mock(return_value="http://localhost:8000/email/unsubscribe?token=abc"),
    )
    monkeypatch.setattr(
        "core.digest_email.send_digest_email",
        Mock(side_effect=EmailDeliveryError("smtp down")),
    )

    result = deliver_digest_email_for_user(
        user_id="reader@example.com",
        profile_ids=["profile-1"],
        run_ids=["run-1"],
    )

    assert result["status"] == "failed"
    assert "smtp down" in result["error_message"]


def test_send_digest_email_wraps_unexpected_delivery_errors(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "mailpit")
    monkeypatch.setenv("EMAIL_FROM", "noreply@localhost")
    monkeypatch.setattr(
        "core.digest_email.deliver_email_message",
        Mock(side_effect=RuntimeError("socket down")),
    )

    with pytest.raises(EmailDeliveryError, match="socket down"):
        send_digest_email(
            to_email="reader@example.com",
            subject="Digest",
            plain_body="plain",
            html_body="<p>html</p>",
        )
