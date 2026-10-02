"""Jobs, dispatch and the availability calendar (masterplan 5.17). A job comes from an accepted quote, is set up directly,
or repeats an earlier one (reusing the client's saved route). Dispatching it creates a trip for a free lorry and crew, and
the driver is told."""

import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.db import get_db
from app.deps import Principal, error, require_any
from app.floatcalc import day_bounds
from app.models import (
    BillingMethod,
    Client,
    Job,
    JobStatus,
    Membership,
    MembershipStatus,
    Quote,
    Role,
    SavedRoute,
    Trip,
    TripStatus,
    Vehicle,
    WorkOrder,
)
from app.numbering import create_numbered
from app.reminders import NAIROBI, nairobi_today
from app.routers.quotes import QuoteIn, resolve
from app.routers.trips import TripIn, do_create_trip, trip_out
from app.scheduling import (
    BOOKING_STATUSES,
    DEFAULT_TRIP_HOURS,
    IN_WORKSHOP,
    conflicting_trip,
    overlaps,
    trip_window,
    workshop_order,
)
from app.sms import get_sms_sender
from app.vehicle_scope import scope_vehicles

router = APIRouter(tags=["jobs"])
log = logging.getLogger(__name__)
MONEY = ("clients.manage", "jobs.manage")
MANAGE = ("jobs.manage",)
VIEW = ("trips.view", "jobs.manage")
MAX_CALENDAR_DAYS = 31
OPEN = (JobStatus.PLANNED, JobStatus.DISPATCHED, JobStatus.IN_PROGRESS)


class JobIn(BaseModel):
    client_id: uuid.UUID
    route_id: uuid.UUID | None = None
    cargo_description: str | None = Field(default=None, max_length=255)
    weight_tonnes: Decimal = Field(default=Decimal(0), ge=0, le=1000, decimal_places=2)
    trips: int = Field(default=1, ge=1, le=500)
    billing_method: BillingMethod | None = None
    rate_cents: int | None = Field(default=None, ge=0, le=10_000_000_000)
    pickup_at: datetime | None = None
    deliver_by: datetime | None = None
    instructions: str | None = Field(default=None, max_length=2000)


class JobUpdate(BaseModel):
    cargo_description: str | None = Field(default=None, max_length=255)
    pickup_at: datetime | None = None
    deliver_by: datetime | None = None
    instructions: str | None = Field(default=None, max_length=2000)


class RepeatIn(BaseModel):
    pickup_at: datetime | None = None
    deliver_by: datetime | None = None


class DispatchIn(BaseModel):
    vehicle_id: uuid.UUID
    driver_membership_id: uuid.UUID | None = None  # the vehicle's own crew unless set
    turnboy_membership_id: uuid.UUID | None = None
    scheduled_for: datetime


async def job_from_quote(db: AsyncSession, principal: Principal, q: Quote) -> Job:
    return await create_numbered(
        db, Job, "J", client_id=q.client_id, quote_id=q.id, route_id=q.route_id, cargo_description=q.cargo_description,
        weight_tonnes=q.weight_tonnes, trips_planned=q.trips, billing_method=q.billing_method, rate_cents=q.rate_cents,
        price_cents=q.price_cents, expected_profit_cents=q.expected_profit_cents, pickup_at=q.pickup_at,
        deliver_by=q.deliver_by, instructions=q.instructions, created_by_user_id=principal.user.id,
    )  # fmt: skip


async def job_out(db: AsyncSession, principal: Principal, j: Job, *, detail: bool = True) -> dict:
    client = (await db.execute(select(Client).where(Client.id == j.client_id))).scalar_one_or_none()
    route = (await db.execute(select(SavedRoute).where(SavedRoute.id == j.route_id))).scalar_one_or_none() if j.route_id else None
    trips = (await db.execute(select(Trip).where(Trip.job_id == j.id).order_by(Trip.scheduled_for))).scalars().all()
    live = [t for t in trips if t.status != TripStatus.CANCELLED]
    names = {m.id: m.user.name for m in (await db.execute(select(Membership))).scalars()} if detail else {}
    plates = {v.id: v.registration for v in (await db.execute(select(Vehicle))).scalars()} if detail else {}
    out = {
        "id": j.id, "number": j.number, "client_id": j.client_id, "client_name": client.name if client else None,
        "quote_id": j.quote_id, "repeat_of_id": j.repeat_of_id, "route_id": j.route_id,
        "route": {"id": route.id, "name": route.name, "pickup": route.pickup, "dropoff": route.dropoff, "distance_km": route.distance_km} if route else None,
        "cargo_description": j.cargo_description, "weight_tonnes": float(j.weight_tonnes), "trips_planned": j.trips_planned,
        "trips_dispatched": len(live), "trips_completed": sum(1 for t in live if t.status == TripStatus.COMPLETED),
        "billing_method": j.billing_method.value, "pickup_at": j.pickup_at, "deliver_by": j.deliver_by,
        "instructions": j.instructions, "status": j.status.value, "created_at": j.created_at, "completed_at": j.completed_at,
    }  # fmt: skip
    if any(p in principal.permissions for p in MONEY):
        out |= {"rate_cents": j.rate_cents, "price_cents": j.price_cents, "expected_profit_cents": j.expected_profit_cents}
    if detail:
        out["trips"] = [
            {"id": t.id, "status": t.status.value, "scheduled_for": t.scheduled_for, "planned_end": t.planned_end,
             "vehicle_id": t.vehicle_id, "registration": plates.get(t.vehicle_id), "driver_name": names.get(t.driver_membership_id),
             "distance_km": t.distance_km}
            for t in trips
        ]  # fmt: skip
    return out


