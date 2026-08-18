"""
Daily digest email formatting and delivery
"""

from datetime import UTC, datetime
from html import escape
from urllib.parse import urlencode

from email.message import EmailMessage

from core.auth import create_digest_login_token
from core.config import get_app_base_url, get_email_from, get_product_name, is_email_delivery_configured
from core.digest_content import (
    DigestPick,
    DigestSection,
    build_digest_sections,
    count_digest_picks,
)
from core.email import EmailDeliveryError, deliver_email_message
from core.email_settings import build_unsubscribe_url, ensure_email_settings
from core.logging import get_logger

logger = get_logger(__name__)

PAPERS_SOURCED_DISCLAIMER = "Papers are sourced from arXiv.org"

CTA_BUTTON_STYLE = (
    "display:inline-block;background:#111827;color:#ffffff;text-decoration:none;"
    "border-radius:6px;padding:8px 14px;font-size:14px;border:1px solid #111827;"
    "margin:0 5px 8px;"
)


def score_display_percent(final_score: float) -> int:
    score = final_score if isinstance(final_score, (int, float)) else 0.0
    return max(0, min(100, round(score * 100)))


def star_rating_from_percent(percent: int) -> int:
    if percent >= 75:
        return 3
    if percent >= 65:
        return 2
    if percent >= 55:
        return 1
    return 0


def stars_display(percent: int) -> str:
    return "⭐" * star_rating_from_percent(percent)


def paper_link(pick: DigestPick) -> str:
    if pick.pdf_url:
        return pick.pdf_url
    return f"https://arxiv.org/abs/{pick.arxiv_id}"


def pick_stars(pick: DigestPick) -> str:
    return stars_display(score_display_percent(pick.final_score))


def _format_authors(authors: tuple[str, ...], max_named: int = 3) -> str:
    names = [str(name).strip() for name in (authors or ()) if str(name).strip()]
    if not names:
        return ""
    if len(names) > max_named:
        return f"{names[0]} et al."
    return ", ".join(names)


def _format_short_date(value: datetime | None) -> str:
    if not value:
        return ""
    return value.strftime("%d/%m/%y")


def _format_pick_byline(pick: DigestPick) -> str:
    authors_text = _format_authors(pick.authors)
    date_text = _format_short_date(pick.published_at)
    if not authors_text and not date_text:
        return ""
    if authors_text and date_text:
        return f"{authors_text} ({date_text})"
    return authors_text or date_text


def format_pick_plain_lines(index: int, pick: DigestPick) -> list[str]:
    lines = [f"{index}. {pick.title}"]
    byline = _format_pick_byline(pick)
    if byline:
        lines.append(f"   {byline}")
    if pick.description:
        lines.append(f"   {pick.description}")
    stars = pick_stars(pick)
    if stars:
        lines.append(f"   {stars}")
    lines.append(f"   {paper_link(pick)}")
    return lines


def build_digest_email_subject(*, generated_at: datetime | None = None) -> str:
    when = generated_at or datetime.now(UTC)
    date_label = when.astimezone(UTC).strftime("%-d %b %Y")
    return f"Your daily research digest — {date_label}"


def build_digest_login_url(base_url: str, token: str, next_path: str) -> str:
    query = urlencode({"token": token, "next": next_path})
    return f"{base_url.rstrip('/')}/auth/digest-login?{query}"


def _digest_urls(
    *,
    app_base_url: str | None = None,
    unsubscribe_url: str | None = None,
    login_token: str | None = None,
) -> tuple[str, str, str, str]:
    base_url = (app_base_url or get_app_base_url()).rstrip("/")
    if login_token:
        preferences_url = build_digest_login_url(base_url, login_token, "/profiles")
        feedback_url = build_digest_login_url(base_url, login_token, "/papers")
    else:
        preferences_url = f"{base_url}/profiles"
        feedback_url = f"{base_url}/papers"
    resolved_unsubscribe_url = unsubscribe_url or f"{base_url}/email/unsubscribe"
    return base_url, preferences_url, feedback_url, resolved_unsubscribe_url


