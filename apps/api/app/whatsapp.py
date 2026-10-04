"""Automatic WhatsApp through the official Business (Cloud) API: a parts order goes to the supplier and a payment reminder to a client
without anyone opening WhatsApp, and Meta's reports (sent, delivered, read) and the supplier's button answer come back to /hooks/whatsapp.

A business starts a conversation only with an approved template, so every message here is one (docs/whatsapp.md has their wording). With no
token and number id configured a stand-in keeps the messages in memory, so development and tests see every outcome."""

import hmac
import logging
import re
import uuid
from datetime import UTC, datetime
from hashlib import sha256
from typing import Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import WhatsAppMessage
from app.phone import mask_phone

log = logging.getLogger(__name__)
GRAPH = "https://graph.facebook.com/v21.0"
RANK = {"queued": 0, "sent": 1, "delivered": 2, "read": 3}  # a later report never goes back to an earlier state (Meta can send them out of order)
BUTTONS = ("confirm", "decline")  # the payloads of the order template's two quick-reply buttons


class WhatsAppError(Exception):
    """Meta did not accept the message. The text is safe to show to the person who asked for it."""


class WhatsAppSender(Protocol):
    async def send_template(self, to: str, template: str, params: list[str], *, buttons: tuple[str, ...] = ()) -> str: ...


def clean_param(value: object) -> str:
    """A template variable may not hold a line break, a tab or a run of spaces, and may not be empty."""
    text = re.sub(r"\s+", " ", str(value)).strip()[:1000]
    return text or "-"


class FakeWhatsApp:
    """Keeps what would have been sent, and fails on request, so tests and local development can see every outcome."""

    def __init__(self) -> None:
        self.outbox: list[dict] = []
        self.fail_with: str | None = None

    def reset(self) -> None:
        self.outbox.clear()
        self.fail_with = None

    async def send_template(self, to: str, template: str, params: list[str], *, buttons: tuple[str, ...] = ()) -> str:
        if self.fail_with:
            raise WhatsAppError(self.fail_with)
        message_id = f"wamid.FAKE{len(self.outbox) + 1:05d}"
        self.outbox.append({"id": message_id, "to": to, "template": template, "params": params, "buttons": buttons})
        log.info("Fake WhatsApp %s sent to %s", template, mask_phone(to))
        return message_id


class CloudApi:
    async def send_template(self, to: str, template: str, params: list[str], *, buttons: tuple[str, ...] = ()) -> str:
        components: list[dict] = [{"type": "body", "parameters": [{"type": "text", "text": p} for p in params]}]
        for index, payload in enumerate(buttons):
            components.append({"type": "button", "sub_type": "quick_reply", "index": str(index), "parameters": [{"type": "payload", "payload": payload}]})
        body = {
            "messaging_product": "whatsapp", "to": to.lstrip("+"), "type": "template",
            "template": {"name": template, "language": {"code": settings.whatsapp_template_language}, "components": components},
        }  # fmt: skip
        try:
            async with httpx.AsyncClient(timeout=30) as http:
                res = await http.post(f"{GRAPH}/{settings.whatsapp_phone_number_id}/messages", headers={"Authorization": f"Bearer {settings.whatsapp_token}"}, json=body)
            if res.status_code >= 400:
                reason = ((res.json().get("error") or {}).get("message") or "") if res.headers.get("content-type", "").startswith("application/json") else ""
                raise WhatsAppError(f"WhatsApp did not accept the message (HTTP {res.status_code}). {reason}"[:250].strip())
            return str(res.json()["messages"][0]["id"])
        except httpx.HTTPError as e:
            raise WhatsAppError(f"WhatsApp could not be reached: {type(e).__name__}") from e
        except (KeyError, IndexError, ValueError) as e:
            raise WhatsAppError("WhatsApp sent back something unreadable.") from e


_fake = FakeWhatsApp()


def is_live() -> bool:
    return bool(settings.whatsapp_token and settings.whatsapp_phone_number_id)


def available() -> bool:
    """Whether sending automatically is on offer: the real thing is set up, or this is development, where the stand-in is used."""
    return is_live() or settings.environment != "production"


def get_whatsapp() -> WhatsAppSender:
    return CloudApi() if is_live() else _fake


def fake_whatsapp() -> FakeWhatsApp:
    return _fake


def template_for(purpose: str) -> str:
    """The approved template for a purpose. In development the stand-in needs no approval, so a name is made up."""
    name = settings.whatsapp_order_template if purpose == "order" else settings.whatsapp_reminder_template
    return name or ("" if is_live() else f"fleettms_{purpose}")


async def send(db: AsyncSession, *, to: str, purpose: str, entity_type: str, entity_id: uuid.UUID, params: list[str], buttons: tuple[str, ...] = ()) -> WhatsAppMessage:
    """Sends one template message and records it. Raises WhatsAppError when it is not accepted (the row is kept, marked failed)."""
    template = template_for(purpose)
    row = WhatsAppMessage(to_phone=to, purpose=purpose, entity_type=entity_type, entity_id=entity_id, status="queued")
    db.add(row)
    if not template:
        row.status, row.error = "failed", "The WhatsApp template for this has not been set up."
        await db.flush()
        raise WhatsAppError(row.error)
    try:
        row.wa_message_id = await get_whatsapp().send_template(to, template, [clean_param(p) for p in params], buttons=buttons)
    except WhatsAppError as e:
        row.status, row.error = "failed", str(e)[:255]
        await db.flush()
        raise
    row.status, row.sent_at = "sent", datetime.now(UTC)
    await db.flush()
    return row


async def latest_for(db: AsyncSession, entity_type: str, entity_id: uuid.UUID) -> WhatsAppMessage | None:
    return (
        await db.execute(select(WhatsAppMessage).where(WhatsAppMessage.entity_type == entity_type, WhatsAppMessage.entity_id == entity_id).order_by(WhatsAppMessage.created_at.desc()))
    ).scalars().first()


def state_of(row: WhatsAppMessage | None) -> dict | None:
    """What a screen shows about the latest message: how far it got, and the recipient's answer if there is one."""
    if row is None:
        return None
    return {"status": row.status, "sent_at": row.sent_at, "delivered_at": row.delivered_at, "read_at": row.read_at, "reply": row.reply, "replied_at": row.replied_at, "error": row.error}


def apply_report(row: WhatsAppMessage, status: str, errors: list[dict] | None, at: datetime) -> None:
    """Meta's report on one message. Out-of-order and repeated reports change nothing they should not."""
    if status == "failed":
        if row.status not in ("delivered", "read"):
            row.status = "failed"
            row.error = ("; ".join(str(e.get("title") or e.get("message") or e.get("code")) for e in (errors or [])) or "WhatsApp could not deliver the message.")[:255]
        return
    if status not in RANK or RANK[status] <= RANK.get(row.status, -1):
        return
    row.status, row.error = status, None
    if status == "sent":
        row.sent_at = row.sent_at or at
    elif status == "delivered":
        row.delivered_at = row.delivered_at or at
    elif status == "read":
        row.delivered_at, row.read_at = row.delivered_at or at, row.read_at or at


def signature_ok(body: bytes, header: str | None) -> bool:
    """Meta signs every report with the app secret: X-Hub-Signature-256: sha256=<hex of the body>. Nothing is accepted unsigned."""
    if not settings.whatsapp_app_secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(settings.whatsapp_app_secret.encode(), body, sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))
