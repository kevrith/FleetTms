import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, fraud, mpesa
from app.clock import capture_time
from app.db import get_db
from app.deps import Principal, error, require, require_any
from app.models import FuelEntry, PhotoKind, Trip, TripStatus
from app.photos import claim_photo
from app.routers.inspections import can_act_on_vehicle
from app.routers.vehicles import get_vehicle
from app.vehicle_scope import scope_vehicles

router = APIRouter(tags=["fuel"])
FIELDS = ["vehicle_id", "trip_id", "litres", "price_per_litre_cents", "amount_cents", "station", "mpesa_code"]


class FuelIn(BaseModel):
    vehicle_id: uuid.UUID
    trip_id: uuid.UUID | None = None  # the vehicle's trip running at that moment is used when left out
    litres: Decimal = Field(gt=0, le=2000, decimal_places=2)
    price_per_litre_cents: int = Field(gt=0, le=100_000)
    amount_cents: int = Field(gt=0, le=100_000_000)
    station: str | None = Field(default=None, max_length=120)
    mpesa_code: str | None = None
    receipt_photo_id: uuid.UUID | None = None
    receipt_photo_client_id: uuid.UUID | None = None
    client_id: uuid.UUID | None = None  # chosen by the phone, so a retried entry is stored once
    captured_at: datetime | None = None


def fuel_out(f: FuelEntry) -> dict:
    return {
        "id": f.id, "vehicle_id": f.vehicle_id, "trip_id": f.trip_id, "litres": f.litres,
        "price_per_litre_cents": f.price_per_litre_cents, "amount_cents": f.amount_cents, "station": f.station,
        "mpesa_code": f.mpesa_code, "has_receipt": f.receipt_photo_id is not None, "flags": f.flags,
        "captured_at": f.captured_at, "client_id": f.client_id,
    }  # fmt: skip


async def do_add_fuel(db: AsyncSession, principal: Principal, body: FuelIn) -> tuple[FuelEntry, bool]:
    """Records a fuel purchase. Returns (entry, created); a repeat of the same client_id returns the first one."""
    if body.client_id is not None:
        again = (await db.execute(select(FuelEntry).where(FuelEntry.client_id == body.client_id))).scalar_one_or_none()
        if again is not None:
            return again, False
    at = capture_time(body.captured_at)
    vehicle = await get_vehicle(db, principal, body.vehicle_id)
    if not await can_act_on_vehicle(db, principal, vehicle):
        raise error(status.HTTP_403_FORBIDDEN, "not_your_vehicle", "You are not assigned to this vehicle.")
    trip_id = body.trip_id
    if trip_id is not None:
        trip = (await db.execute(select(Trip).where(Trip.id == trip_id))).scalar_one_or_none()
        if trip is None or trip.vehicle_id != vehicle.id:
            raise error(422, "wrong_trip", "That trip is not for this vehicle.")
    else:
        # Fuel bought while a trip was running belongs to it, whoever types it in and whenever it is entered; otherwise it is the
        # vehicle's own cost and never reaches the client or driver profit rows.
        trip_id = (
            await db.execute(
                select(Trip.id)
                .where(
                    Trip.vehicle_id == vehicle.id, Trip.started_at.is_not(None), Trip.started_at <= at,
                    Trip.ended_at.is_(None) | (Trip.ended_at >= at),
                    Trip.status.in_((TripStatus.IN_PROGRESS, TripStatus.DELIVERED, TripStatus.COMPLETED)),
                )
                .order_by(Trip.started_at.desc())
            )
        ).scalars().first()  # fmt: skip
    try:
        code = mpesa.tidy(body.mpesa_code)
    except ValueError as exc:
        raise error(422, "invalid_mpesa_code", str(exc)) from None
    if code and await mpesa.taken(db, code):
        await fraud.duplicate_mpesa(db, code=code, user_id=principal.user.id, vehicle_id=vehicle.id)
        await db.commit()  # the claim is refused, but the owner is told someone tried
        raise error(status.HTTP_409_CONFLICT, "duplicate_mpesa_code", "That M-Pesa code was already claimed.")

    receipt = await claim_photo(
        db, principal, body.receipt_photo_id, PhotoKind.RECEIPT, required=False,
        client_id=body.receipt_photo_client_id, near=at,
    )  # fmt: skip
    flags = []
    expected = body.litres * body.price_per_litre_cents
    if abs(expected - body.amount_cents) > max(Decimal(100), Decimal(body.amount_cents) / 100):
        flags.append("amount_mismatch")  # litres times price is not the amount paid
    if receipt is None:
        flags.append("no_receipt")
    entry = FuelEntry(
        vehicle_id=vehicle.id, trip_id=trip_id, litres=body.litres, price_per_litre_cents=body.price_per_litre_cents,
        amount_cents=body.amount_cents, station=body.station, mpesa_code=code,
        receipt_photo_id=receipt.id if receipt else None, flags=flags, client_id=body.client_id, captured_at=at,
        recorded_by_user_id=principal.user.id,
    )  # fmt: skip
    db.add(entry)
    try:
        await db.flush()
    except IntegrityError:
        raise error(status.HTTP_409_CONFLICT, "duplicate_fuel_entry", "That fuel entry was already recorded.") from None
    audit.record(
        db, actor_user_id=principal.user.id, action="fuel.added", entity_type="fuel_entry", entity_id=entry.id,
        after=audit.snapshot(entry, FIELDS) | {"flags": flags},
    )  # fmt: skip
    return entry, True


@router.post("/fuel", status_code=status.HTTP_201_CREATED)
async def add_fuel(
    body: FuelIn,
    principal: Principal = Depends(require_any("trips.own", "trips.manage")),
    db: AsyncSession = Depends(get_db),
):
    entry, _ = await do_add_fuel(db, principal, body)
    await db.commit()
    return fuel_out(entry)


@router.get("/fuel")
async def list_fuel(
    vehicle_id: uuid.UUID | None = None,
    limit: int = 100,
    principal: Principal = Depends(require("vehicles.view")),
    db: AsyncSession = Depends(get_db),
):
    from app.models import Vehicle

    query = select(FuelEntry).order_by(FuelEntry.captured_at.desc()).limit(min(max(limit, 1), 500))
    if principal.vehicle_scope is not None:
        query = query.where(FuelEntry.vehicle_id.in_(scope_vehicles(select(Vehicle.id), principal)))
    if vehicle_id:
        query = query.where(FuelEntry.vehicle_id == vehicle_id)
    return [fuel_out(f) for f in (await db.execute(query)).scalars()]
