"""
Tests outbound email delivery
"""

from email.message import EmailMessage
from unittest.mock import MagicMock, patch

import pytest

from core.email import EmailDeliveryError, send_magic_link_email


def test_send_magic_link_email_requires_configuration(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("EMAIL_FROM", raising=False)

    with pytest.raises(EmailDeliveryError, match="temporarily unavailable"):
        send_magic_link_email("user@example.com", "http://localhost/verify?token=abc")


def test_send_magic_link_email_uses_starttls_on_port_587(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("EMAIL_FROM", "noreply@example.com")
    monkeypatch.delenv("SMTP_USE_SSL", raising=False)

    smtp_instance = MagicMock()
    smtp_context = MagicMock()
    smtp_context.__enter__.return_value = smtp_instance

    with patch("core.email.smtplib.SMTP", return_value=smtp_context) as smtp_ctor:
        send_magic_link_email("user@example.com", "http://localhost/verify?token=abc")

    smtp_ctor.assert_called_once_with("smtp.example.com", 587, timeout=30)
    smtp_instance.ehlo.assert_called()
    smtp_instance.starttls.assert_called_once()
    sent_message = smtp_instance.send_message.call_args.args[0]
    assert isinstance(sent_message, EmailMessage)
    assert sent_message["To"] == "user@example.com"
    assert sent_message["From"] == "noreply@example.com"
    assert "http://localhost/verify?token=abc" in sent_message.get_content()


def test_send_magic_link_email_skips_starttls_on_mailpit_port(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "mailpit")
    monkeypatch.setenv("SMTP_PORT", "1025")
    monkeypatch.setenv("EMAIL_FROM", "noreply@localhost")
    monkeypatch.delenv("SMTP_USE_STARTTLS", raising=False)

    smtp_instance = MagicMock()
    smtp_context = MagicMock()
    smtp_context.__enter__.return_value = smtp_instance

    with patch("core.email.smtplib.SMTP", return_value=smtp_context) as smtp_ctor:
        send_magic_link_email("user@example.com", "http://localhost/verify?token=abc")

    smtp_ctor.assert_called_once_with("mailpit", 1025, timeout=30)
    smtp_instance.starttls.assert_not_called()


def test_send_magic_link_email_uses_ssl_on_port_465(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "465")
    monkeypatch.setenv("EMAIL_FROM", "noreply@example.com")

    smtp_instance = MagicMock()
    smtp_context = MagicMock()
    smtp_context.__enter__.return_value = smtp_instance

    with patch("core.email.smtplib.SMTP_SSL", return_value=smtp_context) as smtp_ctor:
        send_magic_link_email("user@example.com", "http://localhost/verify?token=abc")

    smtp_ctor.assert_called_once_with("smtp.example.com", 465, timeout=30)
    smtp_instance.send_message.assert_called_once()


def test_send_magic_link_email_logs_in_when_credentials_set(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("EMAIL_FROM", "noreply@example.com")
    monkeypatch.setenv("SMTP_USERNAME", "apikey")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")

    smtp_instance = MagicMock()
    smtp_context = MagicMock()
    smtp_context.__enter__.return_value = smtp_instance

    with patch("core.email.smtplib.SMTP", return_value=smtp_context):
        send_magic_link_email("user@example.com", "http://localhost/verify?token=abc")

    smtp_instance.login.assert_called_once_with("apikey", "secret")


def test_send_magic_link_email_wraps_smtp_failures(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("EMAIL_FROM", "noreply@example.com")

    with patch("core.email.smtplib.SMTP", side_effect=OSError("connection refused")):
        with pytest.raises(EmailDeliveryError, match="couldn't send"):
            send_magic_link_email("user@example.com", "http://localhost/verify?token=abc")
