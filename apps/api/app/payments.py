"""Client payments by M-Pesa (masterplan 5.10). A payment is stored once per M-Pesa code, matched to an invoice by the
account number the client typed, and anything that cannot be matched with confidence waits in a queue for a person.

Matching is deliberately strict: a reference that names an open invoice is applied (up to what is owed); everything
else is left for the office, with the invoices that would fit suggested. Money is never guessed onto an invoice."""

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.debtor_rules import invoice_number_from
from app.invoicing import refresh_standing
from app.models import Invoice, InvoicePayment, MpesaTransaction
from app.reminders import NAIROBI, nairobi_today

CODE = re.compile(r"^[A-Z0-9]{8,12}$")
REASONS = {
    "no_reference": "The client did not type an account number.",
    "unknown_reference": "The account number is not an invoice number.",
    "unknown_invoice": "No invoice has that number.",
    "void_invoice": "That invoice was voided.",
    "already_paid": "That invoice is already paid.",
    "overpaid": "More was paid than the invoice was owed.",
}


class PaymentError(Exception):
    """A matching request that cannot be done. The text is safe to show."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


def parse_trans_time(raw: str | None) -> datetime:
    """Safaricom sends Nairobi time as YYYYMMDDHHMMSS."""
    try:
        return datetime.strptime((raw or "").strip(), "%Y%m%d%H%M%S").replace(tzinfo=NAIROBI).astimezone(UTC)
    except ValueError:
        return datetime.now(UTC)


def parse_amount_cents(raw: str | float | None) -> int:
    try:
        cents = round(float(str(raw).replace(",", "").strip()) * 100)
    except ValueError:
        raise PaymentError("bad_amount", "The amount is not a number.") from None
    if cents <= 0:
        raise PaymentError("bad_amount", "The amount must be more than zero.")
    return cents


def settle(txn: MpesaTransaction) -> None:
    """Sets the status from how much of the payment has been put against invoices."""
    if txn.status == "dismissed":
        return
    if txn.allocated_cents >= txn.amount_cents:
        txn.status, txn.reason = "matched", None
    elif txn.allocated_cents > 0:
        txn.status = "partly_matched"
    else:
        txn.status = "unmatched"


async def _locked_invoice(db: AsyncSession, invoice_id: uuid.UUID) -> Invoice | None:
    return (await db.execute(select(Invoice).where(Invoice.id == invoice_id).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()


async def allocate(db: AsyncSession, txn: MpesaTransaction, invoice_id: uuid.UUID, cents: int, user_id: uuid.UUID | None) -> InvoicePayment:
    """Puts `cents` of an M-Pesa payment against an invoice. Never more than the payment has left, never more than is owed."""
    invoice = await _locked_invoice(db, invoice_id)
    if invoice is None:
        raise PaymentError("not_found", "That invoice was not found.")
    if invoice.status == "void":
        raise PaymentError("void", "That invoice has been voided.")
    owed = invoice.total_cents - sum(p.amount_cents for p in invoice.payments)
    left = txn.amount_cents - txn.allocated_cents
    if txn.status == "dismissed":
        raise PaymentError("dismissed", "That payment was set aside.")
    if cents <= 0 or cents > left:
        raise PaymentError("too_much", f"Only KES {left / 100:,.2f} of this payment is left to match.")
    if cents > owed:
        raise PaymentError("overpayment", f"Only KES {owed / 100:,.2f} is still owed on {invoice.number}.")
    payment = InvoicePayment(
        amount_cents=cents, method="mpesa", reference=txn.trans_id, received_on=txn.paid_at.astimezone(NAIROBI).date(),
        note="M-Pesa" + (f" from {txn.payer_name}" if txn.payer_name else ""), mpesa_transaction_id=txn.id, created_by_user_id=user_id,
    )  # fmt: skip
    invoice.payments.append(payment)
    txn.allocated_cents += cents
    await db.flush()
    refresh_standing(invoice, nairobi_today())
    settle(txn)
    audit.record(
        db, actor_user_id=user_id, action="invoice.payment", entity_type="invoice", entity_id=invoice.id,
        after={"amount_cents": cents, "method": "mpesa", "mpesa_code": txn.trans_id, "status": invoice.status, "matched_by": "person" if user_id else "automatic"},
    )  # fmt: skip
    return payment


async def auto_match(db: AsyncSession, txn: MpesaTransaction) -> None:
    """Applies the payment when its account number names an open invoice; otherwise says why it could not."""
    number = invoice_number_from(txn.bill_ref)
    if number is None:
        txn.reason = "unknown_reference" if (txn.bill_ref or "").strip() else "no_reference"
        settle(txn)
        return
    invoice = (await db.execute(select(Invoice).where(Invoice.number == number))).scalar_one_or_none()
    if invoice is None:
        txn.reason = "unknown_invoice"
    elif invoice.status == "void":
        txn.reason = "void_invoice"
    else:
        owed = invoice.total_cents - sum(p.amount_cents for p in invoice.payments)
        if owed <= 0:
            txn.reason = "already_paid"
        else:
            await allocate(db, txn, invoice.id, min(owed, txn.amount_cents), None)
            if txn.allocated_cents < txn.amount_cents:
                txn.reason = "overpaid"
            return
    settle(txn)


async def record_payment(
    db: AsyncSession, *, trans_id: str, amount_cents: int, bill_ref: str | None, payer_name: str | None, payer_phone: str | None,
    shortcode: str | None, paid_at: datetime, source: str,
) -> tuple[MpesaTransaction, bool]:  # fmt: skip
    """Stores a payment and tries to match it. Returns (transaction, is_new). Safaricom sending the same payment again, or
    a statement listing one we already have, changes nothing."""
    trans_id = trans_id.strip().upper()
    if not CODE.match(trans_id):
        raise PaymentError("bad_code", "That is not an M-Pesa transaction code.")
    existing = (await db.execute(select(MpesaTransaction).where(MpesaTransaction.trans_id == trans_id))).scalar_one_or_none()
    if existing is not None:
        return existing, False
    txn = MpesaTransaction(
        trans_id=trans_id, amount_cents=amount_cents, bill_ref=(bill_ref or "").strip()[:60] or None, payer_name=(payer_name or "").strip()[:160] or None,
        payer_phone=(payer_phone or "").strip()[:80] or None, shortcode=shortcode, paid_at=paid_at, source=source,
    )  # fmt: skip
    try:
        async with db.begin_nested():
            db.add(txn)
            await db.flush()
    except IntegrityError:  # the same code arrived on two requests at once
        return (await db.execute(select(MpesaTransaction).where(MpesaTransaction.trans_id == trans_id))).scalar_one(), False
    manual_before = (await db.execute(select(InvoicePayment).where(InvoicePayment.reference == trans_id, InvoicePayment.mpesa_transaction_id.is_(None)))).scalars().first()
    if manual_before is not None:
        # The office already entered this payment by hand: it is accounted for, so do not count it twice.
        txn.allocated_cents = min(manual_before.amount_cents, txn.amount_cents)
        manual_before.mpesa_transaction_id = txn.id
        settle(txn)
        return txn, True
    await auto_match(db, txn)
    audit.record(db, actor_user_id=None, action="mpesa.payment_received", entity_type="mpesa_transaction", entity_id=txn.id, after={"trans_id": txn.trans_id, "amount_cents": txn.amount_cents, "status": txn.status, "source": source})
    return txn, True


async def suggestions(db: AsyncSession, txn: MpesaTransaction) -> list[Invoice]:
    """Open invoices that owe exactly what is left of this payment."""
    left = txn.amount_cents - txn.allocated_cents
    rows = (await db.execute(select(Invoice).where(Invoice.status.in_(("issued", "partially_paid"))).order_by(Invoice.due_date))).scalars().all()
    return [i for i in rows if i.total_cents - sum(p.amount_cents for p in i.payments) == left][:5]
