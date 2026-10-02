"""Lease agreements, ledgers, payments and statements (masterplan 5.23)."""

import io
import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, leases
from app.db import get_db
from app.deps import Principal, error, require_any
from app.lease_config import DEFAULT_RESPONSIBILITIES, RESPONSIBILITY_ITEMS, matrix_of, terms_of
from app.lease_files import statement_pdf
from app.lease_rules import month_bounds, month_charge
from app.models import Business, LeaseAgreement, OwnershipType, Party, PartyKind, Vehicle
from app.reminders import nairobi_today
from app.report_delivery import DeliveryError, get_report_sender

router = APIRouter(tags=["leases"])
VIEW = ("finance.view",)
MANAGE = ("leases.manage",)
FIELDS = [
    "direction", "vehicle_id", "party_id", "status", "start_date", "end_date", "notice_days", "deposit_cents", "fixed_cents", "fixed_period", "per_trip_cents", "per_km_cents",
    "revenue_pct", "profit_pct", "min_guarantee_cents", "responsibilities", "payment_due_days", "share_trips", "share_location",
]  # fmt: skip


class LeaseIn(BaseModel):
    direction: Literal["in", "out"]
    vehicle_id: uuid.UUID
    party_id: uuid.UUID
    start_date: date
    end_date: date | None = None
    notice_days: int = Field(default=30, ge=0, le=365)
    deposit_cents: int = Field(default=0, ge=0, le=10_000_000_000)
    fixed_cents: int = Field(default=0, ge=0, le=10_000_000_000)
    fixed_period: Literal["month", "week", "day"] | None = None
    per_trip_cents: int = Field(default=0, ge=0, le=10_000_000_000)
    per_km_cents: int = Field(default=0, ge=0, le=10_000_000_000)
    revenue_pct: float = Field(default=0, ge=0, le=100)
    profit_pct: float = Field(default=0, ge=0, le=100)
    min_guarantee_cents: int = Field(default=0, ge=0, le=10_000_000_000)
    responsibilities: dict[str, Literal["lessee", "lessor"]] = Field(default_factory=dict)
    payment_due_days: int = Field(default=7, ge=0, le=60)
    share_trips: bool = False
    share_location: bool = False
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _terms(self):
        if bool(self.fixed_cents) != bool(self.fixed_period):
            raise ValueError("A fixed amount needs its period (month, week or day), and a period needs an amount.")
        if not (self.fixed_cents or self.per_trip_cents or self.per_km_cents or self.revenue_pct or self.profit_pct or self.min_guarantee_cents):
            raise ValueError("Say what the lease charges: a fixed amount, a rate per trip or kilometre, a share, or a minimum.")
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("The agreement cannot end before it starts.")
        unknown = set(self.responsibilities) - set(RESPONSIBILITY_ITEMS)
        if unknown:
            raise ValueError(f"Unknown cost items: {', '.join(sorted(unknown))}.")
        return self


class ReportedUsage(BaseModel):
    trips: int = Field(default=0, ge=0, le=100_000)
    km: int = Field(default=0, ge=0, le=10_000_000)
    revenue_cents: int = Field(default=0, ge=0, le=100_000_000_000)
    profit_cents: int = Field(default=0, ge=-100_000_000_000, le=100_000_000_000)


class RunIn(BaseModel):
    month: date
    reported: ReportedUsage | None = None


class PaymentIn(BaseModel):
    amount_cents: int = Field(gt=0, le=10_000_000_000)
    method: Literal["mpesa", "bank", "cash", "cheque"]
    mpesa_code: str | None = None
    reference: str | None = Field(default=None, max_length=60)
    received_on: date | None = None


class AdjustIn(BaseModel):
    amount_cents: int = Field(le=10_000_000_000, ge=-10_000_000_000)
    reason: str = Field(min_length=3, max_length=255)
    entry_date: date | None = None


class EndIn(BaseModel):
    end_date: date | None = None


class SendIn(BaseModel):
    month: date
    channel: Literal["email", "whatsapp"]
    recipient: str | None = Field(default=None, max_length=255)


