"""Lease accounts (masterplan 5.23). Each month the lease's charge is worked out from the agreement and what the lorry actually
did, costs the operator paid on the owner's behalf become offsets, payments are recorded against the account, and a statement
says where it stands. A leased-in lorry's account is what we owe the lessor; a leased-out lorry's is what the lessee owes us."""

import uuid
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, mpesa
from app.floatcalc import day_bounds
from app.lease_config import has_variable_terms, item_for_category, matrix_of, terms_of
from app.lease_rules import Usage, lease_standing, month_bounds, month_charge
from app.models import (
    COUNTED,
    Expense,
    FuelEntry,
    LeaseAgreement,
    LeaseEntry,
    Party,
    Trip,
    TripStatus,
    Vehicle,
)
from app.profit import build
from app.reminders import nairobi_today


class LeaseError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


def entry_row(e: LeaseEntry) -> dict:
    return {
        "id": e.id, "kind": e.kind, "period_start": e.period_start, "entry_date": e.entry_date, "due_date": e.due_date, "amount_cents": e.amount_cents,
        "description": e.description, "basis": e.basis, "method": e.method, "mpesa_code": e.mpesa_code, "reference": e.reference, "source_kind": e.source_kind,
    }  # fmt: skip


async def entries_of(db: AsyncSession, agreement_id: uuid.UUID) -> list[LeaseEntry]:
    return list((await db.execute(select(LeaseEntry).where(LeaseEntry.agreement_id == agreement_id).order_by(LeaseEntry.entry_date, LeaseEntry.created_at))).scalars())


def standing_of(entries: list[LeaseEntry], today: date) -> dict:
    return lease_standing([{"kind": e.kind, "amount_cents": e.amount_cents, "due_date": e.due_date} for e in entries], today)


async def month_usage(db: AsyncSession, vehicle_id: uuid.UUID, month: date) -> Usage:
    """What the lorry did in the month: trips, kilometres, revenue and gross profit before the lease."""
    row = next(r for r in (await build(db, month, month))["vehicles"] if r["vehicle_id"] == vehicle_id)
    return Usage(trips=row["trips"], km=row["km"], revenue_cents=row["revenue"], profit_cents=row["gross"])


async def run_month(db: AsyncSession, a: LeaseAgreement, month: date, user_id: uuid.UUID | None, reported: dict | None = None) -> dict:
    """Works out (or works out again) the charge for a month, and books offsets for costs the operator paid that the lease makes
    the lessor's. The caller commits."""
    first, last = month_bounds(month)
    today = nairobi_today()
    if first > today:
        raise LeaseError("future_month", "That month has not started yet.")
    if last < a.start_date or (a.end_date is not None and first > a.end_date):
        raise LeaseError("outside_agreement", "The agreement was not running in that month.")
    if a.direction == "out" and has_variable_terms(a) and reported is None:
        raise LeaseError("report_needed", "This lease charges by trips, kilometres or a share, and those happen on the lessee's side. Enter what the lessee reported for the month.")
    usage = Usage(**reported) if reported is not None else await month_usage(db, a.vehicle_id, month)
    c = month_charge(terms_of(a), first, usage)
    basis = {
        **c, "usage": {"trips": usage.trips, "km": usage.km, "revenue_cents": usage.revenue_cents, "profit_cents": usage.profit_cents},
        "source": "reported" if reported is not None else "auto", "provisional": last >= today,
    }  # fmt: skip
    entry = (await db.execute(select(LeaseEntry).where(LeaseEntry.agreement_id == a.id, LeaseEntry.kind == "charge", LeaseEntry.period_start == first))).scalar_one_or_none()
    before = entry.amount_cents if entry is not None else None
    due = last + timedelta(days=a.payment_due_days)
    if entry is None:
        entry = LeaseEntry(agreement_id=a.id, kind="charge", period_start=first, entry_date=today, due_date=due, amount_cents=c["charge_cents"], description=f"Lease charge for {first.strftime('%B %Y')}", basis=basis, created_by_user_id=user_id)
        db.add(entry)
    else:
        entry.amount_cents, entry.basis, entry.due_date = c["charge_cents"], basis, due
    new_offsets = await book_offsets(db, a, first, user_id) if a.direction == "in" else []
    await db.flush()
    audit.record(
        db, actor_user_id=user_id, action="lease.charge_run", entity_type="lease_agreement", entity_id=a.id,
        before={"charge_cents": before} if before is not None else None, after={"month": first.isoformat(), "charge_cents": c["charge_cents"], "offsets": len(new_offsets), "source": basis["source"]},
    )  # fmt: skip
    return {"charge": entry, "offsets": new_offsets}


