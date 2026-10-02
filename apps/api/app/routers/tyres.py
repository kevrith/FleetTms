"""Tyre management (masterplan 5.20): serials, positions, fitting and removal, tread, retreads, rotations and swap alerts."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.db import get_db
from app.deps import Principal, error, require, require_any
from app.models import (
    Expense,
    ExpenseCategory,
    ExpenseStatus,
    Tyre,
    TyreEvent,
    TyreEventKind,
    TyreStatus,
    TyreSwapAlert,
    Vehicle,
)
from app.reminders import nairobi_today
from app.routers.vehicles import get_vehicle
from app.tyre_rules import clean_serial, cost_per_km_cents, due_status, km_run, valid_position
from app.vehicle_scope import scope_vehicles

router = APIRouter(tags=["tyres"])
READ = ("workshop.manage", "vehicles.view")
WRITE = ("workshop.manage",)


class TyreIn(BaseModel):
    serial: str = Field(min_length=3, max_length=60)
    brand: str = Field(min_length=1, max_length=80)
    size: str = Field(min_length=2, max_length=40)
    cost_cents: int = Field(default=0, ge=0, le=1_000_000_000)
    supplier: str | None = Field(default=None, max_length=120)


class FitIn(BaseModel):
    vehicle_id: uuid.UUID
    position: str
    odometer_km: int | None = Field(default=None, ge=0, le=9_999_999)


class RemoveIn(BaseModel):
    odometer_km: int | None = Field(default=None, ge=0, le=9_999_999)
    scrap: bool = False
    note: str | None = Field(default=None, max_length=255)


class RotateIn(BaseModel):
    position: str
    odometer_km: int | None = Field(default=None, ge=0, le=9_999_999)


class TreadIn(BaseModel):
    tread_mm: Decimal = Field(ge=0, le=30, max_digits=4, decimal_places=1)
    odometer_km: int | None = Field(default=None, ge=0, le=9_999_999)


class RetreadIn(BaseModel):
    cost_cents: int = Field(ge=0, le=1_000_000_000)
    note: str | None = Field(default=None, max_length=255)


class ResolveIn(BaseModel):
    note: str | None = Field(default=None, max_length=255)


def tyre_out(t: Tyre, vehicles: dict[uuid.UUID, Vehicle]) -> dict:
    vehicle = vehicles.get(t.vehicle_id) if t.vehicle_id else None
    fitted = t.status == TyreStatus.FITTED
    odo = vehicle.odometer_km if vehicle else 0
    km = km_run(t.km_before, t.fitted_odometer_km, odo, fitted)
    since = max(0, odo - t.moved_odometer_km) if fitted and t.moved_odometer_km is not None else 0
    total_cost = t.cost_cents + t.retread_cost_cents
    return {
        "id": t.id, "serial": t.serial, "brand": t.brand, "size": t.size, "cost_cents": t.cost_cents,
        "supplier": t.supplier, "status": t.status.value, "vehicle_id": t.vehicle_id,
        "registration": vehicle.registration if vehicle else None, "position": t.position, "fitted_at": t.fitted_at,
        "km_run": km, "retreads": t.retreads, "retread_cost_cents": t.retread_cost_cents,
        "last_tread_mm": float(t.last_tread_mm) if t.last_tread_mm is not None else None, "last_tread_on": t.last_tread_on,
        "cost_per_km_cents": cost_per_km_cents(total_cost, km),
        "due": due_status(fitted=fitted, km=km, since_moved_km=since, tread_mm=t.last_tread_mm),
    }  # fmt: skip


async def _tyre(db: AsyncSession, tyre_id: uuid.UUID) -> Tyre:
    tyre = (await db.execute(select(Tyre).where(Tyre.id == tyre_id))).scalar_one_or_none()
    if tyre is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That tyre was not found.")
    return tyre


async def _vehicles(db: AsyncSession, principal: Principal) -> dict[uuid.UUID, Vehicle]:
    return {v.id: v for v in (await db.execute(scope_vehicles(select(Vehicle), principal))).scalars()}


def _check_position(position: str) -> str:
    position = position.strip().lower()
    if not valid_position(position):
        raise error(422, "bad_position", "That is not a tyre position. Examples: steer_left, drive1_right_inner, trailer1_left_outer, spare.")
    return position


def _event(db: AsyncSession, tyre: Tyre, kind: TyreEventKind, user_id: uuid.UUID, **extra) -> None:
    db.add(TyreEvent(tyre_id=tyre.id, kind=kind, created_by_user_id=user_id, **extra))


def _book_cost(db: AsyncSession, vehicle_id: uuid.UUID | None, amount: int, note: str, user_id: uuid.UUID) -> None:
    """A tyre's cost lands on the vehicle it runs on, so cost per lorry stays right."""
    if amount > 0 and vehicle_id is not None:
        db.add(
            Expense(
                vehicle_id=vehicle_id, category=ExpenseCategory.TYRES, amount_cents=amount, note=note[:255],
                status=ExpenseStatus.RECORDED, spent_at=datetime.now(UTC), created_by_user_id=user_id,
            )
        )  # fmt: skip


