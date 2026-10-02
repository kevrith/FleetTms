"""M-Pesa Daraja (client payments, "C2B"). A client pays the business's Paybill or Till and Safaricom calls our
confirmation address. With no keys in `.env` a stand-in is used, so nothing leaves the machine in development.

Safaricom refuses callback addresses that contain words like "mpesa", so ours live under /hooks/c2b."""

import hashlib
import hmac
import logging
import uuid
from typing import Protocol

import httpx

from app.config import settings

log = logging.getLogger(__name__)
BASES = {"sandbox": "https://sandbox.safaricom.co.ke", "production": "https://api.safaricom.co.ke"}


class DarajaError(Exception):
    """Safaricom did not accept the request. The text is safe to show to the owner."""


class DarajaClient(Protocol):
    async def register_urls(self, shortcode: str, confirmation_url: str, validation_url: str) -> None: ...

    async def simulate(self, shortcode: str, amount_kes: int, bill_ref: str, phone: str) -> None: ...


class FakeDaraja:
    """Keeps what would have been sent, so tests and local development can inspect it."""

    def __init__(self) -> None:
        self.registered: list[dict] = []
        self.fail_with: str | None = None

    async def register_urls(self, shortcode: str, confirmation_url: str, validation_url: str) -> None:
        if self.fail_with:
            raise DarajaError(self.fail_with)
        self.registered.append({"shortcode": shortcode, "confirmation_url": confirmation_url, "validation_url": validation_url})

    async def simulate(self, shortcode: str, amount_kes: int, bill_ref: str, phone: str) -> None:
        raise DarajaError("The stand-in has no Safaricom to call.")


class SafaricomDaraja:
    def __init__(self) -> None:
        self.base = BASES.get(settings.daraja_env, BASES["sandbox"])

    async def _token(self, http: httpx.AsyncClient) -> str:
        res = await http.get(f"{self.base}/oauth/v1/generate", params={"grant_type": "client_credentials"}, auth=(settings.daraja_consumer_key, settings.daraja_consumer_secret))
        res.raise_for_status()
        return res.json()["access_token"]

    async def _post(self, path: str, body: dict) -> None:
        try:
            async with httpx.AsyncClient(timeout=30) as http:
                token = await self._token(http)
                res = await http.post(f"{self.base}{path}", headers={"Authorization": f"Bearer {token}"}, json=body)
                res.raise_for_status()
        except (httpx.HTTPError, KeyError) as e:
            raise DarajaError(f"Safaricom did not accept the request: {type(e).__name__}") from e

    async def register_urls(self, shortcode: str, confirmation_url: str, validation_url: str) -> None:
        await self._post("/mpesa/c2b/v2/registerurl", {"ShortCode": shortcode, "ResponseType": "Completed", "ConfirmationURL": confirmation_url, "ValidationURL": validation_url})

    async def simulate(self, shortcode: str, amount_kes: int, bill_ref: str, phone: str) -> None:
        if settings.daraja_env != "sandbox":
            raise DarajaError("Payments can only be simulated in the sandbox.")
        await self._post("/mpesa/c2b/v1/simulate", {"ShortCode": shortcode, "CommandID": "CustomerPayBillOnline", "Amount": amount_kes, "Msisdn": phone.lstrip("+"), "BillRefNumber": bill_ref})


_fake = FakeDaraja()


def get_daraja() -> DarajaClient:
    if settings.daraja_consumer_key and settings.daraja_consumer_secret:
        return SafaricomDaraja()
    return _fake


def fake_daraja() -> FakeDaraja:
    return _fake


def is_live() -> bool:
    return bool(settings.daraja_consumer_key and settings.daraja_consumer_secret)


def callback_key(business_id: uuid.UUID) -> str:
    """The secret part of a business's callback address. Safaricom cannot sign its calls, so the address itself is the
    secret: anyone who does not know it cannot post payments to us. It is derived, so nothing needs storing."""
    return hmac.new(settings.jwt_secret.encode(), f"c2b:{business_id}".encode(), hashlib.sha256).hexdigest()[:40]


def key_matches(business_id: uuid.UUID, key: str) -> bool:
    return hmac.compare_digest(callback_key(business_id), key)


def callback_urls(business_id: uuid.UUID) -> tuple[str, str]:
    base = settings.public_api_url.rstrip("/") or "http://localhost:8010"
    root = f"{base}/hooks/c2b/{business_id}/{callback_key(business_id)}"
    return f"{root}/confirmation", f"{root}/validation"
