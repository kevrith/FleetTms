"""Invoices (masterplan 5.10): one per delivered trip, automatically when the proof of delivery is confirmed, and one a
month per contract job listing the trips it covered. Amounts come from billing_rules, which the web also uses."""

import calendar
import logging
import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.billing_rules import invoice_standing, invoice_totals, trip_amount
from app.db import get_sessionmaker
from app.etims_service import queue_sale
from app.invoice_files import invoice_pdf
from app.models import (
    Business,
    Client,
    EtimsSubmission,
    Invoice,
    InvoiceLine,
    Job,
    JobStatus,
    Photo,
    ProofOfDelivery,
    SavedRoute,
    Trip,
    TripStatus,
)
from app.numbering import create_numbered
from app.payment_config import get_settings
from app.quote_rules import BillingMethod
from app.reminders import NAIROBI, nairobi_today
from app.tenancy import current_business_id

log = logging.getLogger(__name__)


def kes(cents: int) -> str:
    return f"KES {cents / 100:,.2f}"


def refresh_standing(invoice: Invoice, today: date | None = None) -> dict:
    """Brings status and paid amount in line with the payments, and says where the invoice stands."""
    standing = invoice_standing(
        total_cents=invoice.total_cents, paid=[p.amount_cents for p in invoice.payments], voided=invoice.status == "void",
        due=invoice.due_date, today=today or nairobi_today(),
    )  # fmt: skip
    invoice.paid_cents, invoice.status = standing["paid_cents"], standing["status"]
    return standing


def _lines_total(lines: list[InvoiceLine]) -> list[int]:
    return [line.amount_cents for line in lines]


async def invoice_for_trip(
    db: AsyncSession, trip: Trip, user_id: uuid.UUID | None, *, weight_kg: int | None = None, trust_weight: bool = False
) -> tuple[Invoice | None, str | None]:
    """Bills a delivered trip. Returns (invoice, None), or (None, why not): no_job, contract, weight_required or
    distance_required. `weight_kg` / `trust_weight` let the office bill a per-tonne trip from a weight they entered
    themselves when the driver did not record the weighbridge ticket."""
    existing = (await db.execute(select(Invoice).where(Invoice.trip_id == trip.id))).scalar_one_or_none()
    if existing is not None:
        return existing, None
    if trip.job_id is None:
        return None, "no_job"
    job = (await db.execute(select(Job).where(Job.id == trip.job_id))).scalar_one()
    if job.billing_method == BillingMethod.MONTHLY_CONTRACT:
        return None, "contract"
    client = (await db.execute(select(Client).where(Client.id == job.client_id))).scalar_one()
    route = (await db.execute(select(SavedRoute).where(SavedRoute.id == job.route_id))).scalar_one_or_none() if job.route_id else None
    weight = weight_kg if weight_kg is not None else trip.loaded_weight_kg
    if job.billing_method == BillingMethod.PER_TONNE and weight_kg is None and not (trip.weighbridge_photo_id or trust_weight):
        return None, "weight_required"  # a per-tonne trip is billed from the weighbridge ticket
    amount = trip_amount(method=job.billing_method, rate_cents=job.rate_cents, weight_kg=weight, distance_km=route.distance_km if route else None)
    if amount is None:
        return None, "weight_required" if job.billing_method == BillingMethod.PER_TONNE else "distance_required"

    where = f"{route.pickup} to {route.dropoff}" if route else (f"{trip.origin} to {trip.destination}" if trip.origin else "Transport")
    delivered = (trip.delivered_at or trip.ended_at)
    when = f", delivered {delivered.astimezone(NAIROBI).strftime('%d %b %Y')}" if delivered else ""
    if job.billing_method == BillingMethod.PER_TONNE:
        quantity, detail = Decimal(weight) / 1000, f"{weight / 1000:,.3f} t at {kes(job.rate_cents)} per tonne (weighbridge)"
    elif job.billing_method == BillingMethod.PER_KM:
        quantity, detail = Decimal(route.distance_km), f"{route.distance_km:,} km at {kes(job.rate_cents)} per km"
    else:
        quantity, detail = Decimal(1), "per trip"
    line = InvoiceLine(trip_id=trip.id, description=f"Transport {where}{when} ({job.number}): {detail}"[:255], quantity=quantity, unit_cents=job.rate_cents, amount_cents=amount, sort_order=0)
    totals = invoice_totals([amount], float(client.vat_pct))
    today = nairobi_today()
    invoice = await create_numbered(
        db, Invoice, "INV", client_id=client.id, job_id=job.id, trip_id=trip.id, kind="trip", issue_date=today,
        due_date=today + timedelta(days=client.payment_terms_days), status="issued", vat_pct=client.vat_pct,
        created_by_user_id=user_id, lines=[line], payments=[], **totals,
    )  # fmt: skip
    audit.record(db, actor_user_id=user_id, action="invoice.issued", entity_type="invoice", entity_id=invoice.id, after={"number": invoice.number, "total_cents": invoice.total_cents, "trip_id": str(trip.id)})
    await queue_sale(db, invoice)
    return invoice, None


def month_bounds(day: date) -> tuple[date, date]:
    return day.replace(day=1), day.replace(day=calendar.monthrange(day.year, day.month)[1])


