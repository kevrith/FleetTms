"""Asset finance and fixed ownership costs (masterplan 5.23): loans on lorries with their repayment schedules, and insurance,
licences and depreciation spread across months."""

import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, mpesa
from app.db import get_db
from app.deps import Principal, error, require_any
from app.lease_rules import finance_schedule, instalment_cents, ownership_monthly
from app.models import (
    FinanceAgreement,
    FinanceInstalment,
    OwnershipCost,
    OwnershipType,
    Party,
    PartyKind,
    Vehicle,
)
from app.reminders import nairobi_today

router = APIRouter(tags=["finance"])
VIEW = ("finance.view",)
MANAGE = ("leases.manage",)


class FinanceIn(BaseModel):
    vehicle_id: uuid.UUID
    party_id: uuid.UUID
    principal_cents: int = Field(gt=0, le=100_000_000_000)
    annual_rate_pct: float = Field(default=0, ge=0, le=100)
    months: int = Field(ge=1, le=120)
    first_due: date
    instalment_cents: int | None = Field(default=None, gt=0, le=100_000_000_000)  # leave out to work it out from the rate
    reference: str | None = Field(default=None, max_length=60)
    notes: str | None = Field(default=None, max_length=1000)


class RepayIn(BaseModel):
    amount_cents: int | None = Field(default=None, gt=0, le=100_000_000_000)  # leave out to pay what is left on the instalment
    method: Literal["mpesa", "bank", "cash", "cheque"]
    mpesa_code: str | None = None
    reference: str | None = Field(default=None, max_length=60)
    paid_on: date | None = None


class OwnershipIn(BaseModel):
    vehicle_id: uuid.UUID
    kind: Literal["insurance", "licence", "depreciation", "other"]
    name: str = Field(min_length=2, max_length=120)
    amount_cents: int = Field(gt=0, le=100_000_000_000)  # per year or per month; for depreciation, what the lorry cost
    period: Literal["year", "month"] = "year"
    salvage_cents: int = Field(default=0, ge=0, le=100_000_000_000)
    life_months: int | None = Field(default=None, ge=1, le=600)
    start_date: date
    end_date: date | None = None
    notes: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _ok(self):
        if self.kind == "depreciation":
            if not self.life_months:
                raise ValueError("Depreciation needs the number of months the lorry is expected to last.")
            if self.salvage_cents >= self.amount_cents:
                raise ValueError("What the lorry will be worth at the end must be less than what it cost.")
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("The cost cannot end before it starts.")
        return self


def finance_out(f: FinanceAgreement, vehicle: Vehicle | None = None, party: Party | None = None, *, schedule: bool = False) -> dict:
    today = nairobi_today()
    paid_principal = sum(i.principal_cents for i in f.instalments if i.paid_cents >= i.amount_cents)
    owing = lambda i: max(0, i.amount_cents - i.paid_cents)
    due = [i for i in f.instalments if owing(i) > 0]
    out = {
        "id": f.id, "vehicle_id": f.vehicle_id, "registration": vehicle.registration if vehicle else None, "party_id": f.party_id, "party_name": party.name if party else None,
        "principal_cents": f.principal_cents, "annual_rate_pct": float(f.annual_rate_pct), "months": f.months, "first_due": f.first_due, "instalment_cents": f.instalment_cents,
        "reference": f.reference, "status": f.status, "notes": f.notes, "principal_balance_cents": f.principal_cents - paid_principal,
        "outstanding_cents": sum(owing(i) for i in f.instalments), "overdue_cents": sum(owing(i) for i in due if i.due_date < today),
        "next_due_date": min((i.due_date for i in due), default=None), "total_interest_cents": sum(i.interest_cents for i in f.instalments),
    }  # fmt: skip
    if schedule:
        out["schedule"] = [
            {"number": i.number, "due_date": i.due_date, "amount_cents": i.amount_cents, "interest_cents": i.interest_cents, "principal_cents": i.principal_cents, "paid_cents": i.paid_cents, "paid_on": i.paid_on, "method": i.method, "mpesa_code": i.mpesa_code, "reference": i.reference, "overdue": owing(i) > 0 and i.due_date < today}
            for i in f.instalments
        ]  # fmt: skip
    return out


