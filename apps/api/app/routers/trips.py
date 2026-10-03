import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, tracking
from app.clock import capture_time
from app.db import get_db
from app.deps import Principal, error, require, require_any
from app.invoicing import invoice_for_trip
from app.jobs_service import sync_job
from app.load_rules import overload_kg
from app.models import (
    BillingMethod,
    Client,
    CrewAssignment,
    CrewRole,
    Inspection,
    Job,
    Membership,
    MembershipStatus,
    OdometerReading,
    Photo,
    PhotoKind,
    ProofOfDelivery,
    ReadingPhase,
    Role,
    Trip,
    TripStatus,
    Vehicle,
)
from app.odometer import OdometerError, check_value, reading_flags, trip_distance_km
from app.photos import claim_photo, photo_out
from app.pod import PodIn, confirm_pod, request_code
from app.reminders import NAIROBI
from app.routers.inspections import OK_FOR_TRIP, latest_inspection_on
from app.routers.vehicles import get_vehicle
from app.scheduling import DEFAULT_TRIP_HOURS, ensure_available
from app.trust import flag_summary, trust_out
from app.vehicle_scope import scope_vehicles, vehicle_in_scope

router = APIRouter(tags=["trips"])
ACTIVE = (TripStatus.SCHEDULED, TripStatus.IN_PROGRESS, TripStatus.DELIVERED)
TRIP_FIELDS = ["vehicle_id", "driver_membership_id", "status", "cargo_description", "origin", "destination"]


class TripIn(BaseModel):
    vehicle_id: uuid.UUID
    driver_membership_id: uuid.UUID | None = None  # defaults to the vehicle's current driver
    turnboy_membership_id: uuid.UUID | None = None
    cargo_description: str | None = Field(default=None, max_length=255)
    origin: str | None = Field(default=None, max_length=160)
    destination: str | None = Field(default=None, max_length=160)
    scheduled_for: datetime | None = None


class ReadingIn(BaseModel):
    photo_id: uuid.UUID | None = None
    photo_client_id: uuid.UUID | None = None  # the id the phone gave the photo while offline
    value: int  # what the person confirmed
    auto_read_value: int | None = None  # what the number reader saw, when it ran
    captured_at: datetime | None = None  # when the driver did it; missing means now


class LoadingIn(BaseModel):
    photo_id: uuid.UUID | None = None
    photo_client_id: uuid.UUID | None = None
    loaded_weight_kg: int | None = Field(default=None, gt=0, le=200_000)  # net cargo weight from the weighbridge ticket
    weighbridge_photo_id: uuid.UUID | None = None  # the weighbridge ticket
    weighbridge_photo_client_id: uuid.UUID | None = None
    captured_at: datetime | None = None


class ActionIn(BaseModel):
    captured_at: datetime | None = None
    pod: PodIn | None = None  # proof of delivery, which a trip for a client job must have


def _is_crew(principal: Principal, trip: Trip) -> bool:
    return principal.membership_id is not None and principal.membership_id in (
        trip.driver_membership_id,
        trip.turnboy_membership_id,
    )


async def get_trip(db: AsyncSession, principal: Principal, trip_id: uuid.UUID) -> Trip:
    """A trip the caller may see: managers and supervisors by vehicle scope, crew for their own trips."""
    trip = (await db.execute(select(Trip).where(Trip.id == trip_id))).scalar_one_or_none()
    allowed = trip is not None and (
        ("trips.view" in principal.permissions and vehicle_in_scope(principal, trip.vehicle_id))
        or _is_crew(principal, trip)
    )
    if not allowed:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That trip was not found.")
    return trip


def require_actor(principal: Principal, trip: Trip) -> None:
    """Who may move a trip along: its crew, or a manager acting for them (for example from the web)."""
    manager = "trips.manage" in principal.permissions and vehicle_in_scope(principal, trip.vehicle_id)
    if not (manager or _is_crew(principal, trip)):
        raise error(status.HTTP_403_FORBIDDEN, "not_your_trip", "This is not your trip.")