def _take_off(tyre: Tyre, odometer_km: int) -> None:
    if tyre.fitted_odometer_km is not None:
        tyre.km_before += max(0, odometer_km - tyre.fitted_odometer_km)
    tyre.last_vehicle_id = tyre.vehicle_id
    tyre.vehicle_id = tyre.position = tyre.fitted_at = tyre.fitted_odometer_km = tyre.moved_odometer_km = None


# ---- Tyres -----------------------------------------------------------------------------------------


@router.get("/tyres")
async def list_tyres(
    status_filter: TyreStatus | None = None,
    vehicle_id: uuid.UUID | None = None,
    principal: Principal = Depends(require_any(*READ)),
    db: AsyncSession = Depends(get_db),
):
    vehicles = await _vehicles(db, principal)
    query = select(Tyre).order_by(Tyre.serial).limit(500)
    if status_filter:
        query = query.where(Tyre.status == status_filter)
    if vehicle_id:
        query = query.where(Tyre.vehicle_id == vehicle_id)
    rows = (await db.execute(query)).scalars().all()
    if principal.vehicle_scope is not None:  # a supervisor sees tyres on their vehicles only
        rows = [t for t in rows if t.vehicle_id in vehicles]
    return [tyre_out(t, vehicles) for t in rows]


@router.post("/tyres", status_code=status.HTTP_201_CREATED)
async def add_tyre(body: TyreIn, principal: Principal = Depends(require_any(*WRITE)), db: AsyncSession = Depends(get_db)):
    serial = clean_serial(body.serial)
    if len(serial) < 3:
        raise error(422, "bad_serial", "Enter the serial number printed on the tyre.")
    tyre = Tyre(serial=serial, brand=body.brand.strip(), size=body.size.strip(), cost_cents=body.cost_cents, supplier=body.supplier)
    db.add(tyre)
    try:
        await db.flush()
    except IntegrityError:
        raise error(status.HTTP_409_CONFLICT, "duplicate_serial", "A tyre with that serial number is already recorded.") from None
    audit.record(db, actor_user_id=principal.user.id, action="tyre.added", entity_type="tyre", entity_id=tyre.id, after={"serial": serial, "brand": tyre.brand})
    await db.commit()
    return tyre_out(tyre, {})


@router.get("/tyres/report")
async def tyre_report(principal: Principal = Depends(require_any(*READ)), db: AsyncSession = Depends(get_db)):
    """Cost per km by brand and by supplier, and the tyres due for rotation or replacement."""
    vehicles = await _vehicles(db, principal)
    rows = [tyre_out(t, vehicles) for t in (await db.execute(select(Tyre).where(Tyre.status != TyreStatus.SCRAPPED))).scalars()]
    if principal.vehicle_scope is not None:
        rows = [r for r in rows if r["vehicle_id"] in vehicles]

    def group(key: str) -> list[dict]:
        buckets: dict[str, dict] = {}
        for r in rows:
            b = buckets.setdefault(r[key] or "Unknown", {"name": r[key] or "Unknown", "tyres": 0, "cost_cents": 0, "km": 0})
            b["tyres"] += 1
            b["cost_cents"] += r["cost_cents"] + r["retread_cost_cents"]
            b["km"] += r["km_run"]
        for b in buckets.values():
            b["cost_per_km_cents"] = cost_per_km_cents(b["cost_cents"], b["km"])
        return sorted(buckets.values(), key=lambda b: b["name"])

    return {
        "by_brand": group("brand"), "by_supplier": group("supplier"),
        "due": [r for r in rows if r["due"]],
    }  # fmt: skip


