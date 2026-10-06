"""Plain-text email for alerts (the report sender only sends PDFs). Without SMTP settings an in-memory outbox is used, so tests and
local development can see what would have been sent."""

import asyncio
import logging
import smtplib
from email.message import EmailMessage
from typing import Protocol

from app.config import settings

log = logging.getLogger(__name__)


class EmailSender(Protocol):
    async def send(self, to: str, subject: str, body: str) -> None: ...


class FakeEmail:
    def __init__(self) -> None:
        self.outbox: list[tuple[str, str, str]] = []

    async def send(self, to: str, subject: str, body: str) -> None:
        self.outbox.append((to, subject, body))
        log.info("Fake email sent")


class SmtpEmail:
    async def send(self, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"], message["To"], message["Subject"] = settings.smtp_from or settings.smtp_user, to, subject
        message.set_content(body)

        def deliver() -> None:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
                smtp.starttls()
                if settings.smtp_user:
                    smtp.login(settings.smtp_user, settings.smtp_password)
                smtp.send_message(message)

        try:
            await asyncio.to_thread(deliver)
        except (OSError, smtplib.SMTPException):
            log.warning("An alert email was not accepted by the mail server")  # an alert must never fail because mail is down


_fake = FakeEmail()


def get_email_sender() -> EmailSender:
    return SmtpEmail() if settings.smtp_host else _fake


def fake_email() -> FakeEmail:
    return _fake


async def send_invite_email(*, to: str, name: str, business_name: str, invited_by: str, token: str) -> bool:
    """Emails a new person the one-time link to choose their password. Returns whether a real mail server is set up (without one the
    message only goes to the in-memory outbox, so the person who invited them still has to pass the link on)."""
    base = (settings.public_web_url or settings.web_app_url or "http://localhost:5180").rstrip("/")  # an empty setting must not give a link with no address
    link = f"{base}/accept-invite?token={token}"
    body = (
        f"Hello {name},\n\n"
        f"{invited_by} has added you to {business_name} on FleetTms.\n\n"
        f"Choose your password to finish setting up your account:\n{link}\n\n"
        f"The link works once and expires in {settings.invite_ttl_hours // 24 or 1} days. "
        "If you were not expecting this, you can ignore this email and nothing will happen.\n\n"
        "FleetTms\n"
    )
    await get_email_sender().send(to, f"{invited_by} invited you to {business_name} on FleetTms", body)
    return bool(settings.smtp_host)