def agreement_out(a: LeaseAgreement, vehicle: Vehicle | None = None, party: Party | None = None) -> dict:
    return {
        "id": a.id, "direction": a.direction, "vehicle_id": a.vehicle_id, "registration": vehicle.registration if vehicle else None, "party_id": a.party_id,
        "party_name": party.name if party else None, "status": a.status, "start_date": a.start_date, "end_date": a.end_date, "notice_days": a.notice_days,
        "deposit_cents": a.deposit_cents, "fixed_cents": a.fixed_cents, "fixed_period": a.fixed_period, "per_trip_cents": a.per_trip_cents, "per_km_cents": a.per_km_cents,
        "revenue_pct": float(a.revenue_pct), "profit_pct": float(a.profit_pct), "min_guarantee_cents": a.min_guarantee_cents, "responsibilities": matrix_of(a),
        "payment_due_days": a.payment_due_days, "share_trips": a.share_trips, "share_location": a.share_location, "notes": a.notes,
    }  # fmt: skip


async def _get(db: AsyncSession, agreement_id: uuid.UUID) -> LeaseAgreement:
    a = (await db.execute(select(LeaseAgreement).where(LeaseAgreement.id == agreement_id))).scalar_one_or_none()
    if a is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That lease was not found.")
    return a


async def _check(db: AsyncSession, body: LeaseIn, current: uuid.UUID | None = None) -> tuple[Vehicle, Party]:
    vehicle = (await db.execute(select(Vehicle).where(Vehicle.id == body.vehicle_id))).scalar_one_or_none()
    party = (await db.execute(select(Party).where(Party.id == body.party_id))).scalar_one_or_none()
    if vehicle is None or party is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That vehicle or lessor was not found.")
    needed_type, needed_kind = (OwnershipType.LEASED_IN, PartyKind.LESSOR) if body.direction == "in" else (OwnershipType.LEASED_OUT, PartyKind.LESSEE)
    if vehicle.ownership_type != needed_type:
        raise error(422, "wrong_ownership", f"Set this vehicle's ownership to {needed_type.value.replace('_', '-')} first.")
    if party.kind != needed_kind or vehicle.party_id != party.id:
        raise error(422, "wrong_party", f"The {needed_kind.value} must be the one set on the vehicle.")
    running = (await db.execute(select(LeaseAgreement).where(LeaseAgreement.vehicle_id == vehicle.id, LeaseAgreement.status == "active"))).scalar_one_or_none()
    if running is not None and running.id != current:
        raise error(status.HTTP_409_CONFLICT, "lease_exists", "This vehicle already has a running lease. End it first.")
    return vehicle, party


@router.get("/leases/responsibility-items")
async def responsibility_items(principal: Principal = Depends(require_any(*VIEW))):
    return {"items": RESPONSIBILITY_ITEMS, "defaults": DEFAULT_RESPONSIBILITIES}


@router.get("/leases")
async def list_leases(principal: Principal = Depends(require_any(*VIEW)), db: AsyncSession = Depends(get_db)):
    vehicles = {v.id: v for v in (await db.execute(select(Vehicle))).scalars()}
    parties = {p.id: p for p in (await db.execute(select(Party))).scalars()}
    out = []
    for a in (await db.execute(select(LeaseAgreement).order_by(LeaseAgreement.status, LeaseAgreement.start_date.desc()))).scalars():
        standing = leases.standing_of(await leases.entries_of(db, a.id), nairobi_today())
        out.append({**agreement_out(a, vehicles.get(a.vehicle_id), parties.get(a.party_id)), **standing})
    return out


