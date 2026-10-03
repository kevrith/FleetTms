"""Driving behaviour from fixes (masterplan 5.25). Feeds a vehicle's fixes, in time order, through the shared rules and stores what
they find, with the driver who was on the trip. The rules remember each vehicle between batches. A tracker is preferred to a phone: when
a vehicle's tracker has reported in the last ten minutes, its phone's fixes are not scored, so one hard stop is not counted twice."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import behaviour_rules
from app.models import (
    BehaviourEvent,
    BehaviourState,
    CrewAssignment,
    CrewRole,
    TrackerDevice,
    Trip,
    TripStatus,
)
from app.tenancy import current_business_id

NEAR = timedelta(seconds=5)  # a device alarm and our own reading of the same braking are one event


async def tracker_is_reporting(db: AsyncSession, vehicle_id: uuid.UUID, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    row = (await db.execute(select(TrackerDevice.id).where(TrackerDevice.vehicle_id == vehicle_id, TrackerDevice.is_active.is_(True), TrackerDevice.last_position_at >= now - timedelta(minutes=10)))).first()
    return row is not None


async def driver_at(db: AsyncSession, vehicle_id: uuid.UUID, at: datetime) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """(driver, trip) responsible at a moment: the trip running then, else whoever crews the vehicle now."""
    trip = (
        await db.execute(
            select(Trip).where(Trip.vehicle_id == vehicle_id, Trip.started_at.is_not(None), Trip.started_at <= at, (Trip.ended_at.is_(None)) | (Trip.ended_at >= at), Trip.status.in_((TripStatus.IN_PROGRESS, TripStatus.DELIVERED, TripStatus.COMPLETED)))
            .order_by(Trip.started_at.desc())
        )
    ).scalars().first()  # fmt: skip
    if trip is not None:
        return trip.driver_membership_id, trip.id
    crew = (await db.execute(select(CrewAssignment.membership_id).where(CrewAssignment.vehicle_id == vehicle_id, CrewAssignment.role == CrewRole.DRIVER, CrewAssignment.ended_at.is_(None)))).scalars().first()
    return crew, None


async def record_event(db: AsyncSession, vehicle_id: uuid.UUID, kind: str, at: datetime, *, source: str, ended_at: datetime | None = None, value: float | None = None, limit: float | None = None, lat: float | None = None, lng: float | None = None) -> BehaviourEvent | None:  # fmt: skip
    """Stores one event unless the same thing is already there (same kind within five seconds)."""
    twin = (await db.execute(select(BehaviourEvent.id).where(BehaviourEvent.vehicle_id == vehicle_id, BehaviourEvent.kind == kind, BehaviourEvent.at >= at - NEAR, BehaviourEvent.at <= at + NEAR))).first()
    if twin is not None:
        return None
    driver, trip_id = await driver_at(db, vehicle_id, at)
    stored = (
        await db.execute(
            pg_insert(BehaviourEvent).values(
                id=uuid.uuid4(), business_id=current_business_id.get(), vehicle_id=vehicle_id, driver_membership_id=driver, trip_id=trip_id, kind=kind, at=at, ended_at=ended_at, value=value, limit_value=limit, lat=lat, lng=lng, source=source,
            ).on_conflict_do_nothing(index_elements=["business_id", "vehicle_id", "kind", "at"]).returning(BehaviourEvent.id)
        )
    ).first()  # fmt: skip
    return (await db.execute(select(BehaviourEvent).where(BehaviourEvent.id == stored[0]))).scalar_one() if stored else None


async def feed(db: AsyncSession, vehicle_id: uuid.UUID, fixes: list[dict], *, source: str) -> list[BehaviourEvent]:
    """Runs fixes ({at, speed, heading, ignition, lat, lng}) through the rules, oldest first, and stores what they find."""
    if not fixes:
        return []
    row = (await db.execute(select(BehaviourState).where(BehaviourState.vehicle_id == vehicle_id))).scalar_one_or_none()
    state = (row.state if row else None) or behaviour_rules.new_state()
    stored: list[BehaviourEvent] = []
    for fix in sorted(fixes, key=lambda f: f["at"]):
        state, events = behaviour_rules.step(state, fix)
        for e in events:
            made = await record_event(db, vehicle_id, e["kind"], e["at"], source=source, ended_at=e.get("ended_at"), value=e.get("value"), limit=e.get("limit"), lat=e.get("lat"), lng=e.get("lng"))
            if made is not None:
                stored.append(made)
    if row is None:
        db.add(BehaviourState(vehicle_id=vehicle_id, state=state))
    else:
        row.state, row.updated_at = state, datetime.now(UTC)
    await db.flush()
    return stored
