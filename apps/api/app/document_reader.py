"""Document reading (masterplan 5.28): a cloud vision model reads a photographed receipt, ticket, note, certificate or logbook into
fields. It is asked for a structured answer through a tool, and what comes back is only ever a suggestion: app/document_rules.py tidies
and checks it, and a person confirms it. Without a key (and not in test mode) reading is switched off."""

import base64
import logging
from typing import Protocol

import httpx

from app.config import settings
from app.document_rules import KINDS

log = logging.getLogger(__name__)
URL = "https://api.anthropic.com/v1/messages"
HINTS = {
    "fuel_receipt": "a fuel station receipt from Kenya. Amounts are Kenya shillings. fuel_type is diesel or petrol. mpesa_code is the 10 character M-Pesa code if one is printed.",
    "weighbridge_ticket": "a weighbridge ticket. Weights are in kilograms (convert tonnes to kilograms). registration is the vehicle's number plate.",
    "delivery_note": "a signed delivery note. recipient_name is who received the goods; quantity is the number of units, bags or tonnes delivered; notes holds any shortage or damage written on it.",
    "insurance_certificate": "a motor insurance certificate. valid_from and valid_to are the cover period. cover_type is comprehensive or third party.",
    "odometer": "a photograph of a vehicle's dashboard odometer. reading is the total distance shown on the main odometer as a whole number, not the trip meter or the clock. unit is km or mi as shown or marked.",
    "logbook": "a Kenyan vehicle logbook (registration certificate). year is the year of manufacture.",
}
NUMBER_FIELDS = {"reading", "litres", "price_per_litre", "amount", "gross_kg", "tare_kg", "net_kg", "quantity", "year"}


class ReadError(Exception):
    """The document could not be read. The text is safe to show."""


class DocumentReader(Protocol):
    name: str

    async def read(self, kind: str, image: bytes, content_type: str) -> dict: ...


def schema_for(kind: str) -> dict:
    props = {f: {"type": ["number", "null"] if f in NUMBER_FIELDS else ["string", "null"], "description": "null if it cannot be read"} for f in KINDS[kind]}
    props["confidence"] = {"type": "number", "description": "0 to 1: how sure you are that the fields above are right"}
    return {"type": "object", "properties": props, "required": ["confidence"]}


class FakeReader:
    """Tests and local development: returns what it is given, and keeps what it was asked."""

    name = "fake"

    def __init__(self) -> None:
        self.result: dict | None = None
        self.fail_with: str | None = None
        self.calls: list[tuple[str, int, str]] = []

    async def read(self, kind: str, image: bytes, content_type: str) -> dict:
        self.calls.append((kind, len(image), content_type))
        if self.fail_with:
            raise ReadError(self.fail_with)
        return self.result if self.result is not None else {"confidence": 0.0}


class ClaudeReader:
    name = "claude"

    async def read(self, kind: str, image: bytes, content_type: str) -> dict:
        body = {
            "model": settings.document_reader_model, "max_tokens": 1024,
            "tools": [{"name": "record_document", "description": f"Record what is written on {HINTS[kind]}", "input_schema": schema_for(kind)}],
            "tool_choice": {"type": "tool", "name": "record_document"},
            "messages": [{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": content_type, "data": base64.b64encode(image).decode()}},
                {"type": "text", "text": f"This is {HINTS[kind]} Record exactly what is printed or written. Never guess a value you cannot see: use null."},
            ]}],
        }  # fmt: skip
        headers = {"x-api-key": settings.anthropic_api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=60) as http:
                res = await http.post(URL, headers=headers, json=body)
                res.raise_for_status()
                blocks = res.json()["content"]
        except (httpx.HTTPError, KeyError, ValueError) as e:
            log.warning("The document reading service did not answer: %s", type(e).__name__)
            raise ReadError("The document could not be read just now. Try again, or type it in.") from None
        for block in blocks:
            if block.get("type") == "tool_use" and isinstance(block.get("input"), dict):
                return block["input"]
        raise ReadError("The document could not be read. Take a clearer, closer photo, or type it in.")


_fake = FakeReader()


def get_reader() -> DocumentReader:
    if settings.document_reader == "fake":
        return _fake
    if settings.anthropic_api_key and settings.document_reader in ("", "claude"):
        return ClaudeReader()
    raise ReadError("Document reading is not switched on for this system.")


def fake_reader() -> FakeReader:
    return _fake