async def trip_out(db: AsyncSession, trip: Trip) -> dict:
    readings = (await db.execute(select(OdometerReading).where(OdometerReading.trip_id == trip.id))).scalars().all()
    photo_ids = [r.photo_id for r in readings] + ([trip.cargo_photo_id] if trip.cargo_photo_id else [])
    photos = (
        {p.id: p for p in (await db.execute(select(Photo).where(Photo.id.in_(photo_ids)))).scalars()}
        if photo_ids
        else {}
    )
    by_phase = {r.phase: r for r in readings}

    def reading(phase: ReadingPhase) -> dict | None:
        r = by_phase.get(phase)
        return None if r is None else {
            "value": r.confirmed_value, "auto_read_value": r.auto_read_value, "flags": r.flags,
            "photo": photo_out(photos.get(r.photo_id)), "recorded_at": r.created_at,
        }  # fmt: skip

    inspection = None
    if trip.inspection_id:
        i = (await db.execute(select(Inspection).where(Inspection.id == trip.inspection_id))).scalar_one_or_none()
        inspection = None if i is None else {"id": i.id, "status": i.status.value, "performed_at": i.performed_at}
    vehicle = (await db.execute(select(Vehicle).where(Vehicle.id == trip.vehicle_id))).scalar_one_or_none()
    pod = (await db.execute(select(ProofOfDelivery).where(ProofOfDelivery.trip_id == trip.id))).scalar_one_or_none()
    pod_out = None
    if pod is not None:
        ids = [i for i in [pod.cargo_photo_id, pod.note_photo_id, *[uuid.UUID(d) for d in pod.damage_photo_ids]] if i]
        pod_photos = {p.id: p for p in (await db.execute(select(Photo).where(Photo.id.in_(ids)))).scalars()} if ids else {}
        pod_out = {
            "recipient_name": pod.recipient_name, "method": pod.method, "captured_at": pod.captured_at, "flags": pod.flags,
            "has_signature": bool(pod.signature), "lat": pod.lat, "lng": pod.lng, "shortage_qty": float(pod.shortage_qty) if pod.shortage_qty is not None else None,
            "shortage_unit": pod.shortage_unit, "damage_notes": pod.damage_notes,
            "cargo_photo": photo_out(pod_photos.get(pod.cargo_photo_id)), "note_photo": photo_out(pod_photos.get(pod.note_photo_id)),
            "damage_photos": [photo_out(pod_photos[uuid.UUID(d)]) for d in pod.damage_photo_ids if uuid.UUID(d) in pod_photos],
        }  # fmt: skip
    ticket = (await db.execute(select(Photo).where(Photo.id == trip.weighbridge_photo_id))).scalar_one_or_none() if trip.weighbridge_photo_id else None
    job = None
    if trip.job_id:
        row = (await db.execute(select(Job, Client.name).join(Client, Client.id == Job.client_id).where(Job.id == trip.job_id))).first()
        if row is not None:
            j, client_name = row
            job = {
                "id": j.id, "number": j.number, "client_name": client_name, "instructions": j.instructions,
                "pickup_at": j.pickup_at, "deliver_by": j.deliver_by, "trips_planned": j.trips_planned,
                "billing_method": j.billing_method.value,
            }  # fmt: skip
    return {
        "job": job,
        "pod": pod_out,
        "overload_kg": trip.overload_kg,
        "weighbridge_photo": photo_out(ticket),
        "planned_end": trip.planned_end,
        "id": trip.id,
        "status": trip.status.value,
        "vehicle_id": trip.vehicle_id,
        "registration": vehicle.registration if vehicle else None,
        "driver_membership_id": trip.driver_membership_id,
        "turnboy_membership_id": trip.turnboy_membership_id,
        "cargo_description": trip.cargo_description,
        "origin": trip.origin,
        "destination": trip.destination,
        "scheduled_for": trip.scheduled_for,
        "started_at": trip.started_at,
        "loaded_at": trip.loaded_at,
        "loaded_weight_kg": trip.loaded_weight_kg,
        "cargo_photo": photo_out(photos.get(trip.cargo_photo_id)) if trip.cargo_photo_id else None,
        "delivered_at": trip.delivered_at,
        "ended_at": trip.ended_at,
        "distance_km": trip.distance_km,
        "gps_distance_km": trip.gps_distance_km,
        "tracker_distance_km": trip.tracker_distance_km,
        "trust": trust_out(vehicle, (await flag_summary(db, [trip.vehicle_id])).get(trip.vehicle_id, {})) if vehicle else None,
        "distance_detail": trip.distance_detail,
        "distance_check": trip.distance_check,
        "start_reading": reading(ReadingPhase.START),
        "end_reading": reading(ReadingPhase.END),
        "inspection": inspection,
    }


