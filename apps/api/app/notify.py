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