@router.get("/tyres/{tyre_id}")
async def read_tyre(tyre_id: uuid.UUID, principal: Principal = Depends(require_any(*READ)), db: AsyncSession = Depends(get_db)):
    tyre = await _tyre(db, tyre_id)
    events = (await db.execute(select(TyreEvent).where(TyreEvent.tyre_id == tyre.id).order_by(TyreEvent.occurred_at))).scalars()
    return tyre_out(tyre, await _vehicles(db, principal)) | {
        "history": [
            {"kind": e.kind.value, "vehicle_id": e.vehicle_id, "position": e.position, "odometer_km": e.odometer_km,
             "tread_mm": float(e.tread_mm) if e.tread_mm is not None else None, "cost_cents": e.cost_cents,
             "note": e.note, "occurred_at": e.occurred_at}
            for e in events
        ]
    }  # fmt: skip


@router.get("/vehicles/{vehicle_id}/tyres")
async def vehicle_tyres(vehicle_id: uuid.UUID, principal: Principal = Depends(require_any(*READ)), db: AsyncSession = Depends(get_db)):
    vehicle = await get_vehicle(db, principal, vehicle_id)
    rows = (await db.execute(select(Tyre).where(Tyre.vehicle_id == vehicle.id, Tyre.status == TyreStatus.FITTED).order_by(Tyre.position))).scalars()
    return [tyre_out(t, {vehicle.id: vehicle}) for t in rows]


@router.post("/tyres/{tyre_id}/fit")
async def fit_tyre(tyre_id: uuid.UUID, body: FitIn, principal: Principal = Depends(require_any(*WRITE)), db: AsyncSession = Depends(get_db)):
    tyre = await _tyre(db, tyre_id)
    if tyre.status not in (TyreStatus.IN_STORE, TyreStatus.REMOVED):
        raise error(status.HTTP_409_CONFLICT, "not_available", "That tyre is already fitted or scrapped.")
    position = _check_position(body.position)
    vehicle = await get_vehicle(db, principal, body.vehicle_id)
    taken = (await db.execute(select(Tyre.serial).where(Tyre.vehicle_id == vehicle.id, Tyre.position == position, Tyre.status == TyreStatus.FITTED))).scalar_one_or_none()
    if taken:
        raise error(status.HTTP_409_CONFLICT, "position_taken", f"Tyre {taken} is already fitted at that position. Remove it first.")
    odometer = body.odometer_km if body.odometer_km is not None else vehicle.odometer_km
    tyre.status, tyre.vehicle_id, tyre.position = TyreStatus.FITTED, vehicle.id, position
    tyre.fitted_at, tyre.fitted_odometer_km, tyre.moved_odometer_km = datetime.now(UTC), odometer, odometer
    _event(db, tyre, TyreEventKind.FITTED, principal.user.id, vehicle_id=vehicle.id, position=position, odometer_km=odometer)
    if not tyre.cost_booked:
        _book_cost(db, vehicle.id, tyre.cost_cents, f"Tyre {tyre.serial} ({tyre.brand})", principal.user.id)
        tyre.cost_booked = True
    audit.record(db, actor_user_id=principal.user.id, action="tyre.fitted", entity_type="tyre", entity_id=tyre.id, after={"vehicle_id": str(vehicle.id), "position": position})
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise error(status.HTTP_409_CONFLICT, "position_taken", "Another tyre was just fitted at that position.") from None
    return tyre_out(tyre, {vehicle.id: vehicle})


@router.post("/tyres/{tyre_id}/remove")
async def remove_tyre(tyre_id: uuid.UUID, body: RemoveIn, principal: Principal = Depends(require_any(*WRITE)), db: AsyncSession = Depends(get_db)):
    tyre = await _tyre(db, tyre_id)
    if tyre.status != TyreStatus.FITTED or tyre.vehicle_id is None:
        raise error(status.HTTP_409_CONFLICT, "not_fitted", "That tyre is not on a vehicle.")
    vehicle = await get_vehicle(db, principal, tyre.vehicle_id)
    odometer = body.odometer_km if body.odometer_km is not None else vehicle.odometer_km
    position = tyre.position
    _take_off(tyre, odometer)
    tyre.status = TyreStatus.SCRAPPED if body.scrap else TyreStatus.REMOVED
    kind = TyreEventKind.SCRAPPED if body.scrap else TyreEventKind.REMOVED
    _event(db, tyre, kind, principal.user.id, vehicle_id=vehicle.id, position=position, odometer_km=odometer, note=body.note)
    audit.record(db, actor_user_id=principal.user.id, action="tyre.removed", entity_type="tyre", entity_id=tyre.id, after={"scrapped": body.scrap, "km_run": tyre.km_before})
    await db.commit()
    return tyre_out(tyre, {})