async def _membership_with_role(db: AsyncSession, membership_id: uuid.UUID, role: Role) -> Membership:
    m = (await db.execute(select(Membership).where(Membership.id == membership_id))).scalar_one_or_none()
    if m is None or m.status != MembershipStatus.ACTIVE or role not in {r.role for r in m.roles}:
        raise error(422, "wrong_crew", f"That person is not an active {role.value}.")
    return m


# ---- Creating and finding trips ------------------------------------------------------------------


async def do_create_trip(
    db: AsyncSession, principal: Principal, body: TripIn, *, job_id: uuid.UUID | None = None, hours: float | None = None
) -> Trip:
    """Schedules a trip for a vehicle and its crew. Refuses a vehicle that is in the workshop, and a vehicle or crew
    that is already booked for the time. The caller commits."""
    vehicle = await get_vehicle(db, principal, body.vehicle_id)
    if not vehicle.is_active:
        raise error(status.HTTP_409_CONFLICT, "vehicle_inactive", "This vehicle is not active.")
    crew = {
        c.role: c.membership_id
        for c in (
            await db.execute(
                select(CrewAssignment).where(CrewAssignment.vehicle_id == vehicle.id, CrewAssignment.ended_at.is_(None))
            )
        ).scalars()
    }
    driver_id = body.driver_membership_id or crew.get(CrewRole.DRIVER)
    turnboy_id = body.turnboy_membership_id or crew.get(CrewRole.TURNBOY)
    if driver_id is None:
        raise error(422, "no_driver", "Assign a driver to this vehicle, or choose one for the trip.")
    await _membership_with_role(db, driver_id, Role.DRIVER)
    if turnboy_id is not None:
        await _membership_with_role(db, turnboy_id, Role.TURNBOY)
    planned_end = body.scheduled_for + timedelta(hours=hours or DEFAULT_TRIP_HOURS) if body.scheduled_for else None
    window = (body.scheduled_for, planned_end) if body.scheduled_for and planned_end else None
    await ensure_available(db, vehicle.id, [m for m in (driver_id, turnboy_id) if m], window)

    trip = Trip(
        vehicle_id=vehicle.id, driver_membership_id=driver_id, turnboy_membership_id=turnboy_id,
        cargo_description=body.cargo_description, origin=body.origin, destination=body.destination,
        scheduled_for=body.scheduled_for, planned_end=planned_end, job_id=job_id, created_by_user_id=principal.user.id,
    )  # fmt: skip
    db.add(trip)
    await db.flush()
    audit.record(
        db, actor_user_id=principal.user.id, action="trip.created", entity_type="trip", entity_id=trip.id,
        after=audit.snapshot(trip, TRIP_FIELDS),
    )  # fmt: skip
    await sync_job(db, job_id)
    return trip


@router.post("/trips", status_code=status.HTTP_201_CREATED)
async def create_trip(
    body: TripIn, principal: Principal = Depends(require("trips.manage")), db: AsyncSession = Depends(get_db)
):
    trip = await do_create_trip(db, principal, body)
    await db.commit()
    return await trip_out(db, trip)


@router.get("/trips")
async def list_trips(
    status_filter: TripStatus | None = None,
    vehicle_id: uuid.UUID | None = None,
    limit: int = 50,
    principal: Principal = Depends(require("trips.view")),
    db: AsyncSession = Depends(get_db),
):
    query = select(Trip).order_by(Trip.created_at.desc()).limit(min(max(limit, 1), 200))
    if principal.vehicle_scope is not None:
        visible = scope_vehicles(select(Vehicle.id), principal)
        query = query.where(Trip.vehicle_id.in_(visible))
    if status_filter:
        query = query.where(Trip.status == status_filter)
    if vehicle_id:
        query = query.where(Trip.vehicle_id == vehicle_id)
    return [await trip_out(db, t) for t in (await db.execute(query)).scalars()]


@router.get("/me/trips")
async def my_trips(principal: Principal = Depends(require("trips.own")), db: AsyncSession = Depends(get_db)):
    """The caller's current trips: scheduled, in progress or delivered but not yet closed."""
    if principal.membership_id is None:
        return []
    query = (
        select(Trip)
        .where(
            or_(
                Trip.driver_membership_id == principal.membership_id,
                Trip.turnboy_membership_id == principal.membership_id,
            ),
            Trip.status.in_(ACTIVE),
        )
        .order_by(Trip.scheduled_for.asc().nulls_last(), Trip.created_at)
    )
    return [await trip_out(db, t) for t in (await db.execute(query)).scalars()]


