import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.clock import capture_time
from app.db import get_db
from app.deps import Principal, error, require, require_any
from app.models import (
    ChecklistItem,
    CrewAssignment,
    Defect,
    Inspection,
    InspectionResult,
    InspectionStatus,
    Photo,
    PhotoKind,
    Vehicle,
)
from app.photos import claim_photo, photo_out
from app.reminders import NAIROBI, nairobi_today
from app.routers.tyres import SerialIn, check_serials
from app.routers.vehicles import get_vehicle
from app.routers.workshop import work_order_from_defect
from app.vehicle_scope import vehicle_in_scope

router = APIRouter(tags=["inspections"])

# Brakes and tyres are critical out of the box; each business can change this.
DEFAULT_CHECKLIST = [
    ("Brakes", True),
    ("Tyres: condition and pressure", True),
    ("Lights and indicators", False),
    ("Oil level", False),
    ("Coolant level", False),
    ("Leaks under the vehicle", False),
    ("Body damage", False),
    ("Tyre serial numbers match", False),
]
OK_FOR_TRIP = {InspectionStatus.PASSED, InspectionStatus.PASSED_WITH_DEFECTS, InspectionStatus.OVERRIDDEN}


class ChecklistItemIn(BaseModel):
    label: str = Field(min_length=2, max_length=120)
    critical: bool = False
    photo_on_fault: bool = True
    is_active: bool = True
    sort_order: int = Field(default=100, ge=0, le=10_000)


class ResultIn(BaseModel):
    item_id: uuid.UUID
    ok: bool
    note: str | None = Field(default=None, max_length=1000)
    photo_id: uuid.UUID | None = None
    photo_client_id: uuid.UUID | None = None  # the id the phone gave the photo while offline


class InspectionIn(BaseModel):
    results: list[ResultIn] = Field(min_length=1)
    tyre_serials: list[SerialIn] = Field(default_factory=list, max_length=30)  # what the driver read off each tyre
    notes: str | None = Field(default=None, max_length=1000)
    captured_at: datetime | None = None  # when the driver did it; missing means now


class OverrideIn(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)


def item_out(i: ChecklistItem) -> dict:
    return {
        "id": i.id, "label": i.label, "critical": i.critical, "photo_on_fault": i.photo_on_fault,
        "is_active": i.is_active, "sort_order": i.sort_order,
    }  # fmt: skip


async def ensure_checklist(db: AsyncSession) -> None:
    """Gives a business the standard checklist the first time it is needed."""
    if (await db.execute(select(ChecklistItem.id).limit(1))).first() is None:
        for order, (label, critical) in enumerate(DEFAULT_CHECKLIST):
            db.add(ChecklistItem(label=label, critical=critical, sort_order=order * 10))
        await db.flush()


async def can_act_on_vehicle(db: AsyncSession, principal: Principal, vehicle: Vehicle) -> bool:
    """Managers act on any vehicle in their scope; drivers and turnboys only on the one they crew."""
    if "trips.manage" in principal.permissions:
        return vehicle_in_scope(principal, vehicle.id)
    if principal.membership_id is None:
        return False
    return (
        await db.execute(
            select(CrewAssignment.id).where(
                CrewAssignment.vehicle_id == vehicle.id,
                CrewAssignment.membership_id == principal.membership_id,
                CrewAssignment.ended_at.is_(None),
            )
        )
    ).first() is not None


async def latest_inspection_today(db: AsyncSession, vehicle_id: uuid.UUID) -> Inspection | None:
    return await latest_inspection_on(db, vehicle_id, nairobi_today())


