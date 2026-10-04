"""Paying a subscription invoice by card, on the card provider's own hosted page (Paystack): FleetTms sends the customer there with the
amount and a reference, never sees a card number, and learns the result two ways, so a missed one cannot lose a payment: the provider's
signed webhook, and a check of the reference with the provider when the customer comes back. Whatever answers first settles the invoice;
the other finds it already settled. Without a key a stand-in is used in development, so nothing leaves the machine.

The rest of the app talks only to `CardProvider` (start a payment, check a payment), so changing provider means one new class here."""

import hmac
import logging
from dataclasses import dataclass
from hashlib import sha512
from typing import Protocol

import httpx

from app.config import settings

log = logging.getLogger(__name__)
CURRENCY = "KES"


class CardError(Exception):
    """The provider did not accept the request. The text is safe to show to the person paying."""


@dataclass(frozen=True)
class Charge:
    reference: str
    status: str  # success, failed or pending
    amount_cents: int = 0
    currency: str = CURRENCY


class CardProvider(Protocol):
    async def start(self, *, email: str, amount_cents: int, reference: str, callback_url: str, description: str) -> str:
        """Opens a payment and returns the address of the page the customer pays on."""
        ...

    async def check(self, reference: str) -> Charge: ...


class FakeCards:
    """Keeps the payments that would have been started, and answers checks from what a test sets in `results`."""

    def __init__(self) -> None:
        self.started: list[dict] = []
        self.results: dict[str, Charge] = {}
        self.fail_with: str | None = None

    def reset(self) -> None:
        self.started.clear(), self.results.clear()
        self.fail_with = None

    async def start(self, *, email: str, amount_cents: int, reference: str, callback_url: str, description: str) -> str:
        if self.fail_with:
            raise CardError(self.fail_with)
        self.started.append({"email": email, "amount_cents": amount_cents, "reference": reference, "callback_url": callback_url, "description": description})
        return f"https://checkout.example.test/pay/{reference}"

    async def check(self, reference: str) -> Charge:
        if self.fail_with:
            raise CardError(self.fail_with)
        return self.results.get(reference, Charge(reference, "pending"))


class Paystack:
    """Paystack's hosted checkout. Amounts are in the currency's smallest unit, which for shillings is the cents we already use."""

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {settings.paystack_secret_key}"}

    async def _call(self, method: str, path: str, **kw) -> dict:
        try:
            async with httpx.AsyncClient(timeout=30, base_url=settings.paystack_base_url) as http:
                res = await http.request(method, path, headers=self._headers(), **kw)
            data = res.json()
        except httpx.HTTPError as e:
            raise CardError(f"The card payment service could not be reached: {type(e).__name__}") from e
        except ValueError:
            raise CardError("The card payment service sent back something unreadable.") from None
        if res.status_code >= 400 or not data.get("status"):
            raise CardError(f"The card payment service did not accept the request. {data.get('message') or ''}"[:250].strip())
        return data.get("data") or {}

    async def start(self, *, email: str, amount_cents: int, reference: str, callback_url: str, description: str) -> str:
        data = await self._call(
            "POST", "/transaction/initialize",
            json={"email": email, "amount": amount_cents, "currency": CURRENCY, "reference": reference, "callback_url": callback_url, "channels": ["card"], "metadata": {"description": description}},
        )  # fmt: skip
        url = data.get("authorization_url")
        if not url:
            raise CardError("The card payment service sent back no payment page.")
        return str(url)

    async def check(self, reference: str) -> Charge:
        data = await self._call("GET", f"/transaction/verify/{reference}")
        return charge_from(data, fallback_reference=reference)


def charge_from(data: dict, *, fallback_reference: str = "") -> Charge:
    """Paystack's description of a transaction, as a Charge. Anything not clearly a success or a failure is still pending."""
    state = str(data.get("status") or "")
    status = "success" if state == "success" else "failed" if state in ("failed", "abandoned", "reversed") else "pending"
    try:
        amount = int(data.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0
    return Charge(str(data.get("reference") or fallback_reference), status, amount, str(data.get("currency") or ""))


def signature_ok(body: bytes, header: str | None) -> bool:
    """Paystack signs every webhook with the secret key: x-paystack-signature is the HMAC SHA-512 of the body, in hex."""
    if not settings.paystack_secret_key or not header:
        return False
    return hmac.compare_digest(hmac.new(settings.paystack_secret_key.encode(), body, sha512).hexdigest(), header.strip().lower())


def parse_webhook(payload: object) -> Charge | None:
    """The charge a webhook reports, if it reports one we act on (a successful charge); otherwise None."""
    if not isinstance(payload, dict) or payload.get("event") != "charge.success" or not isinstance(payload.get("data"), dict):
        return None
    charge = charge_from(payload["data"])
    return charge if charge.reference and charge.status == "success" else None


_fake = FakeCards()


def is_live() -> bool:
    return bool(settings.paystack_secret_key)


def available() -> bool:
    """Whether paying by card is on offer: the provider is set up, or this is development, where the stand-in is used."""
    return is_live() or settings.environment != "production"


def get_cards() -> CardProvider:
    return Paystack() if is_live() else _fake


def fake_cards() -> FakeCards:
    return _fake