async def _loan(db: AsyncSession, loan_id: uuid.UUID) -> FinanceAgreement:
    f = (await db.execute(select(FinanceAgreement).where(FinanceAgreement.id == loan_id))).scalar_one_or_none()
    if f is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That loan was not found.")
    return f


@router.get("/finance")
async def list_loans(principal: Principal = Depends(require_any(*VIEW)), db: AsyncSession = Depends(get_db)):
    vehicles = {v.id: v for v in (await db.execute(select(Vehicle))).scalars()}
    parties = {p.id: p for p in (await db.execute(select(Party))).scalars()}
    return [finance_out(f, vehicles.get(f.vehicle_id), parties.get(f.party_id)) for f in (await db.execute(select(FinanceAgreement).order_by(FinanceAgreement.created_at.desc()))).scalars()]


@router.post("/finance", status_code=status.HTTP_201_CREATED)
async def create_loan(body: FinanceIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    vehicle = (await db.execute(select(Vehicle).where(Vehicle.id == body.vehicle_id))).scalar_one_or_none()
    party = (await db.execute(select(Party).where(Party.id == body.party_id))).scalar_one_or_none()
    if vehicle is None or party is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That vehicle or lender was not found.")
    if vehicle.ownership_type != OwnershipType.ASSET_FINANCED or party.kind != PartyKind.LENDER or vehicle.party_id != party.id:
        raise error(422, "wrong_ownership", "Set the vehicle as asset-financed with this lender first.")
    payment = body.instalment_cents or instalment_cents(body.principal_cents, body.annual_rate_pct, body.months)
    rows = finance_schedule(body.principal_cents, body.annual_rate_pct, body.months, body.first_due, payment)
    f = FinanceAgreement(**body.model_dump(exclude={"instalment_cents"}), instalment_cents=payment, created_by_user_id=principal.user.id)
    f.instalments = [FinanceInstalment(**{k: v for k, v in r.items() if k != "balance_cents"}) for r in rows]
    db.add(f)
    await db.flush()
    audit.record(db, actor_user_id=principal.user.id, action="finance.created", entity_type="finance_agreement", entity_id=f.id, after={"principal_cents": f.principal_cents, "months": f.months, "instalment_cents": payment})
    await db.commit()
    return finance_out(f, vehicle, party, schedule=True)


@router.get("/finance/{loan_id}")
async def read_loan(loan_id: uuid.UUID, principal: Principal = Depends(require_any(*VIEW)), db: AsyncSession = Depends(get_db)):
    f = await _loan(db, loan_id)
    vehicle = (await db.execute(select(Vehicle).where(Vehicle.id == f.vehicle_id))).scalar_one()
    party = (await db.execute(select(Party).where(Party.id == f.party_id))).scalar_one()
    return finance_out(f, vehicle, party, schedule=True)


@router.post("/finance/{loan_id}/instalments/{number}/pay")
async def repay(loan_id: uuid.UUID, number: int, body: RepayIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    """Ticks a repayment off the schedule, in full or in part."""
    f = await _loan(db, loan_id)
    inst = next((i for i in f.instalments if i.number == number), None)
    if inst is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That instalment was not found.")
    left = inst.amount_cents - inst.paid_cents
    amount = body.amount_cents or left
    if left <= 0:
        raise error(status.HTTP_409_CONFLICT, "paid", "That instalment is already paid.")
    if amount > left:
        raise error(422, "overpayment", f"Only KES {left / 100:,.2f} is left on that instalment.")
    try:
        code = mpesa.tidy(body.mpesa_code)
    except ValueError as e:
        raise error(422, "invalid_mpesa_code", str(e)) from None
    if code and (inst.mpesa_code or await mpesa.taken(db, code)):
        raise error(status.HTTP_409_CONFLICT, "duplicate_mpesa_code", "That M-Pesa code was already recorded, or this instalment already has one.")
    inst.paid_cents += amount
    inst.paid_on = body.paid_on or nairobi_today()
    inst.method, inst.mpesa_code, inst.reference = body.method, code or inst.mpesa_code, (body.reference or "").strip() or inst.reference
    if all(i.paid_cents >= i.amount_cents for i in f.instalments):
        f.status = "closed"
    audit.record(db, actor_user_id=principal.user.id, action="finance.repayment", entity_type="finance_agreement", entity_id=f.id, after={"number": number, "amount_cents": amount, "method": body.method, "mpesa_code": code})
    await db.commit()
    vehicle = (await db.execute(select(Vehicle).where(Vehicle.id == f.vehicle_id))).scalar_one()
    return finance_out(f, vehicle, None, schedule=True)


# ---- ownership costs --------------------------------------------------------------------------------------------


def ownership_out(o: OwnershipCost, registration: str | None = None) -> dict:
    today = nairobi_today()
    return {
        "id": o.id, "vehicle_id": o.vehicle_id, "registration": registration, "kind": o.kind, "name": o.name, "amount_cents": o.amount_cents, "period": o.period,
        "salvage_cents": o.salvage_cents, "life_months": o.life_months, "start_date": o.start_date, "end_date": o.end_date, "notes": o.notes,
        "monthly_cents": ownership_monthly(kind=o.kind, amount_cents=o.amount_cents, period=o.period, salvage_cents=o.salvage_cents, life_months=o.life_months, start=o.start_date, end=o.end_date, month=today),
    }  # fmt: skip


async def _vehicle(db: AsyncSession, vehicle_id: uuid.UUID) -> Vehicle:
    v = (await db.execute(select(Vehicle).where(Vehicle.id == vehicle_id))).scalar_one_or_none()
    if v is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That vehicle was not found.")
    return v


@router.get("/ownership-costs")
async def list_ownership(vehicle_id: uuid.UUID | None = None, principal: Principal = Depends(require_any(*VIEW)), db: AsyncSession = Depends(get_db)):
    names = {v.id: v.registration for v in (await db.execute(select(Vehicle))).scalars()}
    query = select(OwnershipCost).order_by(OwnershipCost.start_date.desc())
    if vehicle_id:
        query = query.where(OwnershipCost.vehicle_id == vehicle_id)
    return [ownership_out(o, names.get(o.vehicle_id)) for o in (await db.execute(query)).scalars()]


@router.post("/ownership-costs", status_code=status.HTTP_201_CREATED)
async def add_ownership(body: OwnershipIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    vehicle = await _vehicle(db, body.vehicle_id)
    o = OwnershipCost(**body.model_dump())
    db.add(o)
    await db.flush()
    audit.record(db, actor_user_id=principal.user.id, action="ownership_cost.added", entity_type="ownership_cost", entity_id=o.id, after={"kind": o.kind, "amount_cents": o.amount_cents, "vehicle": vehicle.registration})
    await db.commit()
    return ownership_out(o, vehicle.registration)


@router.put("/ownership-costs/{cost_id}")
async def update_ownership(cost_id: uuid.UUID, body: OwnershipIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    o = (await db.execute(select(OwnershipCost).where(OwnershipCost.id == cost_id))).scalar_one_or_none()
    if o is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That cost was not found.")
    vehicle = await _vehicle(db, body.vehicle_id)
    before = {"kind": o.kind, "amount_cents": o.amount_cents, "start_date": o.start_date.isoformat()}
    for k, v in body.model_dump().items():
        setattr(o, k, v)
    audit.record(db, actor_user_id=principal.user.id, action="ownership_cost.updated", entity_type="ownership_cost", entity_id=o.id, before=before, after={"kind": o.kind, "amount_cents": o.amount_cents, "start_date": o.start_date.isoformat()})
    await db.commit()
    return ownership_out(o, vehicle.registration)


@router.delete("/ownership-costs/{cost_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ownership(cost_id: uuid.UUID, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    o = (await db.execute(select(OwnershipCost).where(OwnershipCost.id == cost_id))).scalar_one_or_none()
    if o is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That cost was not found.")
    audit.record(db, actor_user_id=principal.user.id, action="ownership_cost.deleted", entity_type="ownership_cost", entity_id=o.id, before={"kind": o.kind, "amount_cents": o.amount_cents})
    await db.delete(o)
    await db.commit()
