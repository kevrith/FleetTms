"""Work orders and service schedules (masterplan 5.8 and 5.19). Preventive and corrective work share one system."""

import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.db import get_db
from app.deps import Principal, error, require_any
from app.models import (
    Defect,
    Expense,
    ExpenseCategory,
    ExpenseStatus,
    Priority,
    ServiceRecord,
    ServiceSchedule,
    Vehicle,
    WorkOrder,
    WorkOrderPart,
    WorkOrderSource,
    WorkOrderStatus,
)
from app.reminders import NAIROBI, nairobi_today
from app.routers.vehicles import get_vehicle
from app.service_rules import service_due
from app.vehicle_scope import scope_vehicles, vehicle_in_scope

router = APIRouter(tags=["workshop"])
OPEN = (WorkOrderStatus.OPEN, WorkOrderStatus.IN_PROGRESS, WorkOrderStatus.WAITING_PARTS)
READ = ("workshop.manage", "vehicles.view")
WRITE = ("workshop.manage",)
SCHEDULE_WRITE = ("workshop.manage", "vehicles.manage")


class PartIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    quantity: int = Field(default=1, ge=1, le=10_000)
    unit_cost_cents: int = Field(default=0, ge=0, le=1_000_000_000)


class WorkOrderIn(BaseModel):
    vehicle_id: uuid.UUID
    title: str = Field(min_length=3, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    priority: Priority = Priority.NORMAL
    assignee_kind: str | None = Field(default=None, pattern="^(mechanic|garage)$")
    assignee_name: str | None = Field(default=None, max_length=160)


class WorkOrderUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    priority: Priority | None = None
    status: WorkOrderStatus | None = None
    assignee_kind: str | None = Field(default=None, pattern="^(mechanic|garage)$")
    assignee_name: str | None = Field(default=None, max_length=160)
    labour_cents: int | None = Field(default=None, ge=0, le=1_000_000_000)
    parts: list[PartIn] | None = None


class CompleteIn(BaseModel):
    odometer_km: int | None = Field(default=None, ge=0, le=9_999_999)
    labour_cents: int | None = Field(default=None, ge=0, le=1_000_000_000)
    notes: str | None = Field(default=None, max_length=2000)


class ScheduleIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    every_km: int | None = Field(default=None, gt=0, le=1_000_000)
    every_months: int | None = Field(default=None, gt=0, le=120)
    last_done_km: int = Field(default=0, ge=0, le=9_999_999)
    last_done_on: date | None = None
    advance_km: int = Field(default=500, ge=0, le=100_000)
    advance_days: int = Field(default=14, ge=0, le=365)
    is_active: bool = True


def parts_total(wo: WorkOrder) -> int:
    return sum(p.quantity * p.unit_cost_cents for p in wo.parts)


def work_order_out(wo: WorkOrder) -> dict:
    return {
        "id": wo.id, "vehicle_id": wo.vehicle_id, "source": wo.source.value, "defect_id": wo.defect_id,
        "schedule_id": wo.schedule_id, "title": wo.title, "description": wo.description, "priority": wo.priority.value,
        "status": wo.status.value, "assignee_kind": wo.assignee_kind, "assignee_name": wo.assignee_name,
        "labour_cents": wo.labour_cents, "parts_cents": parts_total(wo), "total_cents": wo.labour_cents + parts_total(wo),
        "parts": [
            {"id": p.id, "name": p.name, "quantity": p.quantity, "unit_cost_cents": p.unit_cost_cents, "part_id": p.part_id, "fitted": p.fitted}
            for p in wo.parts
        ],
        "unfitted_parts": sum(1 for p in wo.parts if p.part_id and not p.fitted),
        "odometer_km": wo.odometer_km, "opened_at": wo.opened_at, "completed_at": wo.completed_at,
    }  # fmt: skip


async def work_order_from_defect(db: AsyncSession, defect: Defect, vehicle: Vehicle, user_id: uuid.UUID | None) -> WorkOrder:
    """Every defect found in an inspection becomes a work order at once (masterplan 5.19)."""
    wo = WorkOrder(
        vehicle_id=vehicle.id, source=WorkOrderSource.DEFECT, defect_id=defect.id,
        title=f"{defect.label}: {defect.note or 'fault found in inspection'}"[:160], description=defect.note,
        priority=Priority.URGENT if defect.critical else Priority.NORMAL, created_by_user_id=user_id,
    )  # fmt: skip
    db.add(wo)
    await db.flush()
    defect.work_order_id = wo.id
    defect.status = "work_order"
    return wo


async def _get_wo(db: AsyncSession, principal: Principal, wo_id: uuid.UUID) -> WorkOrder:
    wo = (await db.execute(select(WorkOrder).where(WorkOrder.id == wo_id))).scalar_one_or_none()
    if wo is None or ("workshop.manage" not in principal.permissions and not vehicle_in_scope(principal, wo.vehicle_id)):
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That work order was not found.")
    return wo


@router.get("/workshop/vehicles")
async def workshop_vehicles(principal: Principal = Depends(require_any(*WRITE)), db: AsyncSession = Depends(get_db)):
    """Just enough about each vehicle for workshop screens (which vehicle, what odometer), for staff who cannot see the
    full vehicle list."""
    rows = (await db.execute(select(Vehicle).order_by(Vehicle.registration))).scalars()
    return [{"id": v.id, "registration": v.registration, "make": v.make, "model": v.model, "odometer_km": v.odometer_km} for v in rows]


# ---- Work orders -----------------------------------------------------------------------------------


@router.get("/work-orders")
async def list_work_orders(
    status_filter: WorkOrderStatus | None = None,
    vehicle_id: uuid.UUID | None = None,
    open_only: bool = False,
    principal: Principal = Depends(require_any(*READ)),
    db: AsyncSession = Depends(get_db),
):
    query = select(WorkOrder).order_by(WorkOrder.opened_at.desc()).limit(300)
    if "workshop.manage" not in principal.permissions and principal.vehicle_scope is not None:
        query = query.where(WorkOrder.vehicle_id.in_(scope_vehicles(select(Vehicle.id), principal)))
    if status_filter:
        query = query.where(WorkOrder.status == status_filter)
    if open_only:
        query = query.where(WorkOrder.status.in_(OPEN))
    if vehicle_id:
        query = query.where(WorkOrder.vehicle_id == vehicle_id)
    plates = {v.id: v.registration for v in (await db.execute(select(Vehicle))).scalars()}
    return [work_order_out(w) | {"registration": plates.get(w.vehicle_id)} for w in (await db.execute(query)).scalars()]


@router.get("/work-orders/{wo_id}")
async def read_work_order(wo_id: uuid.UUID, principal: Principal = Depends(require_any(*READ)), db: AsyncSession = Depends(get_db)):
    return work_order_out(await _get_wo(db, principal, wo_id))


@router.post("/work-orders", status_code=status.HTTP_201_CREATED)
async def create_work_order(
    body: WorkOrderIn, principal: Principal = Depends(require_any(*WRITE)), db: AsyncSession = Depends(get_db)
):
    vehicle = (await db.execute(select(Vehicle).where(Vehicle.id == body.vehicle_id))).scalar_one_or_none()
    if vehicle is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That vehicle was not found.")
    wo = WorkOrder(
        vehicle_id=vehicle.id, source=WorkOrderSource.MANUAL, title=body.title.strip(), description=body.description,
        priority=body.priority, assignee_kind=body.assignee_kind, assignee_name=body.assignee_name,
        created_by_user_id=principal.user.id, parts=[],
    )  # fmt: skip
    db.add(wo)
    await db.flush()
    audit.record(db, actor_user_id=principal.user.id, action="work_order.created", entity_type="work_order", entity_id=wo.id, after={"title": wo.title, "vehicle_id": str(vehicle.id)})
    await db.commit()
    return work_order_out(wo)


@router.put("/work-orders/{wo_id}")
async def update_work_order(
    wo_id: uuid.UUID, body: WorkOrderUpdate, principal: Principal = Depends(require_any(*WRITE)), db: AsyncSession = Depends(get_db)
):
    wo = await _get_wo(db, principal, wo_id)
    if wo.status in (WorkOrderStatus.DONE, WorkOrderStatus.CANCELLED):
        raise error(status.HTTP_409_CONFLICT, "closed", "That work order is already closed.")
    if body.status == WorkOrderStatus.DONE:
        raise error(422, "use_complete", "Use the complete action to finish a work order, so its cost is recorded.")
    before = {"status": wo.status.value, "assignee": wo.assignee_name}
    for field in ("title", "description", "priority", "assignee_kind", "assignee_name", "labour_cents"):
        value = getattr(body, field)
        if value is not None:
            setattr(wo, field, value)
    if body.status is not None:
        wo.status = body.status
        if body.status == WorkOrderStatus.CANCELLED and wo.defect_id:
            defect = (await db.execute(select(Defect).where(Defect.id == wo.defect_id))).scalar_one_or_none()
            if defect:
                defect.status = "open"
    if body.parts is not None:
        for old in [p for p in wo.parts if p.part_id is None]:  # parts issued from the store are changed by returning them
            wo.parts.remove(old)
        await db.flush()
        wo.parts.extend(WorkOrderPart(name=p.name, quantity=p.quantity, unit_cost_cents=p.unit_cost_cents) for p in body.parts)
    audit.record(db, actor_user_id=principal.user.id, action="work_order.updated", entity_type="work_order", entity_id=wo.id, before=before, after={"status": wo.status.value, "assignee": wo.assignee_name})
    await db.commit()
    return work_order_out(wo)


@router.post("/work-orders/{wo_id}/complete")
async def complete_work_order(
    wo_id: uuid.UUID, body: CompleteIn, principal: Principal = Depends(require_any(*WRITE)), db: AsyncSession = Depends(get_db)
):
    """Finishes the work. Its cost becomes a repair or service expense on the vehicle, so true cost per lorry stays right;
    a service work order also records the service and restarts its schedule."""
    wo = await _get_wo(db, principal, wo_id)
    if wo.status in (WorkOrderStatus.DONE, WorkOrderStatus.CANCELLED):
        raise error(status.HTTP_409_CONFLICT, "closed", "That work order is already closed.")
    vehicle = (await db.execute(select(Vehicle).where(Vehicle.id == wo.vehicle_id))).scalar_one()
    now = datetime.now(UTC)
    if body.labour_cents is not None:
        wo.labour_cents = body.labour_cents
    wo.odometer_km = body.odometer_km if body.odometer_km is not None else vehicle.odometer_km
    wo.status, wo.completed_at = WorkOrderStatus.DONE, now
    if body.notes:
        wo.description = f"{wo.description}\n\n{body.notes}" if wo.description else body.notes
    vehicle.odometer_km = max(vehicle.odometer_km, wo.odometer_km)
    total = wo.labour_cents + parts_total(wo)
    # Parts issued from the store were charged to the vehicle when they were issued; only the rest is booked now.
    to_book = wo.labour_cents + sum(p.quantity * p.unit_cost_cents for p in wo.parts if p.part_id is None)
    is_service = wo.source == WorkOrderSource.SERVICE
    if to_book > 0:
        db.add(
            Expense(
                vehicle_id=vehicle.id, work_order_id=wo.id,
                category=ExpenseCategory.SERVICE if is_service else ExpenseCategory.REPAIR, amount_cents=to_book,
                note=wo.title[:255], status=ExpenseStatus.RECORDED, spent_at=now, created_by_user_id=principal.user.id,
            )
        )  # fmt: skip
    if wo.defect_id:
        defect = (await db.execute(select(Defect).where(Defect.id == wo.defect_id))).scalar_one_or_none()
        if defect:
            defect.status = "fixed"
    if is_service or wo.schedule_id:
        today = nairobi_today()
        db.add(ServiceRecord(vehicle_id=vehicle.id, schedule_id=wo.schedule_id, work_order_id=wo.id, done_on=today, odometer_km=wo.odometer_km, cost_cents=total, notes=body.notes))
        schedule = (await db.execute(select(ServiceSchedule).where(ServiceSchedule.id == wo.schedule_id))).scalar_one_or_none() if wo.schedule_id else None
        if schedule:
            schedule.last_done_km, schedule.last_done_on = wo.odometer_km, today
    audit.record(db, actor_user_id=principal.user.id, action="work_order.completed", entity_type="work_order", entity_id=wo.id, after={"total_cents": total, "odometer_km": wo.odometer_km})
    await db.commit()
    return work_order_out(wo)


# ---- Service schedules -----------------------------------------------------------------------------


def schedule_out(s: ServiceSchedule, vehicle: Vehicle, today: date) -> dict:
    due = service_due(
        every_km=s.every_km, every_months=s.every_months, last_done_km=s.last_done_km, last_done_on=s.last_done_on,
        advance_km=s.advance_km, advance_days=s.advance_days, odometer_km=vehicle.odometer_km, today=today,
        started_on=s.created_at.astimezone(NAIROBI).date(),
    )  # fmt: skip
    return {
        "id": s.id, "vehicle_id": s.vehicle_id, "registration": vehicle.registration, "name": s.name,
        "every_km": s.every_km, "every_months": s.every_months, "last_done_km": s.last_done_km,
        "last_done_on": s.last_done_on, "advance_km": s.advance_km, "advance_days": s.advance_days, "is_active": s.is_active,
        "due_status": due.status if s.is_active else "inactive", "next_km": due.next_km, "km_left": due.km_left,
        "next_due_on": due.next_due_on, "days_left": due.days_left,
    }  # fmt: skip


def _check_schedule(body: ScheduleIn) -> None:
    if not body.every_km and not body.every_months:
        raise error(422, "interval_required", "Set how often: every so many kilometres, every so many months, or both.")


@router.get("/service-schedules")
async def list_schedules(
    due_only: bool = False, principal: Principal = Depends(require_any(*READ)), db: AsyncSession = Depends(get_db)
):
    """Every schedule across the fleet with where it stands, most urgent first."""
    vehicles = {v.id: v for v in (await db.execute(scope_vehicles(select(Vehicle), principal))).scalars()}
    rows = (await db.execute(select(ServiceSchedule).where(ServiceSchedule.vehicle_id.in_(list(vehicles))))).scalars().all()
    today = nairobi_today()
    out = [schedule_out(s, vehicles[s.vehicle_id], today) for s in rows if s.is_active]
    if due_only:
        out = [s for s in out if s["due_status"] != "ok"]
    rank = {"overdue": 0, "due_soon": 1, "ok": 2}
    return sorted(out, key=lambda s: (rank.get(s["due_status"], 3), s["km_left"] if s["km_left"] is not None else 10**9))


@router.get("/vehicles/{vehicle_id}/services")
async def vehicle_services(
    vehicle_id: uuid.UUID, principal: Principal = Depends(require_any(*READ)), db: AsyncSession = Depends(get_db)
):
    vehicle = await get_vehicle(db, principal, vehicle_id)
    today = nairobi_today()
    schedules = (await db.execute(select(ServiceSchedule).where(ServiceSchedule.vehicle_id == vehicle.id).order_by(ServiceSchedule.name))).scalars()
    history = (await db.execute(select(ServiceRecord).where(ServiceRecord.vehicle_id == vehicle.id).order_by(ServiceRecord.done_on.desc()).limit(50))).scalars()
    return {
        "schedules": [schedule_out(s, vehicle, today) for s in schedules],
        "history": [
            {"id": r.id, "schedule_id": r.schedule_id, "done_on": r.done_on, "odometer_km": r.odometer_km, "cost_cents": r.cost_cents, "notes": r.notes}
            for r in history
        ],
    }  # fmt: skip


@router.post("/vehicles/{vehicle_id}/services", status_code=status.HTTP_201_CREATED)
async def add_schedule(
    vehicle_id: uuid.UUID, body: ScheduleIn, principal: Principal = Depends(require_any(*SCHEDULE_WRITE)), db: AsyncSession = Depends(get_db)
):
    vehicle = await get_vehicle(db, principal, vehicle_id)
    _check_schedule(body)
    schedule = ServiceSchedule(vehicle_id=vehicle.id, **body.model_dump())
    db.add(schedule)
    await db.flush()
    audit.record(db, actor_user_id=principal.user.id, action="service_schedule.created", entity_type="service_schedule", entity_id=schedule.id, after={"name": schedule.name, "vehicle_id": str(vehicle.id)})
    await db.commit()
    await db.refresh(schedule)
    return schedule_out(schedule, vehicle, nairobi_today())


@router.put("/service-schedules/{schedule_id}")
async def update_schedule(
    schedule_id: uuid.UUID, body: ScheduleIn, principal: Principal = Depends(require_any(*SCHEDULE_WRITE)), db: AsyncSession = Depends(get_db)
):
    schedule = (await db.execute(select(ServiceSchedule).where(ServiceSchedule.id == schedule_id))).scalar_one_or_none()
    if schedule is None or not vehicle_in_scope(principal, schedule.vehicle_id):
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That schedule was not found.")
    _check_schedule(body)
    for field, value in body.model_dump().items():
        setattr(schedule, field, value)
    vehicle = (await db.execute(select(Vehicle).where(Vehicle.id == schedule.vehicle_id))).scalar_one()
    audit.record(db, actor_user_id=principal.user.id, action="service_schedule.updated", entity_type="service_schedule", entity_id=schedule.id, after={"name": schedule.name})
    await db.commit()
    return schedule_out(schedule, vehicle, nairobi_today())