@router.get("/trips/{trip_id}")
async def read_trip(
    trip_id: uuid.UUID, principal: Principal = Depends(require_any("trips.view", "trips.own")), db: AsyncSession = Depends(get_db)
):
    return await trip_out(db, await get_trip(db, principal, trip_id))


# ---- Moving a trip along -------------------------------------------------------------------------


async def _record_reading(
    db: AsyncSession,
    principal: Principal,
    trip: Trip,
    vehicle: Vehicle,
    phase: ReadingPhase,
    body: ReadingIn,
    at: datetime,
) -> tuple[OdometerReading, Photo]:
    try:
        check_value(body.value)
        if body.auto_read_value is not None:
            check_value(body.auto_read_value)
    except OdometerError as exc:
        raise error(422, "invalid_odometer", str(exc)) from None
    if body.value < vehicle.odometer_km:
        # An odometer never goes backwards, so a lower number is refused (not just flagged): it is how kilometres get hidden.
        raise error(
            422, "odometer_backward",
            f"That is lower than this vehicle's last odometer reading ({vehicle.odometer_km:,} km). Check the number. "
            "If the odometer was replaced, a manager can correct the vehicle's reading first.",
        )  # fmt: skip
    photo = await claim_photo(
        db, principal, body.photo_id, PhotoKind.ODOMETER, required=True, client_id=body.photo_client_id, near=at
    )
    assert photo is not None  # required=True
    reading = OdometerReading(
        trip_id=trip.id, vehicle_id=vehicle.id, phase=phase, photo_id=photo.id,
        auto_read_value=body.auto_read_value, confirmed_value=body.value,
        flags=reading_flags(
            body.value, body.auto_read_value, vehicle.odometer_km, has_location=photo.lat is not None and photo.lng is not None
        ),
        recorded_by_user_id=principal.user.id,
    )  # fmt: skip
    db.add(reading)
    return reading, photo


def _not_before_start(trip: Trip, at: datetime) -> None:
    if trip.started_at is not None and at < trip.started_at:
        raise error(422, "time_travel", "That is earlier than when the trip started. Check the phone's clock.")


async def do_start_trip(db: AsyncSession, principal: Principal, trip_id: uuid.UUID, body: ReadingIn) -> Trip:
    """Starts a trip as of the time the driver did it. The caller commits."""
    at = capture_time(body.captured_at)
    trip = await get_trip(db, principal, trip_id)
    require_actor(principal, trip)
    if trip.status != TripStatus.SCHEDULED:
        raise error(status.HTTP_409_CONFLICT, "wrong_status", "This trip has already started.")
    vehicle = await get_vehicle(db, principal, trip.vehicle_id)

    inspection = await latest_inspection_on(db, vehicle.id, at.astimezone(NAIROBI).date())
    if inspection is None:
        raise error(status.HTTP_409_CONFLICT, "inspection_required", "Complete today's pre-trip inspection before starting.")
    if inspection.status not in OK_FOR_TRIP:
        raise error(
            status.HTTP_409_CONFLICT, "inspection_blocked",
            "The inspection found a critical fault. A manager must override it before this trip can start.",
        )  # fmt: skip
    busy = (
        await db.execute(
            select(Trip.id).where(
                Trip.status == TripStatus.IN_PROGRESS,
                or_(Trip.vehicle_id == vehicle.id, Trip.driver_membership_id == trip.driver_membership_id),
                Trip.id != trip.id,
            )
        )
    ).first()
    if busy is not None:
        raise error(status.HTTP_409_CONFLICT, "already_on_trip", "This vehicle or driver is already on another trip.")

    reading, _ = await _record_reading(db, principal, trip, vehicle, ReadingPhase.START, body, at)
    trip.status = TripStatus.IN_PROGRESS
    trip.started_at = at
    trip.inspection_id = inspection.id
    vehicle.odometer_km = max(vehicle.odometer_km, body.value)
    await db.flush()
    audit.record(
        db, actor_user_id=principal.user.id, action="trip.started", entity_type="trip", entity_id=trip.id,
        after={"odometer_km": body.value, "flags": reading.flags, "inspection_id": str(inspection.id)},
    )  # fmt: skip
    await sync_job(db, trip.job_id)
    return trip


