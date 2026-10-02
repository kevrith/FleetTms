"""Sends a report PDF by email or WhatsApp. Without credentials in the environment, an in-memory outbox is used."""

import asyncio
import logging
import smtplib
from email.message import EmailMessage
from typing import Protocol

import httpx

from app.config import settings
from app.phone import mask_phone

log = logging.getLogger(__name__)
GRAPH = "https://graph.facebook.com/v21.0"


class DeliveryError(Exception):
    """The provider did not accept the message. The text is safe to show to the owner."""


class ReportSender(Protocol):
    async def send(self, recipient: str, subject: str, filename: str, pdf: bytes, body: str | None = None) -> None: ...


class FakeSender:
    """Keeps what would have been sent, so tests and local development can inspect it."""

    def __init__(self, channel: str) -> None:
        self.channel = channel
        self.outbox: list[dict] = []
        self.fail_with: str | None = None

    async def send(self, recipient: str, subject: str, filename: str, pdf: bytes, body: str | None = None) -> None:
        if self.fail_with:
            raise DeliveryError(self.fail_with)
        self.outbox.append({"recipient": recipient, "subject": subject, "filename": filename, "pdf": pdf, "body": body})
        log.info("Fake %s report sent to %s", self.channel, mask_phone(recipient) if self.channel == "whatsapp" else recipient)


class SmtpSender:
    async def send(self, recipient: str, subject: str, filename: str, pdf: bytes, body: str | None = None) -> None:
        message = EmailMessage()
        message["From"], message["To"], message["Subject"] = settings.smtp_from or settings.smtp_user, recipient, subject
        message.set_content(body or "Your FleetTms report is attached.")
        message.add_attachment(pdf, maintype="application", subtype="pdf", filename=filename)

        def deliver() -> None:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
                smtp.starttls()
                if settings.smtp_user:
                    smtp.login(settings.smtp_user, settings.smtp_password)
                smtp.send_message(message)

        try:
            await asyncio.to_thread(deliver)
        except (OSError, smtplib.SMTPException) as e:
            raise DeliveryError(f"Email was not accepted: {type(e).__name__}") from e


class WhatsAppSender:
    """WhatsApp Cloud API: upload the PDF, then send it as a document message."""

    async def send(self, recipient: str, subject: str, filename: str, pdf: bytes, body: str | None = None) -> None:
        base = f"{GRAPH}/{settings.whatsapp_phone_number_id}"
        headers = {"Authorization": f"Bearer {settings.whatsapp_token}"}
        to = recipient.lstrip("+")
        try:
            async with httpx.AsyncClient(timeout=30) as http:
                up = await http.post(f"{base}/media", headers=headers, data={"messaging_product": "whatsapp"}, files={"file": (filename, pdf, "application/pdf")})
                up.raise_for_status()
                media_id = up.json()["id"]
                document = {"id": media_id, "filename": filename}
                if settings.whatsapp_report_template:
                    message = {"type": "template", "template": {
                        "name": settings.whatsapp_report_template, "language": {"code": "en"},
                        "components": [{"type": "header", "parameters": [{"type": "document", "document": document}]}],
                    }}  # fmt: skip
                else:
                    message = {"type": "document", "document": {**document, "caption": body or subject}}
                sent = await http.post(f"{base}/messages", headers=headers, json={"messaging_product": "whatsapp", "to": to, **message})
                sent.raise_for_status()
        except (httpx.HTTPError, KeyError) as e:
            raise DeliveryError(f"WhatsApp was not accepted: {type(e).__name__}") from e


_fakes = {"email": FakeSender("email"), "whatsapp": FakeSender("whatsapp")}


def get_report_sender(channel: str) -> ReportSender:
    if channel == "email" and settings.smtp_host:
        return SmtpSender()
    if channel == "whatsapp" and settings.whatsapp_token and settings.whatsapp_phone_number_id:
        return WhatsAppSender()
    return _fakes[channel]


def fake_sender(channel: str) -> FakeSender:
    return _fakes[channel]
