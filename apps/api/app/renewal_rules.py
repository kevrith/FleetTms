"""What a renewal must look like before a manager is asked to approve it (masterplan 5.1). Pure rules, server side only.

NTSA renews a driving licence when the fee is paid, and a licence is checked by ID number, so the payment receipt is real proof; a one-year
renewal also comes as a digital licence. An insurer sends a certificate. The manager looks at the proof and the date before approving."""

from datetime import date

from app.clearance_rules import LABELS

PROOFS = {
    "driving_licence": ("digital_licence", "receipt"),
    "insurance": ("certificate",),
}
OTHER_PROOFS = ("certificate", "receipt")
PROOF_LABELS = {"digital_licence": "the digital licence", "receipt": "the payment receipt", "certificate": "the certificate"}
LICENCE_DAYS = 3 * 365 + 31  # a driving licence is renewed for one or three years
YEAR_DAYS = 400  # insurance and the yearly inspection run for about a year


def horizon_days(doc_type: str) -> int:
    return YEAR_DAYS if doc_type in ("insurance", "inspection") else LICENCE_DAYS


def problem(*, doc_type: str, proof_kind: str, new_expires_on: date, current_expires_on: date | None, today: date) -> str | None:
    """Why this renewal cannot be sent, in plain words, or None."""
    allowed = PROOFS.get(doc_type, OTHER_PROOFS)
    label = LABELS.get(doc_type, doc_type).lower()
    if proof_kind not in allowed:
        return f"A {label} renewal needs {' or '.join(PROOF_LABELS[p] for p in allowed)}."
    if new_expires_on <= today:
        return "The new date must be in the future."
    if current_expires_on is not None and new_expires_on <= current_expires_on:
        return f"That is not later than the date on record ({current_expires_on.isoformat()})."
    if (new_expires_on - today).days > horizon_days(doc_type):
        return f"That is too far ahead for a {label}. Check the date."
    return None
