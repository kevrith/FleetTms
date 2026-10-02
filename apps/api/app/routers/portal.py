"""The Lessor portal (masterplan Section 3): a free, view-only window for a lorry's owner onto their own leases. A lessor sees the
statement, what was charged, paid and owed, and the lorry's service and inspection history, and trips only if the agreement
allows it. They have no other access to the business."""

import io
import uuid
from datetime import date

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import leases
from app.db import get_db
from app.deps import Principal, error, require
from app.lease_config import matrix_of
from app.models import Business, Inspection, LeaseAgreement, Membership, ServiceRecord, Vehicle
from app.reminders import nairobi_today
from app.routers.leases import _pdf, agreement_out

router = APIRouter(prefix="/portal", tags=["portal"])
OWN = "lease.view_own"


async def _mine(db: AsyncSession, principal: Principal) -> list[LeaseAgreement]:
    m = (await db.execute(select(Membership).where(Membership.id == principal.membership_id))).scalar_one()
    if m.party_id is None:
        return []
    return list((await db.execute(select(LeaseAgreement).where(LeaseAgreement.party_id == m.party_id, LeaseAgreement.direction == "in").order_by(LeaseAgreement.start_date.desc()))).scalars())


async def _one(db: AsyncSession, principal: Principal, lease_id: uuid.UUID) -> LeaseAgreement:
    found = next((a for a in await _mine(db, principal) if a.id == lease_id), None)
    if found is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That lease was not found.")  # not "forbidden": other lessors' leases do not exist for them
    return found


def lessor_view(a: LeaseAgreement, vehicle: Vehicle) -> dict:
    """The lease as the lessor sees it: the terms they agreed, never the operator's other business."""
    base = agreement_out(a, vehicle)
    return {k: base[k] for k in ("id", "registration", "status", "start_date", "end_date", "notice_days", "deposit_cents", "fixed_cents", "fixed_period", "per_trip_cents", "per_km_cents", "revenue_pct", "profit_pct", "min_guarantee_cents", "payment_due_days", "share_trips", "share_location")} | {"responsibilities": matrix_of(a)}  # fmt: skip


@router.get("/leases")
async def my_leases(principal: Principal = Depends(require(OWN)), db: AsyncSession = Depends(get_db)):
    business = (await db.execute(select(Business).where(Business.id == principal.business_id))).scalar_one()
    vehicles = {v.id: v for v in (await db.execute(select(Vehicle))).scalars()}
    out = []
    for a in await _mine(db, principal):
        standing = leases.standing_of(await leases.entries_of(db, a.id), nairobi_today())
        out.append({**lessor_view(a, vehicles[a.vehicle_id]), "operator": business.name, **standing})
    return out


@router.get("/leases/{lease_id}")
async def my_lease(lease_id: uuid.UUID, principal: Principal = Depends(require(OWN)), db: AsyncSession = Depends(get_db)):
    a = await _one(db, principal, lease_id)
    vehicle = (await db.execute(select(Vehicle).where(Vehicle.id == a.vehicle_id))).scalar_one()
    entries = await leases.entries_of(db, a.id)
    history = [{"done_on": r.done_on, "odometer_km": r.odometer_km, "notes": r.notes} for r in (await db.execute(select(ServiceRecord).where(ServiceRecord.vehicle_id == a.vehicle_id).order_by(ServiceRecord.done_on.desc()).limit(20))).scalars()]
    inspections = [{"date": i.local_date, "status": i.status.value} for i in (await db.execute(select(Inspection).where(Inspection.vehicle_id == a.vehicle_id).order_by(Inspection.local_date.desc()).limit(20))).scalars()]
    rows = [leases.entry_row(e) | {"basis": None} for e in reversed(entries)]  # the workings are on the monthly statement
    return {**lessor_view(a, vehicle), **leases.standing_of(entries, nairobi_today()), "entries": rows, "service_history": history, "inspections": inspections}


@router.get("/leases/{lease_id}/statement")
async def my_statement(lease_id: uuid.UUID, month: date, principal: Principal = Depends(require(OWN)), db: AsyncSession = Depends(get_db)):
    return await leases.statement(db, await _one(db, principal, lease_id), month, lessor_view=True)


@router.get("/leases/{lease_id}/statement.pdf")
async def my_statement_pdf(lease_id: uuid.UUID, month: date, principal: Principal = Depends(require(OWN)), db: AsyncSession = Depends(get_db)):
    a = await _one(db, principal, lease_id)
    pdf = await _pdf(db, a, month, principal.business_id, lessor_view=True)
    return StreamingResponse(io.BytesIO(pdf), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="lease-{month:%Y-%m}.pdf"'})
