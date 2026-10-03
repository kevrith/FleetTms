"""Subscription payments by M-Pesa prompt (STK push): the owner's phone is asked for the invoice amount and Safaricom calls our callback
with the result. This is the platform's own Paybill, not a business's. Without keys a stand-in is used, so nothing leaves the machine.
Safaricom refuses callback addresses containing words like "mpesa", so the callback lives under /hooks/subscription-pay."""

import base64
import hashlib
import hmac
import logging
import uuid
from datetime import UTC, datetime
from typing import Protocol

import httpx

from app.config import settings
from app.daraja import BASES

log = logging.getLogger(__name__)


class PromptError(Exception):
    """Safaricom did not accept the payment request. The text is safe to show."""


class PromptProvider(Protocol):
    async def push(self, *, phone: str, amount_kes: int, reference: str, description: str, callback_url: str) -> str: ...


class FakePrompts:
    """Keeps the prompts that would have been sent, and gives each a checkout id, so tests can answer them."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.fail_with: str | None = None

    async def push(self, *, phone: str, amount_kes: int, reference: str, description: str, callback_url: str) -> str:
        if self.fail_with:
            raise PromptError(self.fail_with)
        checkout = f"ws_CO_{uuid.uuid4().hex[:20]}"
        self.sent.append({"phone": phone, "amount_kes": amount_kes, "reference": reference, "description": description, "callback_url": callback_url, "checkout_id": checkout})
        return checkout


class SafaricomPrompts:
    async def push(self, *, phone: str, amount_kes: int, reference: str, description: str, callback_url: str) -> str:
        base = BASES.get(settings.daraja_env, BASES["sandbox"])
        stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        password = base64.b64encode(f"{settings.platform_shortcode}{settings.platform_passkey}{stamp}".encode()).decode()
        body = {
            "BusinessShortCode": settings.platform_shortcode, "Password": password, "Timestamp": stamp, "TransactionType": "CustomerPayBillOnline", "Amount": amount_kes,
            "PartyA": phone.lstrip("+"), "PartyB": settings.platform_shortcode, "PhoneNumber": phone.lstrip("+"), "CallBackURL": callback_url, "AccountReference": reference[:12], "TransactionDesc": description[:13],
        }  # fmt: skip
        try:
            async with httpx.AsyncClient(timeout=30) as http:
                token = (await http.get(f"{base}/oauth/v1/generate", params={"grant_type": "client_credentials"}, auth=(settings.daraja_consumer_key, settings.daraja_consumer_secret))).json()["access_token"]
                res = await http.post(f"{base}/mpesa/stkpush/v1/processrequest", headers={"Authorization": f"Bearer {token}"}, json=body)
                res.raise_for_status()
                return res.json()["CheckoutRequestID"]
        except (httpx.HTTPError, KeyError, ValueError) as e:
            raise PromptError(f"Safaricom did not accept the request: {type(e).__name__}") from e


_fake = FakePrompts()


def get_prompts() -> PromptProvider:
    if settings.daraja_consumer_key and settings.daraja_consumer_secret and settings.platform_shortcode and settings.platform_passkey:
        return SafaricomPrompts()
    return _fake


def fake_prompts() -> FakePrompts:
    return _fake


def callback_key() -> str:
    """The secret part of the callback address. Safaricom cannot sign its calls, so the address is the secret; it is derived, not stored."""
    return hmac.new(settings.jwt_secret.encode(), b"subscription-pay", hashlib.sha256).hexdigest()[:40]


def callback_url() -> str:
    base = settings.public_api_url.rstrip("/") or "http://localhost:8010"
    return f"{base}/hooks/subscription-pay/{callback_key()}"


def parse_callback(body: dict) -> dict | None:
    """What Safaricom's answer says: {checkout_id, ok, note, amount, receipt}. None if it is not shaped like one."""
    try:
        cb = body["Body"]["stkCallback"]
        items = {i["Name"]: i.get("Value") for i in (cb.get("CallbackMetadata") or {}).get("Item", [])}
        return {"checkout_id": str(cb["CheckoutRequestID"]), "ok": int(cb["ResultCode"]) == 0, "note": str(cb.get("ResultDesc", ""))[:255], "amount": items.get("Amount"), "receipt": items.get("MpesaReceiptNumber")}
    except (KeyError, TypeError, ValueError):
        return None
