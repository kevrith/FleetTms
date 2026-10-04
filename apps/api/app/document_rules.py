"""Document reading (masterplan 5.28): turning what a reading service returned into clean values, and saying what does not add up so a
person checks it before confirming. A reading is never trusted on its own. Server side only: the web and the phone show these
warnings, they do not recompute them, so there is no TypeScript mirror."""

import re
from datetime import UTC, date, datetime, timedelta

KINDS = {
    "fuel_receipt": ["station", "fuel_type", "litres", "price_per_litre", "amount", "receipt_no", "mpesa_code", "date"],
    "weighbridge_ticket": ["ticket_no", "registration", "gross_kg", "tare_kg", "net_kg", "cargo", "date"],
    "delivery_note": ["reference", "recipient_name", "date", "description", "quantity", "notes"],
    "insurance_certificate": ["insurer", "policy_no", "registration", "cover_type", "valid_from", "valid_to"],
    "logbook": ["registration", "chassis_no", "engine_no", "make", "model", "year", "owner_name"],
    "odometer": ["reading", "unit"],  # read from a dashboard photo when a trip starts or ends; not offered through /document-readings
}
REQUIRED = {
    "fuel_receipt": ["litres", "amount"], "weighbridge_ticket": ["gross_kg", "net_kg"], "delivery_note": ["recipient_name", "date"],
    "insurance_certificate": ["policy_no", "valid_to"], "logbook": ["registration"], "odometer": ["reading"],
}  # fmt: skip
NUMBERS = {"litres": 2, "price_per_litre": 2, "amount": 2, "gross_kg": 0, "tare_kg": 0, "net_kg": 0, "quantity": 2, "year": 0, "reading": 0}
DATES = ("date", "valid_from", "valid_to")
TEXTS = ("station", "fuel_type", "receipt_no", "ticket_no", "cargo", "reference", "recipient_name", "description", "notes", "insurer", "policy_no", "cover_type", "chassis_no", "engine_no", "make", "model", "owner_name")


def _number(raw) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, int | float):
        return float(raw)
    text = re.sub(r"[^0-9.\-]", "", str(raw))  # units, currency, spaces and thousands separators all go
    try:
        return float(text)
    except ValueError:
        return None


def _date(raw) -> str | None:
    if not raw:
        return None
    text = str(raw).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(text[:10] if fmt == "%Y-%m-%d" else text, fmt).replace(tzinfo=UTC).date().isoformat()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except ValueError:
        return None


def plate(raw) -> str | None:
    """A Kenyan number plate as KCA 123A: capitals, one space between the letters and the digits."""
    if not raw:
        return None
    text = re.sub(r"[^A-Za-z0-9]", "", str(raw)).upper()
    m = re.fullmatch(r"([A-Z]{3})(\d{3})([A-Z])", text)
    return f"{m.group(1)} {m.group(2)}{m.group(3)}" if m else (text or None)


def mpesa_code(raw) -> str | None:
    text = re.sub(r"[^A-Za-z0-9]", "", str(raw or "")).upper()
    return text if re.fullmatch(r"[A-Z0-9]{10}", text) else None


def normalise(kind: str, raw: dict) -> dict:
    """Every field the document type has, as a clean value or None: numbers as numbers, dates as ISO dates, plates tidied."""
    out: dict = {}
    for name in KINDS[kind]:
        value = raw.get(name)
        if name in NUMBERS:
            n = _number(value)
            out[name] = None if n is None else (round(n, NUMBERS[name]) if NUMBERS[name] else round(n))
        elif name in DATES:
            out[name] = _date(value)
        elif name == "registration":
            out[name] = plate(value)
        elif name == "mpesa_code":
            out[name] = mpesa_code(value)
        elif name in TEXTS:
            text = str(value).strip() if value not in (None, "") else None
            out[name] = text[:200] if text else None
    return out


def check(kind: str, fields: dict, *, registration: str | None = None, gvw_limit_kg: int | None = None, today: date | None = None) -> dict:
    """What is missing and what does not add up. `registration` is the vehicle the person says the document is for."""
    today = today or datetime.now(UTC).date()
    warnings: list[str] = []
    missing = [f for f in REQUIRED[kind] if fields.get(f) is None]
    if kind == "fuel_receipt":
        litres, price, amount = fields.get("litres"), fields.get("price_per_litre"), fields.get("amount")
        if litres and price and amount and abs(litres * price - amount) > max(1.0, amount * 0.01):
            warnings.append(f"{litres:g} litres at {price:g} is {litres * price:,.2f}, but the total read is {amount:,.2f}.")
        if price is not None and not 100 <= price <= 400:
            warnings.append(f"A price of {price:g} a litre is not what fuel costs in Kenya: check the digits.")
        if litres is not None and litres > 1500:
            warnings.append(f"{litres:g} litres is more than a tank holds: check the digits.")
        when = fields.get("date")
        if when and date.fromisoformat(when) > today:
            warnings.append("The date on the receipt is in the future.")
        elif when and date.fromisoformat(when) < today - timedelta(days=30):
            warnings.append("The receipt is more than 30 days old.")
    elif kind == "weighbridge_ticket":
        gross, tare, net = fields.get("gross_kg"), fields.get("tare_kg"), fields.get("net_kg")
        if gross and tare and net and abs(gross - tare - net) > 20:
            warnings.append(f"Gross {gross:,} less tare {tare:,} is {gross - tare:,} kg, but the net read is {net:,} kg.")
        if gross and gvw_limit_kg and gross > gvw_limit_kg:
            warnings.append(f"The gross weight of {gross:,} kg is over this vehicle's legal limit of {gvw_limit_kg:,} kg.")
    elif kind == "insurance_certificate":
        start, end = fields.get("valid_from"), fields.get("valid_to")
        if start and end and end < start:
            warnings.append("The cover ends before it starts: check the dates.")
        if end and end < today.isoformat():
            warnings.append("This certificate has already expired.")
    elif kind == "logbook" and fields.get("year") and not 1950 <= fields["year"] <= today.year + 1:
        warnings.append(f"A year of {fields['year']} is not possible: check it.")
    if registration and fields.get("registration") and fields["registration"] != plate(registration):
        warnings.append(f"The document is for {fields['registration']}, but you chose {plate(registration)}.")
    return {"warnings": warnings, "missing": missing}
