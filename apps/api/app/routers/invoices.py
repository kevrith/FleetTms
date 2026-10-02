"""Invoices and payments (masterplan 5.10): issued automatically when a delivery is proven, or monthly for a contract;
payments are entered by hand for now. A trip invoice's PDF carries its proof of delivery."""

import io
import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.billing_rules import invoice_standing
from app.db import get_db
from app.deps import Principal, error, require_any
from app.invoice_files import invoice_pdf
from app.invoicing import contract_invoices, invoice_for_trip, month_bounds, refresh_standing
from app.models import Business, Client, Invoice, InvoicePayment, Photo, ProofOfDelivery, Trip
from app.reminders import nairobi_today
from app.report_delivery import DeliveryError, get_report_sender
from app.sms import get_sms_sender

router = APIRouter(tags=["invoices"])
MANAGE = ("invoices.manage",)
METHODS = ("cash", "mpesa", "bank", "cheque")


class PaymentIn(BaseModel):
    amount_cents: int = Field(gt=0, le=10_000_000_000)
    method: Literal["cash", "mpesa", "bank", "cheque"]
    reference: str | None = Field(default=None, max_length=60)
    received_on: date | None = None
    note: str | None = Field(default=None, max_length=255)


class VoidIn(BaseModel):
    reason: str = Field(min_length=3, max_length=255)


class SendIn(BaseModel):
    channel: Literal["email", "whatsapp", "sms"]
    recipient: str | None = Field(default=None, max_length=255)


class TripInvoiceIn(BaseModel):
    weight_kg: int | None = Field(default=None, gt=0, le=200_000)  # the office's own weight, when there is no weighbridge ticket


class ContractRunIn(BaseModel):
    month: date  # any day in the month to bill


def invoice_out(i: Invoice, client_name: str | None = None, *, detail: bool = False) -> dict:
    standing = invoice_standing(total_cents=i.total_cents, paid=[p.amount_cents for p in i.payments], voided=i.status == "void", due=i.due_date, today=nairobi_today())
    out = {
        "id": i.id, "number": i.number, "client_id": i.client_id, "client_name": client_name, "kind": i.kind, "job_id": i.job_id,
        "trip_id": i.trip_id, "period_start": i.period_start, "period_end": i.period_end, "issue_date": i.issue_date,
        "due_date": i.due_date, "status": standing["status"], "overdue": standing["overdue"], "subtotal_cents": i.subtotal_cents,
        "vat_pct": float(i.vat_pct), "vat_cents": i.vat_cents, "total_cents": i.total_cents, "paid_cents": standing["paid_cents"],
        "balance_cents": standing["balance_cents"], "void_reason": i.void_reason, "sent_via": i.sent_via, "sent_at": i.sent_at,
    }  # fmt: skip
    if detail:
        out["lines"] = [{"id": ln.id, "trip_id": ln.trip_id, "description": ln.description, "quantity": float(ln.quantity), "unit_cents": ln.unit_cents, "amount_cents": ln.amount_cents} for ln in i.lines]
        out["payments"] = [{"id": p.id, "amount_cents": p.amount_cents, "method": p.method, "reference": p.reference, "received_on": p.received_on, "note": p.note} for p in i.payments]
    return out


async def _get(db: AsyncSession, invoice_id: uuid.UUID) -> Invoice:
    invoice = (await db.execute(select(Invoice).where(Invoice.id == invoice_id))).scalar_one_or_none()
    if invoice is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That invoice was not found.")
    return invoice


async def _client(db: AsyncSession, client_id: uuid.UUID) -> Client:
    return (await db.execute(select(Client).where(Client.id == client_id))).scalar_one()


@router.get("/invoices")
async def list_invoices(
    status_filter: str | None = None, client_id: uuid.UUID | None = None, trip_id: uuid.UUID | None = None, unpaid_only: bool = False,
    principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db),
):
    query = select(Invoice).order_by(Invoice.created_at.desc()).limit(300)
    if client_id:
        query = query.where(Invoice.client_id == client_id)
    if trip_id:
        query = query.where(Invoice.trip_id == trip_id)
    names = {c.id: c.name for c in (await db.execute(select(Client))).scalars()}
    rows = [invoice_out(i, names.get(i.client_id)) for i in (await db.execute(query)).scalars()]
    if status_filter:
        rows = [r for r in rows if r["status"] == status_filter]
    if unpaid_only:
        rows = [r for r in rows if r["balance_cents"] > 0]
    return rows