async def contract_invoices(db: AsyncSession, month: date, user_id: uuid.UUID | None = None) -> list[Invoice]:
    """One invoice per contract job for the month: the monthly fee, then every trip it covered (at no extra charge)."""
    start, end = month_bounds(month)
    made: list[Invoice] = []
    jobs = (await db.execute(select(Job).where(Job.billing_method == BillingMethod.MONTHLY_CONTRACT, Job.status != JobStatus.CANCELLED))).scalars().all()
    for job in jobs:
        if job.created_at.astimezone(NAIROBI).date() > end or (job.completed_at is not None and job.completed_at.astimezone(NAIROBI).date() < start):
            continue  # not running in that month
        if (await db.execute(select(Invoice.id).where(Invoice.job_id == job.id, Invoice.period_start == start))).first() is not None:
            continue
        client = (await db.execute(select(Client).where(Client.id == job.client_id))).scalar_one()
        route = (await db.execute(select(SavedRoute).where(SavedRoute.id == job.route_id))).scalar_one_or_none() if job.route_id else None
        trips = [
            t for t in (await db.execute(select(Trip).where(Trip.job_id == job.id, Trip.status.in_((TripStatus.DELIVERED, TripStatus.COMPLETED))).order_by(Trip.delivered_at))).scalars()
            if (t.delivered_at or t.ended_at) and start <= (t.delivered_at or t.ended_at).astimezone(NAIROBI).date() <= end
        ]  # fmt: skip
        where = f"{route.pickup} to {route.dropoff}" if route else "transport"
        lines = [InvoiceLine(description=f"Monthly contract {job.number}: {where}, {start.strftime('%B %Y')} ({len(trips)} trip{'s' if len(trips) != 1 else ''})"[:255], quantity=Decimal(1), unit_cents=job.rate_cents, amount_cents=job.rate_cents, sort_order=0)]
        for n, t in enumerate(trips, start=1):
            moved = (t.delivered_at or t.ended_at).astimezone(NAIROBI).strftime("%d %b")
            weight = f", {t.loaded_weight_kg / 1000:,.1f} t" if t.loaded_weight_kg else ""
            lines.append(InvoiceLine(trip_id=t.id, description=f"Trip {n}: {moved}, {where}{weight} (covered by the monthly fee)"[:255], quantity=Decimal(1), unit_cents=0, amount_cents=0, sort_order=n))
        totals = invoice_totals(_lines_total(lines), float(client.vat_pct))
        today = nairobi_today()
        invoice = await create_numbered(
            db, Invoice, "INV", client_id=client.id, job_id=job.id, kind="contract", period_start=start, period_end=end,
            issue_date=today, due_date=today + timedelta(days=client.payment_terms_days), status="issued", vat_pct=client.vat_pct,
            created_by_user_id=user_id, lines=lines, payments=[], **totals,
        )  # fmt: skip
        audit.record(db, actor_user_id=user_id, action="invoice.issued", entity_type="invoice", entity_id=invoice.id, after={"number": invoice.number, "total_cents": invoice.total_cents, "period": start.isoformat()})
        await queue_sale(db, invoice)
        made.append(invoice)
    return made


async def run_contract_invoices(month: date | None = None) -> int:
    """Runs across every business (the first of the month, for the month that just ended)."""
    month = month or (nairobi_today().replace(day=1) - timedelta(days=1))
    total = 0
    async with get_sessionmaker()() as db:
        business_ids = (await db.execute(select(Business.id))).scalars().all()
    for business_id in business_ids:
        async with get_sessionmaker()() as db:
            current_business_id.set(business_id)
            try:
                total += len(await contract_invoices(db, month))
                await db.commit()
            finally:
                current_business_id.set(None)
    log.info("Issued %s contract invoices for %s", total, month.strftime("%B %Y"))
    return total


async def contract_invoices_job(ctx: dict) -> int:
    return await run_contract_invoices()


async def render_invoice_pdf(db: AsyncSession, invoice: Invoice) -> bytes:
    """The invoice as a PDF for the current business: with its proof of delivery, how to pay, and the eTIMS receipt if KRA has one."""
    client = (await db.execute(select(Client).where(Client.id == invoice.client_id))).scalar_one()
    business = (await db.execute(select(Business).where(Business.id == current_business_id.get()))).scalar_one()
    cfg = await get_settings(db)
    pod = trip = None
    photos: dict = {}
    if invoice.trip_id:
        trip = (await db.execute(select(Trip).where(Trip.id == invoice.trip_id))).scalar_one_or_none()
        pod = (await db.execute(select(ProofOfDelivery).where(ProofOfDelivery.trip_id == invoice.trip_id))).scalar_one_or_none()
        if pod:
            ids = [i for i in [pod.cargo_photo_id, pod.note_photo_id, trip.weighbridge_photo_id if trip else None, *[uuid.UUID(d) for d in pod.damage_photo_ids]] if i]
            photos = {p.id: p for p in (await db.execute(select(Photo).where(Photo.id.in_(ids)))).scalars()}
    sale = (await db.execute(select(EtimsSubmission).where(EtimsSubmission.invoice_id == invoice.id, EtimsSubmission.kind == "sale"))).scalar_one_or_none()
    return invoice_pdf(invoice, client, business.name, pod=pod, photos=photos, trip=trip, pay_info=pay_instructions(cfg, invoice), etims=sale, tin=business.kra_pin, branch_id=cfg.etims_branch_id)


def pay_instructions(cfg, invoice: Invoice) -> str | None:
    """How the client pays by M-Pesa, with the invoice number as the account so the payment finds its invoice."""
    if not cfg.shortcode:
        return None
    if cfg.shortcode_type == "till":
        return f"Pay by M-Pesa: Buy Goods Till {cfg.shortcode}. Please send the invoice number {invoice.number} to us after paying."
    return f"Pay by M-Pesa: Paybill {cfg.shortcode}, account number {invoice.number}."