def build_digest_email_body(
    sections: list[DigestSection],
    *,
    app_base_url: str | None = None,
    unsubscribe_url: str | None = None,
    login_token: str | None = None,
) -> str:
    _, preferences_url, feedback_url, resolved_unsubscribe_url = _digest_urls(
        app_base_url=app_base_url,
        unsubscribe_url=unsubscribe_url,
        login_token=login_token,
    )

    lines = [
        f"Your daily research digest from {get_product_name()}",
        "",
    ]

    for section in sections:
        category_suffix = f" · {section.category}" if section.category else ""
        lines.append(f"{section.profile_name}{category_suffix}")
        lines.append("")

        for index, pick in enumerate(section.picks, start=1):
            lines.extend(format_pick_plain_lines(index, pick))
            lines.append("")

    lines.extend(
        [
            "---",
            f"Rate papers: {feedback_url}",
            f"Manage preferences: {preferences_url}",
            PAPERS_SOURCED_DISCLAIMER,
            f"Unsubscribe: {resolved_unsubscribe_url}",
        ]
    )
    return "\n".join(lines)


def build_digest_email_html(
    sections: list[DigestSection],
    *,
    app_base_url: str | None = None,
    unsubscribe_url: str | None = None,
    login_token: str | None = None,
) -> str:
    _, preferences_url, feedback_url, resolved_unsubscribe_url = _digest_urls(
        app_base_url=app_base_url,
        unsubscribe_url=unsubscribe_url,
        login_token=login_token,
    )

    section_blocks: list[str] = []
    for index, section in enumerate(sections):
        section_style = "margin:0;"
        if index > 0:
            section_style = (
                "margin:0;padding-top:24px;border-top:1px solid #e5e7eb;"
            )
        category_html = ""
        if section.category:
            category_html = (
                f'<td align="right" valign="top" style="font-size:12px;'
                f'color:#6b7280;white-space:nowrap;padding-left:12px;">'
                f"{escape(section.category)}</td>"
            )

        pick_items: list[str] = []
        for index, pick in enumerate(section.picks, start=1):
            byline = _format_pick_byline(pick)
            byline_html = ""
            if byline:
                byline_html = (
                    f'<tr><td style="width:36px;"></td>'
                    f'<td style="padding-top:4px;color:#6b7280;font-size:12px;'
                    f'line-height:1.35;">{escape(byline)}</td></tr>'
                )
            stars = pick_stars(pick)
            stars_html = (
                f'<tr><td style="width:36px;"></td>'
                f'<td style="padding-top:4px;font-size:12px;color:#6b7280;'
                f'line-height:1.35;min-height:1.35em;">{escape(stars)}</td></tr>'
            )
            link = escape(paper_link(pick), quote=True)
            title = escape(pick.title)
            blurb_html = ""
            if pick.description:
                blurb_html = (
                    f'<tr><td style="width:36px;"></td>'
                    f'<td style="padding-top:4px;color:#111827;font-size:12px;'
                    f'font-style:italic;line-height:1.45;">{escape(pick.description)}</td></tr>'
                )
            pick_items.append(
                f'<li style="margin:0;padding:0;list-style:none;">'
                f'<table role="presentation" cellpadding="0" cellspacing="0" '
                f'border="0" style="width:100%;">'
                f'<tr>'
                f'<td style="width:36px;font-weight:600;color:#111827;'
                f'text-align:right;vertical-align:top;padding-right:6px;">'
                f"{index}.</td>"
                f'<td style="vertical-align:top;">'
                f'<a href="{link}" style="color:#111827;font-weight:600;'
                f'text-decoration:none;">{title}</a>'
                f"</td></tr>"
                f"{byline_html}{blurb_html}{stars_html}"
                f"</table></li>"
            )

        section_blocks.append(
            f'<article style="{section_style}">'
            f'<table role="presentation" cellpadding="0" cellspacing="0" '
            f'border="0" style="width:100%;margin:0 0 16px;">'
            f"<tr>"
            f'<td><h2 style="margin:0;font-size:18px;color:#111827;">'
            f"{escape(section.profile_name)}</h2></td>"
            f"{category_html}"
            f"</tr></table>"
            f'<ul style="margin:0;padding:0;display:flex;flex-direction:column;gap:14px;">'
            f'{"".join(pick_items)}</ul>'
            f"</article>"
        )

    header = (
        f"Your daily research digest from {escape(get_product_name())}"
    )
    header_block = (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'style="width:100%;margin:0 0 16px;">'
        f'<tr><td align="center" style="text-align:center;">'
        f'<h1 align="center" style="margin:0;font-size:22px;font-weight:700;'
        f'line-height:1.3;color:#111827;text-align:center;">'
        f"{header}"
        f"</h1></td></tr></table>"
    )
    cta_block = (
        f'<div style="margin-top:28px;padding-top:20px;border-top:1px solid #e5e7eb;'
        f'text-align:center;">'
        f'<a href="{escape(feedback_url, quote=True)}" style="{CTA_BUTTON_STYLE}">'
        f"Rate papers</a>"
        f'<a href="{escape(preferences_url, quote=True)}" style="{CTA_BUTTON_STYLE}">'
        f"Manage preferences</a>"
        f"</div>"
    )
    disclaimer = (
        '<p style="margin:16px 0 0;font-size:12px;color:#6b7280;line-height:1.5;'
        'text-align:center;">'
        f"{escape(PAPERS_SOURCED_DISCLAIMER)}"
        "</p>"
    )
    footer_links = (
        f'<p style="margin:8px 0 0;font-size:12px;color:#6b7280;line-height:1.5;'
        f'text-align:center;">'
        f'<a href="{escape(resolved_unsubscribe_url, quote=True)}" '
        f'style="color:#6b7280;">Unsubscribe from digest emails</a>'
        f"</p>"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(build_digest_email_subject())}</title>
