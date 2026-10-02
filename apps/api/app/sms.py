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


_sender: SmsSender = FakeSmsSender()


def get_sms_sender() -> SmsSender:
    return _sender
