"""Incidents, breakdowns, fines and insurance claims (masterplan 5.21)."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.clock import capture_time
from app.db import get_db
from app.deps import Principal, error, require_any
from app.models import (
    ClaimStatus,
    CrewAssignment,
    Expense,
    ExpenseCategory,
    ExpenseStatus,
    FinePayer,
    Incident,
    IncidentType,
    InsuranceClaim,
    Membership,
    Photo,
    PhotoKind,
    Priority,
    Vehicle,
    WorkOrder,
    WorkOrderSource,
)
from app.photos import claim_photo, photo_out
from app.vehicle_scope import scope_vehicles

router = APIRouter(tags=["incidents"])
MANAGE = ("incidents.manage",)
VIEW = ("incidents.manage", "vehicles.view")
FINE_TYPES = {IncidentType.TRAFFIC_FINE, IncidentType.COUNTY_CESS, IncidentType.POLICE_STOP}
TITLES = {IncidentType.BREAKDOWN: "Breakdown", IncidentType.ACCIDENT: "Accident"}


class IncidentIn(BaseModel):
    type: IncidentType
    vehicle_id: uuid.UUID | None = None  # a driver's report defaults to the vehicle they crew
    driver_membership_id: uuid.UUID | None = None  # managers can say whose incident it was
    trip_id: uuid.UUID | None = None
    description: str | None = Field(default=None, max_length=2000)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    occurred_at: datetime | None = None
    photo_ids: list[uuid.UUID] = Field(default_factory=list, max_length=8)
    photo_client_ids: list[uuid.UUID] = Field(default_factory=list, max_length=8)  # ids the phone gave photos offline
    fine_amount_cents: int | None = Field(default=None, gt=0, le=1_000_000_000)
    fine_payer: FinePayer | None = None
    deduct_from_payroll: bool = False
    reference: str | None = Field(default=None, max_length=60)


class FineIn(BaseModel):
    fine_amount_cents: int | None = Field(default=None, gt=0, le=1_000_000_000)
    fine_payer: FinePayer | None = None
    deduct_from_payroll: bool = False
    reference: str | None = Field(default=None, max_length=60)


class ResolveIn(BaseModel):
    note: str | None = Field(default=None, max_length=500)
    cost_cents: int | None = Field(default=None, ge=0, le=1_000_000_000)


class ClaimIn(BaseModel):
    insurer: str = Field(min_length=2, max_length=120)
    policy_no: str | None = Field(default=None, max_length=60)
    claim_no: str | None = Field(default=None, max_length=60)
    amount_claimed_cents: int | None = Field(default=None, ge=0, le=10_000_000_000)
    notes: str | None = Field(default=None, max_length=2000)


class ClaimUpdate(BaseModel):
    status: ClaimStatus | None = None
    claim_no: str | None = Field(default=None, max_length=60)
    amount_claimed_cents: int | None = Field(default=None, ge=0, le=10_000_000_000)
    amount_paid_cents: int | None = Field(default=None, ge=0, le=10_000_000_000)
    notes: str | None = Field(default=None, max_length=2000)
    document_photo_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)


def claim_out(c: InsuranceClaim, photos: dict[uuid.UUID, Photo] | None = None) -> dict:
    photos = photos or {}
    return {
        "id": c.id, "incident_id": c.incident_id, "insurer": c.insurer, "policy_no": c.policy_no, "claim_no": c.claim_no,
        "status": c.status.value, "amount_claimed_cents": c.amount_claimed_cents, "amount_paid_cents": c.amount_paid_cents,
        "notes": c.notes, "created_at": c.created_at, "updated_at": c.updated_at,
        "documents": [photo_out(photos[uuid.UUID(i)]) for i in c.document_photo_ids if uuid.UUID(i) in photos],
    }  # fmt: skip


async def _photos(db: AsyncSession, ids: list[str]) -> dict[uuid.UUID, Photo]:
    if not ids:
        return {}
    return {p.id: p for p in (await db.execute(select(Photo).where(Photo.id.in_([uuid.UUID(i) for i in ids])))).scalars()}


def incident_out(i: Incident, vehicles: dict, members: dict, photos: dict | None = None) -> dict:
    photos = photos or {}
    vehicle = vehicles.get(i.vehicle_id)
    return {
        "id": i.id, "type": i.type.value, "vehicle_id": i.vehicle_id, "registration": vehicle.registration if vehicle else None,
        "driver_membership_id": i.driver_membership_id, "driver_name": members.get(i.driver_membership_id),
        "trip_id": i.trip_id, "occurred_at": i.occurred_at, "lat": i.lat, "lng": i.lng, "description": i.description,
        "status": i.status, "cost_cents": i.cost_cents, "fine_amount_cents": i.fine_amount_cents,
        "fine_payer": i.fine_payer.value if i.fine_payer else None, "deduct_from_payroll": i.deduct_from_payroll,
        "reference": i.reference, "work_order_id": i.work_order_id, "resolution_note": i.resolution_note,
        "resolved_at": i.resolved_at, "created_at": i.created_at,
        "photos": [photo_out(photos[uuid.UUID(p)]) for p in i.photo_ids if uuid.UUID(p) in photos],
    }  # fmt: skip


async def _members(db: AsyncSession) -> dict[uuid.UUID, str]:
    return {m.id: m.user.name for m in (await db.execute(select(Membership))).scalars()}


async def _fine_expense(db: AsyncSession, incident: Incident, user_id: uuid.UUID | None) -> None:
    """Keeps the cost of a fine in step with who pays: a fine the business pays is a cost on the vehicle; one the driver
    pays is not (and is flagged for payroll deduction)."""
    wanted = bool(incident.fine_amount_cents and incident.fine_payer == FinePayer.BUSINESS and incident.vehicle_id)
    expense = (await db.execute(select(Expense).where(Expense.id == incident.expense_id))).scalar_one_or_none() if incident.expense_id else None
    if wanted and expense is None:
        category = ExpenseCategory.OTHER if incident.type == IncidentType.TRAFFIC_FINE else ExpenseCategory.POLICE_COUNTY
        expense = Expense(
            vehicle_id=incident.vehicle_id, trip_id=incident.trip_id, driver_membership_id=incident.driver_membership_id,
            category=category, amount_cents=incident.fine_amount_cents, note=f"{incident.type.value.replace('_', ' ').capitalize()} {incident.reference or ''}".strip()[:255],
            status=ExpenseStatus.RECORDED, spent_at=incident.occurred_at, created_by_user_id=user_id,
        )  # fmt: skip
        db.add(expense)
        await db.flush()
        incident.expense_id = expense.id
    elif wanted and expense is not None:
        expense.amount_cents = incident.fine_amount_cents
    elif not wanted and expense is not None:
        incident.expense_id = None
        await db.delete(expense)
    incident.deduct_from_payroll = bool(incident.fine_amount_cents and incident.fine_payer == FinePayer.DRIVER and incident.deduct_from_payroll)


async def do_report_incident(db: AsyncSession, principal: Principal, body: IncidentIn) -> Incident:
    """One-tap report from the road (or entered by a manager). The caller commits."""
    manager = "incidents.manage" in principal.permissions
    occurred = capture_time(body.occurred_at)
    crew = None
    if principal.membership_id is not None:
        crew = (
            await db.execute(select(CrewAssignment).where(CrewAssignment.membership_id == principal.membership_id, CrewAssignment.ended_at.is_(None)).limit(1))
        ).scalar_one_or_none()
    vehicle_id, driver_id = body.vehicle_id, body.driver_membership_id
    if not manager:
        if crew is None:
            raise error(status.HTTP_403_FORBIDDEN, "not_your_vehicle", "You are not assigned to a vehicle.")
        if vehicle_id is not None and vehicle_id != crew.vehicle_id:
            raise error(status.HTTP_403_FORBIDDEN, "not_your_vehicle", "You are not assigned to this vehicle.")
        vehicle_id, driver_id = crew.vehicle_id, principal.membership_id
        if body.fine_amount_cents or body.fine_payer:
            raise error(status.HTTP_403_FORBIDDEN, "fine_by_manager", "Fines are decided by your manager. Report the stop and add the ticket number.")
    elif vehicle_id is None and crew is not None:
        vehicle_id = crew.vehicle_id
    in_scope = vehicle_id is None or (await db.execute(scope_vehicles(select(Vehicle.id).where(Vehicle.id == vehicle_id), principal))).first()
    if not in_scope:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That vehicle was not found.")
    if body.fine_amount_cents and body.type not in FINE_TYPES:
        raise error(422, "not_a_fine", "Only a police stop, traffic fine or county cess carries a fine amount.")
    if body.fine_amount_cents and body.fine_payer is None:
        raise error(422, "payer_required", "Say who pays the fine: the business or the driver.")

    photo_ids: list[str] = []
    for pid, cid in [(p, None) for p in body.photo_ids] + [(None, c) for c in body.photo_client_ids]:
        photo = await claim_photo(db, principal, pid, PhotoKind.INCIDENT, required=False, client_id=cid, near=occurred)
        if photo is not None:
            photo_ids.append(str(photo.id))
    lat, lng = body.lat, body.lng
    incident = Incident(
        type=body.type, vehicle_id=vehicle_id, driver_membership_id=driver_id, trip_id=body.trip_id, occurred_at=occurred,
        lat=lat, lng=lng, description=(body.description or "").strip() or None, photo_ids=photo_ids,
        fine_amount_cents=body.fine_amount_cents, fine_payer=body.fine_payer, deduct_from_payroll=body.deduct_from_payroll,
        reference=body.reference, created_by_user_id=principal.user.id,
    )  # fmt: skip
    db.add(incident)
    await db.flush()
    if body.type == IncidentType.BREAKDOWN and vehicle_id is not None:
        wo = WorkOrder(
            vehicle_id=vehicle_id, source=WorkOrderSource.INCIDENT, priority=Priority.URGENT, created_by_user_id=principal.user.id,
            title=f"Breakdown: {incident.description or 'reported from the road'}"[:160], description=incident.description, parts=[],
        )  # fmt: skip
        db.add(wo)
        await db.flush()
        incident.work_order_id = wo.id
    await _fine_expense(db, incident, principal.user.id)
    audit.record(db, actor_user_id=principal.user.id, action="incident.reported", entity_type="incident", entity_id=incident.id, after={"type": body.type.value, "vehicle_id": str(vehicle_id) if vehicle_id else None})
    return incident


@router.post("/incidents", status_code=status.HTTP_201_CREATED)
async def report(body: IncidentIn, principal: Principal = Depends(require_any("trips.own", *MANAGE)), db: AsyncSession = Depends(get_db)):
    incident = await do_report_incident(db, principal, body)
    await db.commit()
    return incident_out(incident, await _vehicle_map(db, principal), await _members(db), await _photos(db, incident.photo_ids))


async def _vehicle_map(db: AsyncSession, principal: Principal) -> dict:
    return {v.id: v for v in (await db.execute(scope_vehicles(select(Vehicle), principal))).scalars()}


async def _incident(db: AsyncSession, principal: Principal, incident_id: uuid.UUID, *, manager_only: bool = False) -> Incident:
    incident = (await db.execute(select(Incident).where(Incident.id == incident_id))).scalar_one_or_none()
    allowed = incident is not None
    if incident is not None:
        if "incidents.manage" in principal.permissions:
            allowed = True
        elif manager_only:
            allowed = False
        elif "vehicles.view" in principal.permissions:
            allowed = incident.vehicle_id is not None and (principal.vehicle_scope is None or str(incident.vehicle_id) in principal.vehicle_scope)
        else:
            allowed = incident.driver_membership_id == principal.membership_id
    if not allowed:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That incident was not found.")
    return incident


@router.get("/incidents")
async def list_incidents(
    type_filter: IncidentType | None = None,
    status_filter: str | None = None,
    vehicle_id: uuid.UUID | None = None,
    driver_membership_id: uuid.UUID | None = None,
    principal: Principal = Depends(require_any(*VIEW)),
    db: AsyncSession = Depends(get_db),
):
    vehicles = await _vehicle_map(db, principal)
    query = select(Incident).order_by(Incident.occurred_at.desc()).limit(300)
    if type_filter:
        query = query.where(Incident.type == type_filter)
    if status_filter:
        query = query.where(Incident.status == status_filter)
    if vehicle_id:
        query = query.where(Incident.vehicle_id == vehicle_id)
    if driver_membership_id:
        query = query.where(Incident.driver_membership_id == driver_membership_id)
    rows = (await db.execute(query)).scalars().all()
    if principal.vehicle_scope is not None:
        rows = [i for i in rows if i.vehicle_id in vehicles]
    members = await _members(db)
    return [incident_out(i, vehicles, members) for i in rows]


@router.get("/me/incidents")
async def my_incidents(principal: Principal = Depends(require_any("trips.own")), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(select(Incident).where(Incident.driver_membership_id == principal.membership_id).order_by(Incident.occurred_at.desc()).limit(30))
    ).scalars()
    vehicles = {v.id: v for v in (await db.execute(select(Vehicle))).scalars()}
    return [incident_out(i, vehicles, {}) for i in rows]


@router.get("/incidents/{incident_id}")
async def read_incident(incident_id: uuid.UUID, principal: Principal = Depends(require_any("trips.own", *VIEW)), db: AsyncSession = Depends(get_db)):
    incident = await _incident(db, principal, incident_id)
    claims = (await db.execute(select(InsuranceClaim).where(InsuranceClaim.incident_id == incident.id).order_by(InsuranceClaim.created_at))).scalars().all()
    photos = await _photos(db, incident.photo_ids + [d for c in claims for d in c.document_photo_ids])
    out = incident_out(incident, await _vehicle_map(db, principal), await _members(db), photos)
    out["claims"] = [claim_out(c, photos) for c in claims] if "incidents.manage" in principal.permissions else []
    return out


@router.put("/incidents/{incident_id}/fine")
async def set_fine(incident_id: uuid.UUID, body: FineIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    """The manager decides the amount and who pays. A fine the business pays becomes a cost on the vehicle."""
    incident = await _incident(db, principal, incident_id, manager_only=True)
    if body.fine_amount_cents and incident.type not in FINE_TYPES:
        raise error(422, "not_a_fine", "Only a police stop, traffic fine or county cess carries a fine amount.")
    if body.fine_amount_cents and body.fine_payer is None:
        raise error(422, "payer_required", "Say who pays the fine: the business or the driver.")
    before = {"amount": incident.fine_amount_cents, "payer": incident.fine_payer.value if incident.fine_payer else None}
    incident.fine_amount_cents, incident.fine_payer, incident.reference = body.fine_amount_cents, body.fine_payer if body.fine_amount_cents else None, body.reference or incident.reference
    incident.deduct_from_payroll = body.deduct_from_payroll
    await _fine_expense(db, incident, principal.user.id)
    audit.record(db, actor_user_id=principal.user.id, action="incident.fine_set", entity_type="incident", entity_id=incident.id, before=before, after={"amount": incident.fine_amount_cents, "payer": body.fine_payer.value if body.fine_payer else None})
    await db.commit()
    return incident_out(incident, await _vehicle_map(db, principal), await _members(db), await _photos(db, incident.photo_ids))


@router.post("/incidents/{incident_id}/resolve")
async def resolve(incident_id: uuid.UUID, body: ResolveIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    incident = await _incident(db, principal, incident_id, manager_only=True)
    incident.status, incident.resolved_at = "resolved", datetime.now(UTC)
    incident.resolution_note = body.note
    if body.cost_cents is not None:
        incident.cost_cents = body.cost_cents
    audit.record(db, actor_user_id=principal.user.id, action="incident.resolved", entity_type="incident", entity_id=incident.id, after={"cost_cents": incident.cost_cents})
    await db.commit()
    return incident_out(incident, await _vehicle_map(db, principal), await _members(db), await _photos(db, incident.photo_ids))


@router.get("/fines/summary")
async def fines_summary(principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    """Fines per driver and per vehicle, with who pays; driver-paid fines are flagged for payroll deduction."""
    rows = (await db.execute(select(Incident).where(Incident.fine_amount_cents.is_not(None)))).scalars().all()
    members, vehicles = await _members(db), {v.id: v.registration for v in (await db.execute(select(Vehicle))).scalars()}

    def add(buckets: dict, key, name) -> dict:
        return buckets.setdefault(key, {"id": key, "name": name, "fines": 0, "total_cents": 0, "business_cents": 0, "driver_cents": 0, "to_deduct_cents": 0})

    by_driver: dict = {}
    by_vehicle: dict = {}
    for i in rows:
        for buckets, key, name in ((by_driver, i.driver_membership_id, members.get(i.driver_membership_id, "Unknown driver")), (by_vehicle, i.vehicle_id, vehicles.get(i.vehicle_id, "No vehicle"))):
            b = add(buckets, key, name)
            b["fines"] += 1
            b["total_cents"] += i.fine_amount_cents
            if i.fine_payer == FinePayer.BUSINESS:
                b["business_cents"] += i.fine_amount_cents
            else:
                b["driver_cents"] += i.fine_amount_cents
                if i.deduct_from_payroll:
                    b["to_deduct_cents"] += i.fine_amount_cents
    return {"by_driver": sorted(by_driver.values(), key=lambda b: -b["total_cents"]), "by_vehicle": sorted(by_vehicle.values(), key=lambda b: -b["total_cents"])}


# ---- Insurance claims ------------------------------------------------------------------------------


@router.post("/incidents/{incident_id}/claims", status_code=status.HTTP_201_CREATED)
async def file_claim(incident_id: uuid.UUID, body: ClaimIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    incident = await _incident(db, principal, incident_id, manager_only=True)
    if incident.type not in (IncidentType.ACCIDENT, IncidentType.CARGO_THEFT, IncidentType.BREAKDOWN):
        raise error(422, "not_claimable", "Insurance claims are for accidents, cargo theft and breakdowns.")
    claim = InsuranceClaim(incident_id=incident.id, created_by_user_id=principal.user.id, **body.model_dump())
    db.add(claim)
    await db.flush()
    audit.record(db, actor_user_id=principal.user.id, action="claim.filed", entity_type="insurance_claim", entity_id=claim.id, after={"incident_id": str(incident.id), "insurer": body.insurer})
    await db.commit()
    return claim_out(claim)


@router.get("/claims")
async def list_claims(principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(InsuranceClaim).order_by(InsuranceClaim.created_at.desc()).limit(200))).scalars().all()
    incidents = {i.id: i for i in (await db.execute(select(Incident).where(Incident.id.in_([c.incident_id for c in rows])))).scalars()} if rows else {}
    vehicles = {v.id: v.registration for v in (await db.execute(select(Vehicle))).scalars()}
    return [claim_out(c) | {"incident_type": incidents[c.incident_id].type.value, "registration": vehicles.get(incidents[c.incident_id].vehicle_id)} for c in rows if c.incident_id in incidents]


@router.put("/claims/{claim_id}")
async def update_claim(claim_id: uuid.UUID, body: ClaimUpdate, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    claim = (await db.execute(select(InsuranceClaim).where(InsuranceClaim.id == claim_id))).scalar_one_or_none()
    if claim is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That claim was not found.")
    if body.status == ClaimStatus.PAID and body.amount_paid_cents is None and claim.amount_paid_cents is None:
        raise error(422, "amount_required", "Enter the amount the insurer paid.")
    before = claim.status.value
    for field in ("status", "claim_no", "amount_claimed_cents", "amount_paid_cents", "notes"):
        value = getattr(body, field)
        if value is not None:
            setattr(claim, field, value)
    docs = list(claim.document_photo_ids)
    for pid in body.document_photo_ids:
        photo = await claim_photo(db, principal, pid, PhotoKind.INCIDENT, required=False)
        if photo is not None:
            docs.append(str(photo.id))
    claim.document_photo_ids = docs
    claim.updated_at = datetime.now(UTC)
    audit.record(db, actor_user_id=principal.user.id, action="claim.updated", entity_type="insurance_claim", entity_id=claim.id, before={"status": before}, after={"status": claim.status.value})
    await db.commit()
    return claim_out(claim, await _photos(db, claim.document_photo_ids))