@router.post("/tyres/{tyre_id}/rotate")
async def rotate_tyre(tyre_id: uuid.UUID, body: RotateIn, principal: Principal = Depends(require_any(*WRITE)), db: AsyncSession = Depends(get_db)):
    """Moves a fitted tyre to another position on the same vehicle; a tyre already there swaps places with it."""
    tyre = await _tyre(db, tyre_id)
    if tyre.status != TyreStatus.FITTED or tyre.vehicle_id is None:
        raise error(status.HTTP_409_CONFLICT, "not_fitted", "That tyre is not on a vehicle.")
    vehicle = await get_vehicle(db, principal, tyre.vehicle_id)
    target = _check_position(body.position)
    if target == tyre.position:
        raise error(422, "same_position", "That tyre is already at that position.")
    odometer = body.odometer_km if body.odometer_km is not None else vehicle.odometer_km
    other = (await db.execute(select(Tyre).where(Tyre.vehicle_id == vehicle.id, Tyre.position == target, Tyre.status == TyreStatus.FITTED))).scalar_one_or_none()
    origin = tyre.position
    # Park this tyre first so the unique position index is never broken part way.
    tyre.position = None
    await db.flush()
    if other is not None:
        other.position = origin
        other.moved_odometer_km = odometer
        await db.flush()
        _event(db, other, TyreEventKind.ROTATED, principal.user.id, vehicle_id=vehicle.id, position=origin, odometer_km=odometer)
    tyre.position, tyre.moved_odometer_km = target, odometer
    _event(db, tyre, TyreEventKind.ROTATED, principal.user.id, vehicle_id=vehicle.id, position=target, odometer_km=odometer)
    audit.record(db, actor_user_id=principal.user.id, action="tyre.rotated", entity_type="tyre", entity_id=tyre.id, after={"from": origin, "to": target})
    await db.commit()
    return tyre_out(tyre, {vehicle.id: vehicle})


@router.post("/tyres/{tyre_id}/tread")
async def record_tread(tyre_id: uuid.UUID, body: TreadIn, principal: Principal = Depends(require_any(*WRITE)), db: AsyncSession = Depends(get_db)):
    tyre = await _tyre(db, tyre_id)
    vehicle = await get_vehicle(db, principal, tyre.vehicle_id) if tyre.vehicle_id else None
    odometer = body.odometer_km if body.odometer_km is not None else (vehicle.odometer_km if vehicle else None)
    tyre.last_tread_mm, tyre.last_tread_on = body.tread_mm, nairobi_today()
    _event(db, tyre, TyreEventKind.TREAD, principal.user.id, vehicle_id=tyre.vehicle_id, position=tyre.position, odometer_km=odometer, tread_mm=body.tread_mm)
    await db.commit()
    return tyre_out(tyre, {vehicle.id: vehicle} if vehicle else {})


@router.post("/tyres/{tyre_id}/retread")
async def retread_tyre(tyre_id: uuid.UUID, body: RetreadIn, principal: Principal = Depends(require_any(*WRITE)), db: AsyncSession = Depends(get_db)):
    """A worn tyre that is off the vehicle gets a new tread. The cost goes to the vehicle it last ran on."""
    tyre = await _tyre(db, tyre_id)
    if tyre.status not in (TyreStatus.IN_STORE, TyreStatus.REMOVED):
        raise error(status.HTTP_409_CONFLICT, "still_fitted", "Take the tyre off the vehicle before retreading it.")
    tyre.retreads += 1
    tyre.retread_cost_cents += body.cost_cents
    tyre.last_tread_mm, tyre.last_tread_on = None, None
    tyre.status = TyreStatus.IN_STORE
    _book_cost(db, tyre.last_vehicle_id, body.cost_cents, f"Retread of tyre {tyre.serial}", principal.user.id)
    _event(db, tyre, TyreEventKind.RETREADED, principal.user.id, cost_cents=body.cost_cents, note=body.note)
    audit.record(db, actor_user_id=principal.user.id, action="tyre.retreaded", entity_type="tyre", entity_id=tyre.id, after={"cost_cents": body.cost_cents})
    await db.commit()
    return tyre_out(tyre, {})


# ---- Swap alerts -----------------------------------------------------------------------------------


class SerialIn(BaseModel):
    position: str
    serial: str = Field(min_length=1, max_length=60)