</head>
<body style="margin:0;padding:24px 16px;background:#f9fafb;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#111827;">
  <div style="max-width:980px;margin:0 auto;">
    {header_block}
    <div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:8px;padding:24px;">
      {"".join(section_blocks)}
      {cta_block}
    </div>
    {disclaimer}
    {footer_links}
  </div>
</body>
</html>"""


def send_digest_email(
    *,
    to_email: str,
    subject: str,
    plain_body: str,
    html_body: str,
) -> None:
    if not is_email_delivery_configured():
        raise EmailDeliveryError("email delivery is not configured")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = get_email_from()
    message["To"] = to_email
    message.set_content(plain_body)
    message.add_alternative(html_body, subtype="html")
    try:
        deliver_email_message(message)
    except Exception as error:
        raise EmailDeliveryError(str(error)) from error


def deliver_digest_email_for_user(
    *,
    user_id: str,
    profile_ids: list[str],
    run_ids: list[str],
    to_email: str | None = None,
    conn=None,
) -> dict:
    if not is_email_delivery_configured():
        logger.info(
            "Digest email skipped because SMTP is not configured",
            extra={
                "event": "digest.email.skipped_unconfigured",
                "user_id": user_id,
            },
        )
        return {"status": "skipped_unconfigured", "error_message": None}

    sections = build_digest_sections(
        user_id=user_id,
        profile_ids=profile_ids,
        run_ids=run_ids,
        conn=conn,
    )
    if count_digest_picks(sections) == 0:
        logger.info(
            "Digest email skipped because there are no picks",
            extra={
                "event": "digest.email.skipped_no_picks",
                "user_id": user_id,
                "profile_ids": profile_ids,
                "run_ids": run_ids,
            },
        )
        return {"status": "skipped_no_picks", "error_message": None}

    ensure_email_settings(user_id, conn=conn)
    unsubscribe_url = build_unsubscribe_url(user_id)
    login_token, _ = create_digest_login_token(user_id, conn=conn)

    recipient = (to_email or user_id).strip()
    subject = build_digest_email_subject()
    plain_body = build_digest_email_body(
        sections,
        unsubscribe_url=unsubscribe_url,
        login_token=login_token,
    )
    html_body = build_digest_email_html(
        sections,
        unsubscribe_url=unsubscribe_url,
        login_token=login_token,
    )

    try:
        send_digest_email(
            to_email=recipient,
            subject=subject,
            plain_body=plain_body,
            html_body=html_body,
        )
    except EmailDeliveryError as error:
        logger.exception(
            "Digest email delivery failed",
            extra={
                "event": "digest.email.failed",
                "user_id": user_id,
                "profile_ids": profile_ids,
                "run_ids": run_ids,
            },
        )
        return {
            "status": "failed",
            "error_message": str(error),
        }

    logger.info(
        "Digest email sent",
        extra={
            "event": "digest.email.sent",
            "user_id": user_id,
            "to_email": recipient,
            "redirected_recipient": recipient.lower() != user_id.strip().lower(),
            "profile_ids": profile_ids,
            "run_ids": run_ids,
            "pick_count": count_digest_picks(sections),
        },
    )
    return {"status": "sent", "error_message": None}
