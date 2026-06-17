"""
Outbound email delivery for authentication messages
"""

import smtplib
from email.message import EmailMessage

from core.config import (
    get_email_from,
    get_product_name,
    get_smtp_host,
    get_smtp_password,
    get_smtp_port,
    get_smtp_use_ssl,
    get_smtp_use_starttls,
    get_smtp_username,
    is_email_delivery_configured,
)
from core.auth_messages import (
    EMAIL_DELIVERY_UNAVAILABLE_MESSAGE,
    EMAIL_SEND_FAILED_MESSAGE,
)
from core.logging import get_logger

logger = get_logger(__name__)


class EmailDeliveryError(RuntimeError):
    """Raised when outbound email cannot be delivered."""


def deliver_email_message(message: EmailMessage) -> None:
    host = get_smtp_host()
    port = get_smtp_port()
    username = get_smtp_username()
    password = get_smtp_password()

    if get_smtp_use_ssl():
        with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
            if username and password:
                smtp.login(username, password)
            smtp.send_message(message)
        return

    with smtplib.SMTP(host, port, timeout=30) as smtp:
        smtp.ehlo()
        if get_smtp_use_starttls():
            smtp.starttls()
            smtp.ehlo()
        if username and password:
            smtp.login(username, password)
        smtp.send_message(message)


def send_magic_link_email(to_email: str, magic_link: str) -> None:
    if not is_email_delivery_configured():
        raise EmailDeliveryError(EMAIL_DELIVERY_UNAVAILABLE_MESSAGE)

    message = EmailMessage()
    message["Subject"] = f"Sign in to {get_product_name()}"
    message["From"] = get_email_from()
    message["To"] = to_email
    message.set_content(
        "Click the link below to sign in. This link expires in 30 minutes.\n\n"
        f"{magic_link}\n\n"
        "If you did not request this, you can ignore this email."
    )

    try:
        deliver_email_message(message)
    except Exception as error:
        logger.exception(
            "Magic link email delivery failed",
            extra={"event": "auth.magic_link.email_failed", "to_email": to_email},
        )
        raise EmailDeliveryError(EMAIL_SEND_FAILED_MESSAGE) from error