async def _get(db: AsyncSession, job_id: uuid.UUID) -> Job:
    job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none()
    if job is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That job was not found.")
    return job


def _quote_in(body: JobIn) -> QuoteIn:
    return QuoteIn(
        client_id=body.client_id, route_id=body.route_id, cargo_description=body.cargo_description, weight_tonnes=body.weight_tonnes,
        trips=body.trips, billing_method=body.billing_method, rate_cents=body.rate_cents, pickup_at=body.pickup_at,
        deliver_by=body.deliver_by, instructions=body.instructions,
    )  # fmt: skip


@router.get("/jobs")
async def list_jobs(
    status_filter: JobStatus | None = None, client_id: uuid.UUID | None = None, open_only: bool = False,
    principal: Principal = Depends(require_any(*VIEW)), db: AsyncSession = Depends(get_db),
):
    query = select(Job).order_by(Job.created_at.desc()).limit(300)
    if status_filter:
        query = query.where(Job.status == status_filter)
    if open_only:
        query = query.where(Job.status.in_(OPEN))
    if client_id:
        query = query.where(Job.client_id == client_id)
    return [await job_out(db, principal, j, detail=False) for j in (await db.execute(query)).scalars()]


@router.post("/jobs", status_code=status.HTTP_201_CREATED)
async def create_job(body: JobIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    """A job without a quote: a contract job, or work agreed over the phone."""
    fields, _ = await resolve(db, _quote_in(body), strict=False)
    if fields["rate_cents"] <= 0:
        raise error(422, "rate_required", "Set a rate: on the client, or on this job.")
    job = await create_numbered(
        db, Job, "J", client_id=fields["client_id"], route_id=fields["route_id"], cargo_description=body.cargo_description,
        weight_tonnes=body.weight_tonnes, trips_planned=body.trips, billing_method=fields["billing_method"], rate_cents=fields["rate_cents"],
        price_cents=fields["price_cents"], expected_profit_cents=fields["expected_profit_cents"], pickup_at=body.pickup_at,
        deliver_by=body.deliver_by, instructions=body.instructions, created_by_user_id=principal.user.id,
    )  # fmt: skip
    audit.record(db, actor_user_id=principal.user.id, action="job.created", entity_type="job", entity_id=job.id, after={"number": job.number})
    await db.commit()
    return await job_out(db, principal, job)


@router.get("/jobs/{job_id}")
async def read_job(job_id: uuid.UUID, principal: Principal = Depends(require_any(*VIEW)), db: AsyncSession = Depends(get_db)):
    return await job_out(db, principal, await _get(db, job_id))


@router.put("/jobs/{job_id}")
async def update_job(job_id: uuid.UUID, body: JobUpdate, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    job = await _get(db, job_id)
    if job.status in (JobStatus.COMPLETED, JobStatus.CANCELLED):
        raise error(status.HTTP_409_CONFLICT, "closed", "That job is already closed.")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(job, field, value)
    audit.record(db, actor_user_id=principal.user.id, action="job.updated", entity_type="job", entity_id=job.id)
    await db.commit()
    return await job_out(db, principal, job)


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: uuid.UUID, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    job = await _get(db, job_id)
    started = (await db.execute(select(Trip.id).where(Trip.job_id == job.id, Trip.status.in_((TripStatus.IN_PROGRESS, TripStatus.DELIVERED, TripStatus.COMPLETED))).limit(1))).first()
    if started is not None or job.status in (JobStatus.COMPLETED, JobStatus.CANCELLED):
        raise error(status.HTTP_409_CONFLICT, "cannot_cancel", "A job with trips under way or finished cannot be cancelled.")
    for trip in (await db.execute(select(Trip).where(Trip.job_id == job.id, Trip.status == TripStatus.SCHEDULED))).scalars():
        trip.status = TripStatus.CANCELLED  # frees the lorry and crew
    job.status = JobStatus.CANCELLED
    audit.record(db, actor_user_id=principal.user.id, action="job.cancelled", entity_type="job", entity_id=job.id)
    await db.commit()
    return await job_out(db, principal, job)


@router.post("/jobs/{job_id}/repeat", status_code=status.HTTP_201_CREATED)
async def repeat_job(job_id: uuid.UUID, body: RepeatIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    """The same job again: same client, cargo, billing and saved route, new dates."""
    old = await _get(db, job_id)
    job = await create_numbered(
        db, Job, "J", client_id=old.client_id, route_id=old.route_id, repeat_of_id=old.id, cargo_description=old.cargo_description,
        weight_tonnes=old.weight_tonnes, trips_planned=old.trips_planned, billing_method=old.billing_method, rate_cents=old.rate_cents,
        price_cents=old.price_cents, expected_profit_cents=old.expected_profit_cents, pickup_at=body.pickup_at, deliver_by=body.deliver_by,
        instructions=old.instructions, created_by_user_id=principal.user.id,
    )  # fmt: skip
    audit.record(db, actor_user_id=principal.user.id, action="job.repeated", entity_type="job", entity_id=job.id, after={"from": old.number})
    await db.commit()
    return await job_out(db, principal, job)


async def _tell_driver(db: AsyncSession, membership_id: uuid.UUID | None, job: Job, client_name: str, route: SavedRoute | None, when: datetime) -> None:
    member = (await db.execute(select(Membership).where(Membership.id == membership_id))).scalar_one_or_none() if membership_id else None
    if member is None or not member.user.phone:
        return
    where = f" {route.pickup} to {route.dropoff}." if route else ""
    text = f"FleetTms: new job {job.number} for {client_name}.{where} {when.astimezone(NAIROBI).strftime('%a %d %b %H:%M')}. Open the app for details."
    try:
        await get_sms_sender().send(member.user.phone, text)
    except Exception:
        log.exception("Could not text the driver about job %s", job.number)  # they still see it in the app


@router.post("/jobs/{job_id}/dispatch", status_code=status.HTTP_201_CREATED)
async def dispatch(job_id: uuid.UUID, body: DispatchIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    """Assigns one trip of the job to a free lorry and crew. The driver sees it on their phone and is texted."""
    job = await _get(db, job_id)
    if job.status in (JobStatus.COMPLETED, JobStatus.CANCELLED):
        raise error(status.HTTP_409_CONFLICT, "closed", "That job is closed.")
    live = (await db.execute(select(Trip).where(Trip.job_id == job.id, Trip.status != TripStatus.CANCELLED))).scalars().all()
    if len(live) >= job.trips_planned:
        raise error(status.HTTP_409_CONFLICT, "fully_dispatched", f"All {job.trips_planned} trip(s) of this job already have a lorry.")
    route = (await db.execute(select(SavedRoute).where(SavedRoute.id == job.route_id))).scalar_one_or_none() if job.route_id else None
    client = (await db.execute(select(Client).where(Client.id == job.client_id))).scalar_one()
    trip = await do_create_trip(
        db, principal,
        TripIn(
            vehicle_id=body.vehicle_id, driver_membership_id=body.driver_membership_id, turnboy_membership_id=body.turnboy_membership_id,
            cargo_description=job.cargo_description, origin=route.pickup if route else None, destination=route.dropoff if route else None,
            scheduled_for=body.scheduled_for,
        ),
        job_id=job.id, hours=route.expected_hours if route else None,
    )  # fmt: skip
    audit.record(db, actor_user_id=principal.user.id, action="job.dispatched", entity_type="job", entity_id=job.id, after={"trip_id": str(trip.id), "vehicle_id": str(trip.vehicle_id)})
    await db.commit()
    await _tell_driver(db, trip.driver_membership_id, job, client.name, route, body.scheduled_for)
    return await job_out(db, principal, job) | {"trip": await trip_out(db, trip)}


# ---- Dispatch calendar -----------------------------------------------------------------------------


def _day_status(day: date, bookings: list[Trip], in_service: bool, today: date) -> str:
    start, end = day_bounds(day)
    if in_service and day >= today:
        return "in_service"
    for t in bookings:
        window = trip_window(t)
        if window and overlaps((start, end), window):
            return "booked"
    return "free"


@router.get("/dispatch/calendar")
async def calendar(
    from_: date | None = Query(default=None, alias="from"), to: date | None = None,
    principal: Principal = Depends(require_any(*VIEW)), db: AsyncSession = Depends(get_db),
):
    """Every lorry and crew member, day by day: free, booked, or in service."""
    start = from_ or nairobi_today()
    end = to or start + timedelta(days=13)
    if end < start or (end - start).days >= MAX_CALENDAR_DAYS:
        raise error(422, "bad_range", f"Choose a range of up to {MAX_CALENDAR_DAYS} days.")
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    today = nairobi_today()
    vehicles = (await db.execute(scope_vehicles(select(Vehicle).where(Vehicle.is_active.is_(True)).order_by(Vehicle.registration), principal))).scalars().all()
    trips = (await db.execute(select(Trip).where(Trip.status.in_(BOOKING_STATUSES)))).scalars().all()
    jobs = {j.id: j for j in (await db.execute(select(Job))).scalars()}
    clients = {c.id: c.name for c in (await db.execute(select(Client))).scalars()}
    orders = {}
    for wo in (await db.execute(select(WorkOrder).where(WorkOrder.status.in_(IN_WORKSHOP)))).scalars():
        orders.setdefault(wo.vehicle_id, wo)
    members = {m.id: m for m in (await db.execute(select(Membership).where(Membership.status == MembershipStatus.ACTIVE))).scalars()}
    range_window = (day_bounds(start)[0], day_bounds(end)[1])

    def booking(t: Trip) -> dict:
        w = trip_window(t)
        j = jobs.get(t.job_id)
        return {
            "trip_id": t.id, "job_id": t.job_id, "job_number": j.number if j else None, "client_name": clients.get(j.client_id) if j else None,
            "from": w[0], "to": w[1], "status": t.status.value, "route": f"{t.origin} to {t.destination}" if t.origin and t.destination else None,
            "driver_name": members[t.driver_membership_id].user.name if t.driver_membership_id in members else None,
        }  # fmt: skip

    def mine(*, vehicle: uuid.UUID | None = None, person: uuid.UUID | None = None) -> list[Trip]:
        return [
            t for t in trips
            if ((vehicle is not None and t.vehicle_id == vehicle) or (person is not None and person in (t.driver_membership_id, t.turnboy_membership_id)))
            and (w := trip_window(t)) is not None and overlaps(range_window, w)
        ]  # fmt: skip

    out_vehicles = []
    for v in vehicles:
        booked = mine(vehicle=v.id)
        wo = orders.get(v.id)
        out_vehicles.append({
            "id": v.id, "registration": v.registration, "in_service": wo is not None,
            "service": {"work_order_id": wo.id, "title": wo.title, "status": wo.status.value} if wo else None,
            "bookings": [booking(t) for t in booked],
            "days": [{"date": d, "status": _day_status(d, booked, wo is not None, today)} for d in days],
        })  # fmt: skip
    crew = []
    for m in members.values():
        roles = {r.role for r in m.roles}
        if not roles & {Role.DRIVER, Role.TURNBOY} or (principal.vehicle_scope is not None):
            continue
        booked = mine(person=m.id)
        crew.append({
            "membership_id": m.id, "name": m.user.name, "role": "driver" if Role.DRIVER in roles else "turnboy",
            "bookings": [booking(t) for t in booked], "days": [{"date": d, "status": _day_status(d, booked, False, today)} for d in days],
        })  # fmt: skip
    return {"from": start, "to": end, "vehicles": out_vehicles, "crew": sorted(crew, key=lambda c: c["name"])}


@router.get("/dispatch/available")
async def available(
    start: datetime, hours: float = Query(default=DEFAULT_TRIP_HOURS, gt=0, le=240),
    principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db),
):
    """Who can take a trip that starts at `start` and runs for `hours`: the lorries and crew that are free for the whole time."""
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    window = (start, start + timedelta(hours=hours))
    vehicles = []
    for v in (await db.execute(scope_vehicles(select(Vehicle).where(Vehicle.is_active.is_(True)).order_by(Vehicle.registration), principal))).scalars():
        reason = None
        if await workshop_order(db, v.id) is not None:
            reason = "in_workshop"
        elif await conflicting_trip(db, window, vehicle_id=v.id) is not None:
            reason = "booked"
        vehicles.append({"id": v.id, "registration": v.registration, "free": reason is None, "reason": reason})
    crew = []
    for m in (await db.execute(select(Membership).where(Membership.status == MembershipStatus.ACTIVE))).scalars():
        roles = {r.role for r in m.roles}
        if roles & {Role.DRIVER, Role.TURNBOY}:
            booked = await conflicting_trip(db, window, membership_id=m.id) is not None
            crew.append({"membership_id": m.id, "name": m.user.name, "role": "driver" if Role.DRIVER in roles else "turnboy", "free": not booked, "reason": "booked" if booked else None})
    return {"vehicles": vehicles, "crew": sorted(crew, key=lambda c: c["name"])}