async def book_offsets(db: AsyncSession, a: LeaseAgreement, first: date, user_id: uuid.UUID | None) -> list[LeaseEntry]:
    """Costs the operator paid in the month that the agreement makes the lessor's become offsets against the charge, each backed
    by the expense (and its receipt). One offset per cost, however often this runs."""
    matrix = matrix_of(a)
    start, _ = day_bounds(max(first, a.start_date))
    _, end = day_bounds(min(month_bounds(first)[1], a.end_date) if a.end_date else month_bounds(first)[1])
    done = {sid for (sid,) in (await db.execute(select(LeaseEntry.source_id).where(LeaseEntry.kind == "offset", LeaseEntry.source_id.is_not(None)))).all()}
    made: list[LeaseEntry] = []
    today = nairobi_today()
    for ex in (await db.execute(select(Expense).where(Expense.vehicle_id == a.vehicle_id, Expense.status.in_(COUNTED), Expense.spent_at >= start, Expense.spent_at < end))).scalars():
        item = item_for_category(ex.category)
        if item and matrix.get(item) == "lessor" and ex.id not in done:
            what = ex.category.value.replace("_", " ").capitalize() + (f": {ex.note}" if ex.note else "")
            made.append(LeaseEntry(agreement_id=a.id, kind="offset", period_start=first, entry_date=today, amount_cents=-ex.amount_cents, description=f"Paid on the lessor's behalf. {what}"[:255], source_kind="expense", source_id=ex.id, reference="receipt attached" if ex.receipt_photo_id else None, created_by_user_id=user_id))  # fmt: skip
    if matrix.get("fuel") == "lessor":
        for fu in (await db.execute(select(FuelEntry).where(FuelEntry.vehicle_id == a.vehicle_id, FuelEntry.captured_at >= start, FuelEntry.captured_at < end))).scalars():
            if fu.id not in done:
                made.append(LeaseEntry(agreement_id=a.id, kind="offset", period_start=first, entry_date=today, amount_cents=-fu.amount_cents, description=f"Paid on the lessor's behalf. Fuel {fu.station or ''}".strip()[:255], source_kind="fuel", source_id=fu.id, created_by_user_id=user_id))  # fmt: skip
    db.add_all(made)
    for e in made:
        audit.record(db, actor_user_id=user_id, action="lease.offset_booked", entity_type="lease_agreement", entity_id=a.id, after={"amount_cents": e.amount_cents, "source_kind": e.source_kind, "source_id": str(e.source_id)})
    return made