async def check_serials(db: AsyncSession, vehicle: Vehicle, inspection_id: uuid.UUID, serials: list[SerialIn]) -> list[TyreSwapAlert]:
    """Compares the serials a driver read at inspection with the tyres recorded on the vehicle. A difference is a
    possible tyre swap (a good tyre swapped for a worn one); it is flagged, never blocking."""
    fitted = {t.position: t for t in (await db.execute(select(Tyre).where(Tyre.vehicle_id == vehicle.id, Tyre.status == TyreStatus.FITTED))).scalars()}
    known = {t.serial: t for t in (await db.execute(select(Tyre))).scalars()}
    open_alerts = {
        (a.position, a.seen_serial)
        for a in (await db.execute(select(TyreSwapAlert).where(TyreSwapAlert.vehicle_id == vehicle.id, TyreSwapAlert.status == "open"))).scalars()
    }
    raised: list[TyreSwapAlert] = []
    for item in serials:
        position, seen = item.position.strip().lower(), clean_serial(item.serial)
        expected = fitted.get(position)
        if expected is not None and expected.serial == seen:
            continue
        if expected is None and seen in known and known[seen].vehicle_id == vehicle.id:
            reason = "mismatch"  # a tyre of this vehicle, but not recorded at that position
        elif seen in known:
            reason = "elsewhere"  # recorded as in store, scrapped or on another vehicle
        elif expected is not None:
            reason = "unknown"  # a serial we have never seen where a known tyre should be
        else:
            continue  # no record at that position and nothing to compare with
        if (position, seen) in open_alerts:
            continue
        alert = TyreSwapAlert(
            vehicle_id=vehicle.id, inspection_id=inspection_id, position=position,
            expected_serial=expected.serial if expected else None, seen_serial=seen, reason=reason,
        )  # fmt: skip
        db.add(alert)
        raised.append(alert)
    await db.flush()
    return raised


def alert_out(a: TyreSwapAlert, vehicles: dict[uuid.UUID, Vehicle]) -> dict:
    v = vehicles.get(a.vehicle_id)
    return {
        "id": a.id, "vehicle_id": a.vehicle_id, "registration": v.registration if v else None, "position": a.position,
        "expected_serial": a.expected_serial, "seen_serial": a.seen_serial, "reason": a.reason, "status": a.status,
        "created_at": a.created_at, "resolved_at": a.resolved_at, "resolution_note": a.resolution_note,
    }  # fmt: skip


@router.get("/tyre-alerts")
async def list_alerts(open_only: bool = True, principal: Principal = Depends(require_any(*READ)), db: AsyncSession = Depends(get_db)):
    vehicles = await _vehicles(db, principal)
    query = select(TyreSwapAlert).order_by(TyreSwapAlert.created_at.desc()).limit(200)
    if open_only:
        query = query.where(TyreSwapAlert.status == "open")
    return [alert_out(a, vehicles) for a in (await db.execute(query)).scalars() if a.vehicle_id in vehicles]


@router.post("/tyre-alerts/{alert_id}/resolve")
async def resolve_alert(alert_id: uuid.UUID, body: ResolveIn, principal: Principal = Depends(require_any(*WRITE)), db: AsyncSession = Depends(get_db)):
    alert = (await db.execute(select(TyreSwapAlert).where(TyreSwapAlert.id == alert_id))).scalar_one_or_none()
    if alert is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That alert was not found.")
    alert.status, alert.resolved_at, alert.resolved_by_user_id, alert.resolution_note = "resolved", datetime.now(UTC), principal.user.id, body.note
    audit.record(db, actor_user_id=principal.user.id, action="tyre_alert.resolved", entity_type="tyre_swap_alert", entity_id=alert.id, note=body.note)
    await db.commit()
    return alert_out(alert, await _vehicles(db, principal))


@router.get("/me/tyre-positions")
async def my_tyre_positions(principal: Principal = Depends(require("trips.own")), db: AsyncSession = Depends(get_db)):
    """Positions that have a recorded tyre on the driver's vehicle, WITHOUT the serials: the driver reads the serial off
    the tyre, so a swap shows up instead of being copied from the screen."""
    from app.models import CrewAssignment

    assignment = (
        await db.execute(
            select(CrewAssignment).where(CrewAssignment.membership_id == principal.membership_id, CrewAssignment.ended_at.is_(None)).limit(1)
        )
    ).scalar_one_or_none()
    if assignment is None:
        return {"vehicle_id": None, "positions": []}
    rows = (await db.execute(select(Tyre.position).where(Tyre.vehicle_id == assignment.vehicle_id, Tyre.status == TyreStatus.FITTED).order_by(Tyre.position))).scalars()
    return {"vehicle_id": assignment.vehicle_id, "positions": list(rows)}