async def do_record_loading(db: AsyncSession, principal: Principal, trip_id: uuid.UUID, body: LoadingIn) -> Trip:
    """Records the cargo photo and, from the weighbridge ticket, its weight. It can be done before the lorry leaves, and
    a load over the legal limit is flagged at once. A trip billed per tonne must have the ticket (photo and weight)."""
    at = capture_time(body.captured_at)
    trip = await get_trip(db, principal, trip_id)
    require_actor(principal, trip)
    if trip.status not in (TripStatus.SCHEDULED, TripStatus.IN_PROGRESS):
        raise error(status.HTTP_409_CONFLICT, "wrong_status", "Loading is recorded before the trip leaves or while it is in progress.")
    _not_before_start(trip, at)
    job = (await db.execute(select(Job).where(Job.id == trip.job_id))).scalar_one_or_none() if trip.job_id else None
    per_tonne = job is not None and job.billing_method == BillingMethod.PER_TONNE
    has_ticket = body.weighbridge_photo_id is not None or body.weighbridge_photo_client_id is not None
    if has_ticket and body.loaded_weight_kg is None:
        raise error(422, "weight_required", "Enter the weight printed on the weighbridge ticket.")
    if per_tonne and not (has_ticket and body.loaded_weight_kg):
        raise error(422, "weighbridge_required", "This job is billed per tonne: photograph the weighbridge ticket and enter its weight.")
    photo = await claim_photo(
        db, principal, body.photo_id, PhotoKind.CARGO, required=True, client_id=body.photo_client_id, near=at
    )
    assert photo is not None
    ticket = await claim_photo(
        db, principal, body.weighbridge_photo_id, PhotoKind.WEIGHBRIDGE, required=False,
        client_id=body.weighbridge_photo_client_id, near=at,
    )  # fmt: skip
    trip.cargo_photo_id = photo.id
    trip.weighbridge_photo_id = ticket.id if ticket else None
    trip.loaded_at = at
    trip.loaded_weight_kg = body.loaded_weight_kg
    trip.overload_kg = None
    if body.loaded_weight_kg is not None:
        vehicle = (await db.execute(select(Vehicle).where(Vehicle.id == trip.vehicle_id))).scalar_one()
        trip.overload_kg = overload_kg(
            cargo_kg=body.loaded_weight_kg, tare_kg=vehicle.tare_kg, gvw_limit_kg=vehicle.gvw_limit_kg,
            capacity_tonnes=float(vehicle.capacity_tonnes) if vehicle.capacity_tonnes is not None else None,
        )  # fmt: skip
    audit.record(
        db, actor_user_id=principal.user.id, action="trip.loaded", entity_type="trip", entity_id=trip.id,
        after={"loaded_weight_kg": body.loaded_weight_kg, "overload_kg": trip.overload_kg},
    )  # fmt: skip
    if trip.overload_kg:
        audit.record(db, actor_user_id=principal.user.id, action="trip.overloaded", entity_type="trip", entity_id=trip.id, after={"overload_kg": trip.overload_kg})
    return trip


async def do_mark_delivered(db: AsyncSession, principal: Principal, trip_id: uuid.UUID, body: ActionIn) -> Trip:
    """Marks the cargo as delivered with its proof of delivery. A trip for a client job must have one; confirming it
    invoices the client. The caller commits."""
    at = capture_time(body.captured_at)
    trip = await get_trip(db, principal, trip_id)
    require_actor(principal, trip)
    if trip.status != TripStatus.IN_PROGRESS:
        raise error(status.HTTP_409_CONFLICT, "wrong_status", "Only a trip in progress can be delivered.")
    _not_before_start(trip, at)
    if body.pod is None and trip.job_id is not None:
        raise error(422, "pod_required", "Proof of delivery is needed: the recipient's name, the photos, and a signature or the code.")
    trip.status = TripStatus.DELIVERED
    trip.delivered_at = at
    audit.record(db, actor_user_id=principal.user.id, action="trip.delivered", entity_type="trip", entity_id=trip.id)
    if body.pod is not None:
        await confirm_pod(db, principal, trip, body.pod, at)
        await invoice_for_trip(db, trip, principal.user.id)  # the invoice follows the proof of delivery
    await sync_job(db, trip.job_id)
    return trip