async def latest_inspection_on(db: AsyncSession, vehicle_id: uuid.UUID, day: date) -> Inspection | None:
    """The newest inspection for a vehicle on a given Nairobi day. An offline trip is judged on the day it was driven."""
    return (
        await db.execute(
            select(Inspection)
            .where(Inspection.vehicle_id == vehicle_id, Inspection.local_date == day)
            .order_by(Inspection.performed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def inspection_out(db: AsyncSession, i: Inspection) -> dict:
    photo_ids = [r.photo_id for r in i.results if r.photo_id]
    photos = (
        {p.id: p for p in (await db.execute(select(Photo).where(Photo.id.in_(photo_ids)))).scalars()}
        if photo_ids
        else {}
    )
    return {
        "id": i.id,
        "vehicle_id": i.vehicle_id,
        "performed_at": i.performed_at,
        "status": i.status.value,
        "notes": i.notes,
        "override_reason": i.override_reason,
        "overridden_at": i.overridden_at,
        "results": [
            {
                "label": r.label, "critical": r.critical, "ok": r.ok, "note": r.note,
                "photo": photo_out(photos.get(r.photo_id)) if r.photo_id else None,
            }
            for r in i.results
        ],
    }  # fmt: skip


# ---- Checklist -----------------------------------------------------------------------------------


@router.get("/inspection/checklist")
async def get_checklist(
    include_inactive: bool = False,
    principal: Principal = Depends(require_any("trips.own", "vehicles.view")),
    db: AsyncSession = Depends(get_db),
):
    await ensure_checklist(db)
    await db.commit()
    query = select(ChecklistItem).order_by(ChecklistItem.sort_order, ChecklistItem.label)
    if not (include_inactive and "vehicles.manage" in principal.permissions):
        query = query.where(ChecklistItem.is_active.is_(True))
    return [item_out(i) for i in (await db.execute(query)).scalars()]


@router.post("/inspection/checklist", status_code=status.HTTP_201_CREATED)
async def add_checklist_item(
    body: ChecklistItemIn, principal: Principal = Depends(require("vehicles.manage")), db: AsyncSession = Depends(get_db)
):
    await ensure_checklist(db)
    item = ChecklistItem(**body.model_dump())
    db.add(item)
    await db.flush()
    audit.record(
        db, actor_user_id=principal.user.id, action="checklist.item_added", entity_type="checklist_item",
        entity_id=item.id, after=item_out(item) | {"id": str(item.id)},
    )  # fmt: skip
    await db.commit()
    return item_out(item)


@router.put("/inspection/checklist/{item_id}")
async def update_checklist_item(
    item_id: uuid.UUID,
    body: ChecklistItemIn,
    principal: Principal = Depends(require("vehicles.manage")),
    db: AsyncSession = Depends(get_db),
):
    item = (await db.execute(select(ChecklistItem).where(ChecklistItem.id == item_id))).scalar_one_or_none()
    if item is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That checklist item was not found.")
    before = item_out(item) | {"id": str(item.id)}
    for field, value in body.model_dump().items():
        setattr(item, field, value)
    audit.record(
        db, actor_user_id=principal.user.id, action="checklist.item_updated", entity_type="checklist_item",
        entity_id=item.id, before=before, after=item_out(item) | {"id": str(item.id)},
    )  # fmt: skip
    await db.commit()
    return item_out(item)


# ---- Inspections ---------------------------------------------------------------------------------


async def do_submit_inspection(
    db: AsyncSession, principal: Principal, vehicle_id: uuid.UUID, body: InspectionIn
) -> Inspection:
    """Records an inspection, as of the time the driver did it. The caller commits."""
    captured_at = capture_time(body.captured_at)
    vehicle = await get_vehicle(db, principal, vehicle_id)
    if not await can_act_on_vehicle(db, principal, vehicle):
        raise error(status.HTTP_403_FORBIDDEN, "not_your_vehicle", "You are not assigned to this vehicle.")

    await ensure_checklist(db)
    items = {i.id: i for i in (await db.execute(select(ChecklistItem).where(ChecklistItem.is_active.is_(True)))).scalars()}
    answered = [r.item_id for r in body.results]
    if len(set(answered)) != len(answered) or set(answered) != set(items):
        raise error(422, "checklist_incomplete", "Answer every item on the checklist, once each.")

    results, defects = [], []
    for r in body.results:
        item = items[r.item_id]
        photo = None
        has_photo = r.photo_id is not None or r.photo_client_id is not None
        if not r.ok:
            if not (r.note and r.note.strip()):
                raise error(422, "fault_needs_note", f"Say what is wrong with: {item.label}.")
            photo = await claim_photo(
                db, principal, r.photo_id, PhotoKind.DEFECT, required=item.photo_on_fault,
                client_id=r.photo_client_id, near=captured_at,
            )  # fmt: skip
        elif has_photo:
            photo = await claim_photo(
                db, principal, r.photo_id, PhotoKind.DEFECT, required=False, client_id=r.photo_client_id, near=captured_at
            )  # fmt: skip
        results.append(
            InspectionResult(
                item_id=item.id, label=item.label, critical=item.critical, sort_order=item.sort_order,
                ok=r.ok, note=(r.note or "").strip() or None, photo_id=photo.id if photo else None,
            )
        )  # fmt: skip
    faults = [x for x in results if not x.ok]
    if any(x.critical for x in faults):
        result_status = InspectionStatus.BLOCKED
    elif faults:
        result_status = InspectionStatus.PASSED_WITH_DEFECTS
    else:
        result_status = InspectionStatus.PASSED

    inspection = Inspection(
        vehicle_id=vehicle.id, inspector_user_id=principal.user.id, performed_at=captured_at,
        local_date=captured_at.astimezone(NAIROBI).date(), status=result_status, notes=body.notes, results=results,
    )  # fmt: skip
    db.add(inspection)
    await db.flush()
    for fault in faults:
        defects.append(
            Defect(
                inspection_id=inspection.id, vehicle_id=vehicle.id, label=fault.label, critical=fault.critical,
                note=fault.note, photo_id=fault.photo_id,
            )
        )  # fmt: skip
    db.add_all(defects)
    await db.flush()
    for defect in defects:
        await work_order_from_defect(db, defect, vehicle, principal.user.id)  # a defect becomes a work order at once
    swaps = await check_serials(db, vehicle, inspection.id, body.tyre_serials)
    for swap in swaps:
        audit.record(
            db, actor_user_id=principal.user.id, action="tyre.swap_suspected", entity_type="tyre_swap_alert",
            entity_id=swap.id, after={"position": swap.position, "expected": swap.expected_serial, "seen": swap.seen_serial},
        )  # fmt: skip
    audit.record(
        db, actor_user_id=principal.user.id, action="inspection.submitted", entity_type="inspection",
        entity_id=inspection.id,
        after={"vehicle_id": str(vehicle.id), "status": result_status.value, "faults": [f.label for f in faults]},
    )  # fmt: skip
    return inspection


@router.post("/vehicles/{vehicle_id}/inspections", status_code=status.HTTP_201_CREATED)
async def submit_inspection(
    vehicle_id: uuid.UUID,
    body: InspectionIn,
    principal: Principal = Depends(require_any("trips.own", "trips.manage")),
    db: AsyncSession = Depends(get_db),
):
    inspection = await do_submit_inspection(db, principal, vehicle_id, body)
    await db.commit()
    return await inspection_out(db, inspection)


@router.get("/vehicles/{vehicle_id}/inspections")
async def list_inspections(
    vehicle_id: uuid.UUID, principal: Principal = Depends(require("vehicles.view")), db: AsyncSession = Depends(get_db)
):
    await get_vehicle(db, principal, vehicle_id)
    rows = (
        await db.execute(
            select(Inspection).where(Inspection.vehicle_id == vehicle_id).order_by(Inspection.performed_at.desc()).limit(30)
        )
    ).scalars()
    return [await inspection_out(db, i) for i in rows]


@router.get("/vehicles/{vehicle_id}/inspections/today")
async def inspection_today(
    vehicle_id: uuid.UUID,
    principal: Principal = Depends(require_any("trips.own", "vehicles.view")),
    db: AsyncSession = Depends(get_db),
):
    """Today's inspection for the vehicle (the newest one), and whether it clears a trip to start."""
    vehicle = await get_vehicle(db, principal, vehicle_id)
    if "vehicles.view" not in principal.permissions and not await can_act_on_vehicle(db, principal, vehicle):
        raise error(status.HTTP_403_FORBIDDEN, "not_your_vehicle", "You are not assigned to this vehicle.")
    inspection = await latest_inspection_today(db, vehicle.id)
    return {
        "inspection": await inspection_out(db, inspection) if inspection else None,
        "can_start_trip": inspection is not None and inspection.status in OK_FOR_TRIP,
    }


@router.post("/inspections/{inspection_id}/override")
async def override_inspection(
    inspection_id: uuid.UUID,
    body: OverrideIn,
    principal: Principal = Depends(require("inspections.override")),
    db: AsyncSession = Depends(get_db),
):
    """A manager lets a vehicle with a critical fault go out anyway. The reason is kept and audited."""
    inspection = (await db.execute(select(Inspection).where(Inspection.id == inspection_id))).scalar_one_or_none()
    if inspection is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That inspection was not found.")
    if not vehicle_in_scope(principal, inspection.vehicle_id):
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That inspection was not found.")
    if inspection.status != InspectionStatus.BLOCKED:
        raise error(status.HTTP_409_CONFLICT, "not_blocked", "Only a blocked inspection can be overridden.")
    inspection.status = InspectionStatus.OVERRIDDEN
    inspection.override_reason = body.reason.strip()
    inspection.overridden_by_user_id = principal.user.id
    inspection.overridden_at = datetime.now(UTC)
    audit.record(
        db, actor_user_id=principal.user.id, action="inspection.overridden", entity_type="inspection",
        entity_id=inspection.id, before={"status": "blocked"},
        after={"status": "overridden", "reason": inspection.override_reason}, note=inspection.override_reason,
    )  # fmt: skip
    await db.commit()
    return await inspection_out(db, inspection)