@router.get("/invoices/{invoice_id}")
async def read_invoice(invoice_id: uuid.UUID, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    invoice = await _get(db, invoice_id)
    return invoice_out(invoice, (await _client(db, invoice.client_id)).name, detail=True)


@router.get("/invoices/{invoice_id}/pdf")
async def invoice_file(invoice_id: uuid.UUID, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    invoice = await _get(db, invoice_id)
    pdf = await _pdf(db, principal, invoice)
    return StreamingResponse(io.BytesIO(pdf), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{invoice.number}.pdf"'})


async def _pdf(db: AsyncSession, principal: Principal, invoice: Invoice) -> bytes:
    client = await _client(db, invoice.client_id)
    business = (await db.execute(select(Business).where(Business.id == principal.business_id))).scalar_one()
    pod = trip = None
    photos: dict = {}
    if invoice.trip_id:
        trip = (await db.execute(select(Trip).where(Trip.id == invoice.trip_id))).scalar_one_or_none()
        pod = (await db.execute(select(ProofOfDelivery).where(ProofOfDelivery.trip_id == invoice.trip_id))).scalar_one_or_none()
        if pod:
            ids = [i for i in [pod.cargo_photo_id, pod.note_photo_id, trip.weighbridge_photo_id if trip else None, *[uuid.UUID(d) for d in pod.damage_photo_ids]] if i]
            photos = {p.id: p for p in (await db.execute(select(Photo).where(Photo.id.in_(ids)))).scalars()}
    return invoice_pdf(invoice, client, business.name, pod=pod, photos=photos, trip=trip)


@router.post("/invoices/{invoice_id}/payments", status_code=status.HTTP_201_CREATED)
async def add_payment(invoice_id: uuid.UUID, body: PaymentIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    """Records money received against an invoice. It cannot be more than what is still owed."""
    invoice = await _get(db, invoice_id)
    if invoice.status == "void":
        raise error(status.HTTP_409_CONFLICT, "void", "That invoice has been voided.")
    owed = invoice.total_cents - sum(p.amount_cents for p in invoice.payments)
    if body.amount_cents > owed:
        raise error(422, "overpayment", f"Only KES {owed / 100:,.2f} is still owed on this invoice.")
    invoice.payments.append(
        InvoicePayment(
            amount_cents=body.amount_cents, method=body.method, reference=(body.reference or "").strip() or None,
            received_on=body.received_on or nairobi_today(), note=body.note, created_by_user_id=principal.user.id,
        )
    )  # fmt: skip
    await db.flush()
    refresh_standing(invoice)
    audit.record(db, actor_user_id=principal.user.id, action="invoice.payment", entity_type="invoice", entity_id=invoice.id, after={"amount_cents": body.amount_cents, "method": body.method, "status": invoice.status})
    await db.commit()
    return invoice_out(invoice, (await _client(db, invoice.client_id)).name, detail=True)


@router.post("/invoices/{invoice_id}/void")
async def void_invoice(invoice_id: uuid.UUID, body: VoidIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    invoice = await _get(db, invoice_id)
    if invoice.status == "void":
        return invoice_out(invoice, (await _client(db, invoice.client_id)).name, detail=True)
    if invoice.payments:
        raise error(status.HTTP_409_CONFLICT, "has_payments", "An invoice with payments cannot be voided.")
    invoice.status, invoice.void_reason = "void", body.reason
    audit.record(db, actor_user_id=principal.user.id, action="invoice.voided", entity_type="invoice", entity_id=invoice.id, note=body.reason)
    await db.commit()
    return invoice_out(invoice, (await _client(db, invoice.client_id)).name, detail=True)


@router.post("/invoices/{invoice_id}/send")
async def send_invoice(invoice_id: uuid.UUID, body: SendIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    """Sends the client the invoice: a PDF (with the proof of delivery) by email or WhatsApp, or a short text by SMS."""
    from datetime import UTC, datetime

    invoice = await _get(db, invoice_id)
    client = await _client(db, invoice.client_id)
    recipient = (body.recipient or (client.email if body.channel == "email" else client.phone) or "").strip()
    if not recipient:
        raise error(422, "no_recipient", f"The client has no {'email address' if body.channel == 'email' else 'phone number'}. Enter one.")
    business = (await db.execute(select(Business).where(Business.id == principal.business_id))).scalar_one()
    try:
        if body.channel == "sms":
            await get_sms_sender().send(recipient, f"{business.name}: invoice {invoice.number} for KES {invoice.total_cents / 100:,.2f}, due {invoice.due_date.isoformat()}.")
        else:
            await get_report_sender(body.channel).send(recipient, f"Invoice {invoice.number} from {business.name}", f"{invoice.number}.pdf", await _pdf(db, principal, invoice))
    except DeliveryError as e:
        raise error(502, "delivery_failed", str(e)) from None
    invoice.sent_via, invoice.sent_at = body.channel, datetime.now(UTC)
    audit.record(db, actor_user_id=principal.user.id, action="invoice.sent", entity_type="invoice", entity_id=invoice.id, after={"channel": body.channel})
    await db.commit()
    return invoice_out(invoice, client.name, detail=True)


@router.post("/trips/{trip_id}/invoice")
async def invoice_trip(trip_id: uuid.UUID, body: TripInvoiceIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    """Invoices a delivered trip that could not be invoiced automatically, for example a per-tonne trip with no weighbridge
    ticket: the office enters the weight themselves, and that is recorded."""
    trip = (await db.execute(select(Trip).where(Trip.id == trip_id))).scalar_one_or_none()
    if trip is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That trip was not found.")
    if trip.status.value not in ("delivered", "completed"):
        raise error(status.HTTP_409_CONFLICT, "not_delivered", "Only a delivered trip can be invoiced.")
    invoice, why = await invoice_for_trip(db, trip, principal.user.id, weight_kg=body.weight_kg)
    if invoice is None:
        messages = {
            "weight_required": "This job is billed per tonne and the trip has no weighbridge weight. Enter the weight.",
            "distance_required": "This job is billed per km but its route has no distance.",
            "contract": "A monthly contract is invoiced once a month, not per trip.",
            "no_job": "This trip is not part of a client job.",
        }
        raise error(422, why or "cannot_invoice", messages.get(why or "", "This trip cannot be invoiced."))
    if body.weight_kg is not None:
        trip.loaded_weight_kg = body.weight_kg
        audit.record(db, actor_user_id=principal.user.id, action="trip.weight_entered_by_office", entity_type="trip", entity_id=trip.id, after={"loaded_weight_kg": body.weight_kg})
    await db.commit()
    return invoice_out(invoice, (await _client(db, invoice.client_id)).name, detail=True)


@router.post("/invoices/contracts/run")
async def run_contracts(body: ContractRunIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    """Issues the monthly invoices for contract jobs for a month. Safe to run again: a job is billed once a month."""
    start, _ = month_bounds(body.month)
    if start > nairobi_today():
        raise error(422, "future_month", "That month has not started yet.")
    made = await contract_invoices(db, body.month, principal.user.id)
    await db.commit()
    names = {c.id: c.name for c in (await db.execute(select(Client))).scalars()}
    return {"month": start, "issued": [invoice_out(i, names.get(i.client_id)) for i in made]}


@router.get("/trips/{trip_id}/invoice")
async def trip_invoice(trip_id: uuid.UUID, principal: Principal = Depends(require_any(*MANAGE, "trips.view")), db: AsyncSession = Depends(get_db)):
    """The invoice for a trip, if there is one and the caller may see invoices, so the trip page can link to it."""
    invoice = (await db.execute(select(Invoice).where(Invoice.trip_id == trip_id))).scalar_one_or_none()
    if invoice is None or "invoices.manage" not in principal.permissions:
        return {"invoice": None}
    return {"invoice": invoice_out(invoice, (await _client(db, invoice.client_id)).name)}