async def do_end_trip(db: AsyncSession, principal: Principal, trip_id: uuid.UUID, body: ReadingIn) -> Trip:
    at = capture_time(body.captured_at)
    trip = await get_trip(db, principal, trip_id)
    require_actor(principal, trip)
    if trip.status not in (TripStatus.IN_PROGRESS, TripStatus.DELIVERED):
        raise error(status.HTTP_409_CONFLICT, "wrong_status", "Only a trip in progress can be ended.")
    _not_before_start(trip, at)
    vehicle = await get_vehicle(db, principal, trip.vehicle_id)
    start = (
        await db.execute(
            select(OdometerReading).where(OdometerReading.trip_id == trip.id, OdometerReading.phase == ReadingPhase.START)
        )
    ).scalar_one()
    try:
        distance = trip_distance_km(start.confirmed_value, check_value(body.value))
    except OdometerError as exc:
        raise error(422, "odometer_backward", str(exc)) from None

    # The vehicle's last known reading is now the start of this trip, so only a jump within the trip is flagged.
    reading, photo = await _record_reading(db, principal, trip, vehicle, ReadingPhase.END, body, at)
    reading.flags = reading_flags(
        body.value, body.auto_read_value, start.confirmed_value,
        has_location=photo.lat is not None and photo.lng is not None,
    )  # fmt: skip
    trip.status = TripStatus.COMPLETED
    trip.ended_at = at
    trip.distance_km = distance
    vehicle.odometer_km = max(vehicle.odometer_km, body.value)
    await db.flush()
    await tracking.finalise(db, trip)  # what the GPS saw, and whether the odometer agrees
    audit.record(
        db, actor_user_id=principal.user.id, action="trip.completed", entity_type="trip", entity_id=trip.id,
        after={"odometer_km": body.value, "distance_km": distance, "flags": reading.flags},
    )  # fmt: skip
    await sync_job(db, trip.job_id)
    return trip


@router.post("/trips/{trip_id}/start")
async def start_trip(
    trip_id: uuid.UUID,
    body: ReadingIn,
    principal: Principal = Depends(require_any("trips.own", "trips.manage")),
    db: AsyncSession = Depends(get_db),
):
    trip = await do_start_trip(db, principal, trip_id, body)
    await db.commit()
    return await trip_out(db, trip)


@router.post("/trips/{trip_id}/loading")
async def record_loading(
    trip_id: uuid.UUID,
    body: LoadingIn,
    principal: Principal = Depends(require_any("trips.own", "trips.manage")),
    db: AsyncSession = Depends(get_db),
):
    trip = await do_record_loading(db, principal, trip_id, body)
    await db.commit()
    return await trip_out(db, trip)


@router.post("/trips/{trip_id}/deliver")
async def mark_delivered(
    trip_id: uuid.UUID,
    body: ActionIn | None = None,
    principal: Principal = Depends(require_any("trips.own", "trips.manage")),
    db: AsyncSession = Depends(get_db),
):
    trip = await do_mark_delivered(db, principal, trip_id, body or ActionIn())
    await db.commit()
    return await trip_out(db, trip)


@router.post("/trips/{trip_id}/pod/code")
async def send_pod_code(
    trip_id: uuid.UUID,
    principal: Principal = Depends(require_any("trips.own", "trips.manage")),
    db: AsyncSession = Depends(get_db),
):
    """Texts the client a one-time delivery code. The recipient gives it to the driver, which proves they received the load."""
    trip = await get_trip(db, principal, trip_id)
    require_actor(principal, trip)
    if trip.status != TripStatus.IN_PROGRESS:
        raise error(status.HTTP_409_CONFLICT, "wrong_status", "A delivery code is sent while the trip is in progress.")
    sent = await request_code(db, principal, trip)
    await db.commit()
    return sent


@router.post("/trips/{trip_id}/end")
async def end_trip(
    trip_id: uuid.UUID,
    body: ReadingIn,
    principal: Principal = Depends(require_any("trips.own", "trips.manage")),
    db: AsyncSession = Depends(get_db),
):
    trip = await do_end_trip(db, principal, trip_id, body)
    await db.commit()
    return await trip_out(db, trip)


@router.post("/trips/{trip_id}/cancel")
async def cancel_trip(
    trip_id: uuid.UUID, principal: Principal = Depends(require("trips.manage")), db: AsyncSession = Depends(get_db)
):
    trip = await get_trip(db, principal, trip_id)
    if trip.status != TripStatus.SCHEDULED:
        raise error(status.HTTP_409_CONFLICT, "wrong_status", "Only a trip that has not started can be cancelled.")
    trip.status = TripStatus.CANCELLED
    audit.record(db, actor_user_id=principal.user.id, action="trip.cancelled", entity_type="trip", entity_id=trip.id)
    await sync_job(db, trip.job_id)
    await db.commit()
    return await trip_out(db, trip)