@router.post("/leases", status_code=status.HTTP_201_CREATED)
async def create_lease(body: LeaseIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    vehicle, party = await _check(db, body)
    a = LeaseAgreement(**body.model_dump(), created_by_user_id=principal.user.id)
    db.add(a)
    await db.flush()
    audit.record(db, actor_user_id=principal.user.id, action="lease.created", entity_type="lease_agreement", entity_id=a.id, after=audit.snapshot(a, FIELDS))
    await db.commit()
    return agreement_out(a, vehicle, party)


@router.get("/leases/{lease_id}")
async def read_lease(lease_id: uuid.UUID, principal: Principal = Depends(require_any(*VIEW)), db: AsyncSession = Depends(get_db)):
    a = await _get(db, lease_id)
    vehicle = (await db.execute(select(Vehicle).where(Vehicle.id == a.vehicle_id))).scalar_one()
    party = (await db.execute(select(Party).where(Party.id == a.party_id))).scalar_one()
    entries = await leases.entries_of(db, a.id)
    today = nairobi_today()
    standing = leases.standing_of(entries, today)
    this_month = None
    if a.status == "active" and not (a.direction == "out" and (a.per_trip_cents or a.per_km_cents or a.revenue_pct or a.profit_pct)):
        usage = await leases.month_usage(db, a.vehicle_id, today)
        this_month = {"month": today.replace(day=1), **month_charge(terms_of(a), today, usage)}
    return {**agreement_out(a, vehicle, party), **standing, "entries": [leases.entry_row(e) for e in reversed(entries)], "this_month": this_month}


@router.put("/leases/{lease_id}")
async def update_lease(lease_id: uuid.UUID, body: LeaseIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    """Changes the terms. Charges already worked out stay as they are until that month is run again."""
    a = await _get(db, lease_id)
    if a.status != "active":
        raise error(status.HTTP_409_CONFLICT, "ended", "That lease has ended.")
    if body.vehicle_id != a.vehicle_id or body.direction != a.direction:
        raise error(422, "cannot_move", "A lease cannot be moved to another vehicle or turned around. End it and make a new one.")
    vehicle, party = await _check(db, body, current=a.id)
    before = audit.snapshot(a, FIELDS)
    for k, v in body.model_dump().items():
        setattr(a, k, v)
    audit.record(db, actor_user_id=principal.user.id, action="lease.updated", entity_type="lease_agreement", entity_id=a.id, before=before, after=audit.snapshot(a, FIELDS))
    await db.commit()
    return agreement_out(a, vehicle, party)


@router.post("/leases/{lease_id}/end")
async def end_lease(lease_id: uuid.UUID, body: EndIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    a = await _get(db, lease_id)
    end = body.end_date or nairobi_today()
    if a.status != "active":
        raise error(status.HTTP_409_CONFLICT, "ended", "That lease has already ended.")
    if end < a.start_date:
        raise error(422, "bad_end", "The lease cannot end before it starts.")
    a.status, a.end_date = "ended", end
    audit.record(db, actor_user_id=principal.user.id, action="lease.ended", entity_type="lease_agreement", entity_id=a.id, after={"end_date": end.isoformat()})
    await db.commit()
    return agreement_out(a)


@router.post("/leases/run-month")
async def run_all(body: RunIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    """Works out the month's charge for every lease that was running in it. Safe to run again."""
    first, last = month_bounds(body.month)
    done, waiting = 0, []
    for a in (await db.execute(select(LeaseAgreement))).scalars().all():
        if a.start_date > last or (a.end_date is not None and a.end_date < first):
            continue
        try:
            await leases.run_month(db, a, first, principal.user.id)
            done += 1
        except leases.LeaseError as e:
            if e.code == "report_needed":
                waiting.append(str(a.id))
            else:
                raise error(422, e.code, e.message) from None
    await db.commit()
    return {"month": first, "done": done, "waiting_for_lessee_figures": waiting}


@router.post("/leases/{lease_id}/run")
async def run_one(lease_id: uuid.UUID, body: RunIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    a = await _get(db, lease_id)
    try:
        result = await leases.run_month(db, a, body.month, principal.user.id, body.reported.model_dump() if body.reported else None)
    except leases.LeaseError as e:
        raise error(422, e.code, e.message) from None
    await db.commit()
    return {"charge": leases.entry_row(result["charge"]), "offsets": [leases.entry_row(e) for e in result["offsets"]]}


@router.post("/leases/{lease_id}/payments", status_code=status.HTTP_201_CREATED)
async def add_payment(lease_id: uuid.UUID, body: PaymentIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    a = await _get(db, lease_id)
    try:
        entry = await leases.add_payment(
            db, a, amount_cents=body.amount_cents, method=body.method, reference=body.reference, mpesa_code=body.mpesa_code, received_on=body.received_on or nairobi_today(), user_id=principal.user.id,
        )  # fmt: skip
    except leases.LeaseError as e:
        raise error(status.HTTP_409_CONFLICT if e.code.startswith("duplicate") else 422, e.code, e.message) from None
    await db.commit()
    return leases.entry_row(entry)


@router.post("/leases/{lease_id}/adjustments", status_code=status.HTTP_201_CREATED)
async def add_adjustment(lease_id: uuid.UUID, body: AdjustIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    """A correction to the account, up or down, with the reason: for example a damage claim or a disputed charge."""
    a = await _get(db, lease_id)
    if body.amount_cents == 0:
        raise error(422, "zero", "An adjustment cannot be nothing.")
    when = body.entry_date or nairobi_today()
    entry = leases.LeaseEntry(agreement_id=a.id, kind="adjustment", entry_date=when, due_date=when, amount_cents=body.amount_cents, description=body.reason, created_by_user_id=principal.user.id)
    db.add(entry)
    await db.flush()
    audit.record(db, actor_user_id=principal.user.id, action="lease.adjustment", entity_type="lease_agreement", entity_id=a.id, after={"amount_cents": body.amount_cents}, note=body.reason)
    await db.commit()
    return leases.entry_row(entry)


@router.get("/leases/{lease_id}/statement")
async def read_statement(lease_id: uuid.UUID, month: date, principal: Principal = Depends(require_any(*VIEW)), db: AsyncSession = Depends(get_db)):
    return await leases.statement(db, await _get(db, lease_id), month)


async def _pdf(db: AsyncSession, a: LeaseAgreement, month: date, business_id: uuid.UUID, *, lessor_view: bool = False) -> bytes:
    business = (await db.execute(select(Business).where(Business.id == business_id))).scalar_one()
    return statement_pdf(await leases.statement(db, a, month, lessor_view=lessor_view), business.name)


@router.get("/leases/{lease_id}/statement.pdf")
async def statement_file(lease_id: uuid.UUID, month: date, principal: Principal = Depends(require_any(*VIEW)), db: AsyncSession = Depends(get_db)):
    a = await _get(db, lease_id)
    pdf = await _pdf(db, a, month, principal.business_id)
    return StreamingResponse(io.BytesIO(pdf), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="lease-{month:%Y-%m}.pdf"'})


@router.post("/leases/{lease_id}/statement/send")
async def send_statement(lease_id: uuid.UUID, body: SendIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    """Sends the month's statement to the lessor (or lessee) as a PDF by email or WhatsApp."""
    a = await _get(db, lease_id)
    party = (await db.execute(select(Party).where(Party.id == a.party_id))).scalar_one()
    recipient = (body.recipient or (party.email if body.channel == "email" else party.phone) or "").strip()
    if not recipient:
        raise error(422, "no_recipient", f"{party.name} has no {'email address' if body.channel == 'email' else 'phone number'} on file. Enter one.")
    first, _ = month_bounds(body.month)
    pdf = await _pdf(db, a, first, principal.business_id, lessor_view=True)
    try:
        await get_report_sender(body.channel).send(recipient, f"Lease statement for {first:%B %Y}", f"lease-{first:%Y-%m}.pdf", pdf)
    except DeliveryError as e:
        raise error(502, "delivery_failed", str(e)) from None
    audit.record(db, actor_user_id=principal.user.id, action="lease.statement_sent", entity_type="lease_agreement", entity_id=a.id, after={"month": first.isoformat(), "channel": body.channel})
    await db.commit()
    return {"sent": True, "to": recipient}