async def add_payment(db: AsyncSession, a: LeaseAgreement, *, amount_cents: int, method: str, reference: str | None, mpesa_code: str | None, received_on: date, user_id: uuid.UUID) -> LeaseEntry:
    """Money paid to the lessor (or, for a leased-out lorry, received from the lessee)."""
    try:
        code = mpesa.tidy(mpesa_code)
    except ValueError as e:
        raise LeaseError("invalid_mpesa_code", str(e)) from None
    if code and await mpesa.taken(db, code):
        raise LeaseError("duplicate_mpesa_code", "That M-Pesa code was already recorded.")
    verb = "Paid to" if a.direction == "in" else "Received from"
    party = (await db.execute(select(Party).where(Party.id == a.party_id))).scalar_one()
    entry = LeaseEntry(
        agreement_id=a.id, kind="payment", entry_date=received_on, amount_cents=-amount_cents, description=f"{verb} {party.name}", method=method, mpesa_code=code,
        reference=(reference or "").strip() or None, created_by_user_id=user_id,
    )  # fmt: skip
    db.add(entry)
    await db.flush()
    audit.record(db, actor_user_id=user_id, action="lease.payment", entity_type="lease_agreement", entity_id=a.id, after={"amount_cents": amount_cents, "method": method, "mpesa_code": code})
    return entry


async def statement(db: AsyncSession, a: LeaseAgreement, month: date, *, lessor_view: bool = False) -> dict:
    """The month's statement: what was charged and how, what was offset, what was paid, and the balance. The lessor's own view
    shows trips only if the agreement allows it, and the usage behind a charge only for the parts the charge depends on."""
    first, last = month_bounds(month)
    entries = await entries_of(db, a.id)
    vehicle = (await db.execute(select(Vehicle).where(Vehicle.id == a.vehicle_id))).scalar_one()
    party = (await db.execute(select(Party).where(Party.id == a.party_id))).scalar_one()

    def belongs_before(e: LeaseEntry) -> bool:
        return (e.period_start < first) if e.period_start is not None else e.entry_date < first

    def in_month(e: LeaseEntry) -> bool:
        return (e.period_start == first) if e.period_start is not None else first <= e.entry_date <= last

    opening = sum(e.amount_cents for e in entries if belongs_before(e))
    lines = [entry_row(e) for e in entries if in_month(e)]
    for ln in lines:
        if lessor_view and ln["basis"] is not None:
            ln["basis"] = {k: v for k, v in ln["basis"].items() if k not in ("source", "provisional")}
    closing = opening + sum(ln["amount_cents"] for ln in lines)
    charge = next((e for e in entries if e.kind == "charge" and e.period_start == first), None)
    usage = (charge.basis or {}).get("usage", {}) if charge else {}
    shown_usage = {}
    if usage:
        if a.per_trip_cents:
            shown_usage["trips"] = usage.get("trips")
        if a.per_km_cents:
            shown_usage["km"] = usage.get("km")
        if float(a.revenue_pct):
            shown_usage["revenue_cents"] = usage.get("revenue_cents")
        if float(a.profit_pct):
            shown_usage["profit_cents"] = usage.get("profit_cents")
    trips = []
    if not lessor_view or a.share_trips:
        start, _ = day_bounds(first)
        _, end = day_bounds(last)
        trips = [
            {"delivered_at": t.delivered_at or t.ended_at, "route": f"{t.origin or ''} to {t.destination or ''}".strip(" to"), "distance_km": t.distance_km or 0}
            for t in (await db.execute(select(Trip).where(Trip.vehicle_id == a.vehicle_id, Trip.status.in_((TripStatus.DELIVERED, TripStatus.COMPLETED))))).scalars()
            if (t.delivered_at or t.ended_at) and start <= (t.delivered_at or t.ended_at) < end
        ]  # fmt: skip
    standing = standing_of(entries, nairobi_today())
    return {
        "agreement_id": a.id, "direction": a.direction, "vehicle": vehicle.registration, "party": party.name, "month": first, "deposit_cents": a.deposit_cents,
        "opening_balance_cents": opening, "lines": lines, "closing_balance_cents": closing, "usage": shown_usage, "trips": trips, "trip_count": len(trips) if trips else None,
        "balance_cents": standing["balance_cents"], "overdue_cents": standing["overdue_cents"], "next_due_date": standing["next_due_date"],
        "payable_cents": sum(ln["amount_cents"] for ln in lines if ln["kind"] in ("charge", "offset")),
    }  # fmt: skip
