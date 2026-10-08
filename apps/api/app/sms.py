"""SMS sending. Development keeps messages in memory; a deployment with AT_USERNAME and AT_API_KEY sends them through Africa's Talking."""

import asyncio
import logging
from collections import deque
from datetime import UTC, datetime
from typing import Protocol

import httpx

from app.config import settings
from app.phone import mask_phone

log = logging.getLogger(__name__)


class SmsSender(Protocol):
    async def send(self, phone: str, message: str) -> None: ...


CODE_PREFIX = "Your FleetTms code"  # how every one-time sign-in and verification code begins


class FakeSmsSender:
    """Keeps messages in memory so tests and local development can read the code."""

    def __init__(self) -> None:
        self.outbox: list[tuple[str, str]] = []
        # One-time codes only (never a business's alerts or messages), newest last, for the super admin's testing inbox in the platform
        # console while no real gateway is set up. Held in memory: a restart clears it.
        self.inbox: deque[dict] = deque(maxlen=50)

    async def send(self, phone: str, message: str) -> None:
        self.outbox.append((phone, message))
        if message.startswith(CODE_PREFIX):
            self.inbox.append({"to": phone, "message": message, "at": datetime.now(UTC)})
        log.info("Fake SMS sent to %s", mask_phone(phone))
        if settings.environment == "development":
            # Local development only: lets you read the one-time code without a real SMS gateway.
            log.warning("DEV ONLY SMS to %s: %s", phone, message)


# Africa's Talking status codes for a recipient. 100 processed, 101 sent, 102 queued are success; the rest are failures with a reason.
AT_OK = {100, 101, 102}
AT_REASONS = {
    401: "risk hold", 402: "invalid sender id", 403: "invalid phone number", 404: "unsupported number type", 405: "insufficient balance",
    406: "recipient blocked", 407: "could not route", 500: "internal error", 501: "gateway error", 502: "rejected by the gateway",
}  # fmt: skip


class AfricasTalkingSms:
    """Sends through Africa's Talking's messaging API (written from their documentation, and tested against a mock: no live account was
    available). It never raises into the caller: a gateway that is down must not turn a driver's sign-in or an alert job into an error, so a
    failure is retried twice for network trouble and server errors, then logged. The log names the masked number and the reason, never the
    message (it may hold a sign-in code) and never the key."""

    LIVE = "https://api.africastalking.com/version1/messaging"
    SANDBOX = "https://api.sandbox.africastalking.com/version1/messaging"

    def __init__(self, username: str, api_key: str, sender_id: str = "", *, sandbox: bool = False, transport: httpx.AsyncBaseTransport | None = None, retry_wait: float = 1.0) -> None:
        self.username, self.api_key, self.sender_id = username, api_key, sender_id
        self.url = self.SANDBOX if sandbox else self.LIVE
        self.transport, self.retry_wait = transport, retry_wait

    async def send(self, phone: str, message: str) -> None:
        form = {"username": self.username, "to": phone, "message": message}
        if self.sender_id:
            form["from"] = self.sender_id
        reason = "no answer"
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(transport=self.transport, timeout=20) as http:
                    res = await http.post(self.url, data=form, headers={"apiKey": self.api_key, "Accept": "application/json"})
            except httpx.HTTPError as e:
                reason = type(e).__name__
            else:
                if res.status_code < 300:
                    return self._check(phone, res)
                reason = f"gateway answered {res.status_code}"
                if res.status_code < 500:
                    break  # a refusal (bad key, bad request) will not change by asking again
            if attempt < 2:
                await asyncio.sleep(self.retry_wait * (attempt + 1))
        log.warning("Text to %s was not sent: %s", mask_phone(phone), reason)

    @staticmethod
    def _check(phone: str, res: httpx.Response) -> None:
        try:
            recipients = res.json()["SMSMessageData"]["Recipients"]
        except (ValueError, KeyError, TypeError):
            log.warning("Text to %s: the gateway's answer could not be read", mask_phone(phone))
            return
        if not recipients:
            log.warning("Text to %s was not sent: the gateway accepted no recipient", mask_phone(phone))
        for r in recipients:
            if r.get("statusCode") not in AT_OK:
                log.warning("Text to %s was not sent: %s", mask_phone(phone), AT_REASONS.get(r.get("statusCode"), r.get("status") or "unknown reason"))


def build_sender() -> SmsSender:
    """The real gateway when it is configured, else the in-memory stand-in."""
    if settings.at_username and settings.at_api_key:
        return AfricasTalkingSms(settings.at_username, settings.at_api_key, settings.at_sender_id, sandbox=settings.at_sandbox)
    return FakeSmsSender()


class MeteredSms:
    """Counts the messages a business sends, for its text bundle. Wraps any sender; it never holds a message back or lets counting
    get in the way of sending one. One-time sign-in codes are the platform's cost, so they are not counted."""

    def __init__(self, inner: SmsSender) -> None:
        self.inner = inner

    def __getattr__(self, name: str):  # outbox and the like, so tests and tools see the real sender
        return getattr(self.inner, name)

    async def send_platform(self, phone: str, message: str) -> None:
        """A message from the platform to a business (a payment reminder): not counted against the business's bundle."""
        await self.inner.send(phone, message)

    async def send(self, phone: str, message: str) -> None:
        await self.inner.send(phone, message)
        if message.startswith("Your FleetTms code"):
            return
        try:
            from app.db import get_sessionmaker
            from app.subscriptions import current_business, record_sms

            if current_business() is not None:
                async with get_sessionmaker()() as db:
                    await record_sms(db, max(1, -(-len(message) // 160)))
                    await db.commit()
        except Exception:  # noqa: BLE001  (counting must never stop a message)
            log.warning("A text message could not be counted against the bundle")


_sender: SmsSender = MeteredSms(build_sender())


def get_sms_sender() -> SmsSender:
    return _sender
