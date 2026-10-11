"""What a renewal's proof says against what was typed (masterplan 5.28). The reading is a suggestion and a forged file can read perfectly, so
nothing here approves or refuses anything: it gives the approver short findings to look at. Pure rules, server side only."""

import re
from datetime import date, timedelta

from app.document_rules import plate

RECEIPT_DAYS = 45  # a licence fee paid longer ago than this is probably not the renewal being claimed
LOW_CONFIDENCE = 0.5


def _tokens(name: str | None) -> set[str]:
    return {t for t in re.sub(r"[^a-z ]", " ", (name or "").lower()).split() if len(t) > 1}


def same_person(a: str | None, b: str | None) -> bool | None:
    """True when every word of the shorter name is in the longer (so 'John Mwangi' matches 'MWANGI JOHN KAMAU'); None when either is missing."""
    x, y = _tokens(a), _tokens(b)
    if not x or not y:
        return None
    small, big = (x, y) if len(x) <= len(y) else (y, x)
    return small <= big


def _said(level: str, text: str) -> dict:
    return {"level": level, "text": text}


def compare(*, kind: str, fields: dict, confidence: float | None, typed: dict, today: date) -> dict:
    """`kind` is insurance_certificate, driving_licence or licence_receipt. `typed` holds new_expires_on, name, registration and reference as
    sent with the renewal. Returns {"status": "ok" | "warn" | "unreadable", "findings": [{"level": "ok" | "warn" | "info", "text"}]}."""
    findings: list[dict] = []
    if confidence is not None and confidence < LOW_CONFIDENCE:
        findings.append(_said("warn", "The file was hard to read, so the details below may be wrong. Look at it yourself."))
    if not any(v for k, v in fields.items() if k != "confidence"):
        return {"status": "unreadable", "findings": [_said("warn", "Nothing could be read from this file. Look at it yourself.")]}

    new = typed["new_expires_on"]
    if kind in ("insurance_certificate", "driving_licence"):
        end = fields.get("valid_to")
        if end is None:
            findings.append(_said("warn", "No expiry date could be read from the file."))
        elif end == new.isoformat():
            findings.append(_said("ok", f"The file says it is valid until {end}, as typed."))
        else:
            findings.append(_said("warn", f"The file says it is valid until {end}, but {new.isoformat()} was typed."))
        if end and end < today.isoformat():
            findings.append(_said("warn", "The date on the file is already past."))
    if kind == "insurance_certificate":
        read_plate = fields.get("registration")
        if read_plate and typed.get("registration"):
            right = read_plate == plate(typed["registration"])
            findings.append(_said("ok" if right else "warn", f"The file is for {read_plate}" + (", the lorry chosen." if right else f", not {plate(typed['registration'])}.")))
    if kind in ("driving_licence", "licence_receipt"):
        read_name = fields.get("holder_name") if kind == "driving_licence" else fields.get("payer_name")
        match = same_person(read_name, typed.get("name"))
        if match is True:
            findings.append(_said("ok", f"The name on the file ({read_name}) matches {typed['name']}."))
        elif match is False:
            findings.append(_said("warn", f"The name on the file is {read_name}, but this is for {typed['name']}."))
        else:
            findings.append(_said("info", "No name could be compared."))
    if kind == "licence_receipt":
        paid = fields.get("paid_on")
        if paid is None:
            findings.append(_said("warn", "No payment date could be read from the receipt."))
        elif paid > today.isoformat():
            findings.append(_said("warn", f"The payment date ({paid}) is in the future."))
        elif paid < (today - timedelta(days=RECEIPT_DAYS)).isoformat():
            findings.append(_said("warn", f"The receipt was paid on {paid}, more than {RECEIPT_DAYS} days ago."))
        else:
            findings.append(_said("ok", f"Paid on {paid}."))
        ref_read, ref_typed = (fields.get("reference") or "").strip().upper(), (typed.get("reference") or "").strip().upper()
        if ref_read and ref_typed:
            findings.append(_said("ok" if ref_read == ref_typed else "warn", "The receipt number matches." if ref_read == ref_typed else f"The receipt says {ref_read}, but {ref_typed} was typed."))
        findings.append(_said("info", "A receipt does not carry the new expiry date, so that date is the one you are trusting."))
    return {"status": "warn" if any(f["level"] == "warn" for f in findings) else "ok", "findings": findings}
