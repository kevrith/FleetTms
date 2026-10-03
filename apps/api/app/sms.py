"""SMS sending. Development uses an in-memory sender; Africa's Talking arrives in a later sprint."""

import logging
from typing import Protocol

from app.config import settings
from app.phone import mask_phone

log = logging.getLogger(__name__)


class SmsSender(Protocol):
    async def send(self, phone: str, message: str) -> None: ...


class FakeSmsSender:
    """Keeps messages in memory so tests and local development can read the code."""

    def __init__(self) -> None:
        self.outbox: list[tuple[str, str]] = []

    async def send(self, phone: str, message: str) -> None:
        self.outbox.append((phone, message))
        log.info("Fake SMS sent to %s", mask_phone(phone))
        if settings.environment == "development":
            # Local development only: lets you read the one-time code without a real SMS gateway.
            log.warning("DEV ONLY SMS to %s: %s", phone, message)


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


_sender: SmsSender = MeteredSms(FakeSmsSender())


def get_sms_sender() -> SmsSender:
    return _sender
