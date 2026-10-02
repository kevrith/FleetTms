"""Who and what is free when (masterplan 5.17): a lorry in the workshop, or already booked, cannot be dispatched again."""

import uuid
from datetime import datetime, timedelta

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import error
from app.models import Trip, TripStatus, WorkOrder, WorkOrderStatus

DEFAULT_TRIP_HOURS = 12  # how long a booking is assumed to last when the route does not say
BOOKING_STATUSES = (TripStatus.SCHEDULED, TripStatus.IN_PROGRESS, TripStatus.DELIVERED)
IN_WORKSHOP = (WorkOrderStatus.IN_PROGRESS, WorkOrderStatus.WAITING_PARTS)


def trip_window(trip: Trip) -> tuple[datetime, datetime] | None:
    """When a trip occupies its vehicle and crew, or None if it has no time (an unplanned trip blocks nothing)."""
    start = trip.scheduled_for or trip.started_at
    if start is None:
        return None
    end = trip.planned_end or start + timedelta(hours=DEFAULT_TRIP_HOURS)
    if trip.status in (TripStatus.IN_PROGRESS, TripStatus.DELIVERED) and end < datetime.now(start.tzinfo):
        end = datetime.now(start.tzinfo) + timedelta(hours=1)  # still out on the road past its plan
    return start, end


def overlaps(a: tuple[datetime, datetime], b: tuple[datetime, datetime]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


async def workshop_order(db: AsyncSession, vehicle_id: uuid.UUID) -> WorkOrder | None:
    return (
        await db.execute(select(WorkOrder).where(WorkOrder.vehicle_id == vehicle_id, WorkOrder.status.in_(IN_WORKSHOP)).limit(1))
    ).scalars().first()


async def conflicting_trip(
    db: AsyncSession, window: tuple[datetime, datetime], *, vehicle_id: uuid.UUID | None = None,
    membership_id: uuid.UUID | None = None, exclude_trip_id: uuid.UUID | None = None,
) -> Trip | None:
    query = select(Trip).where(Trip.status.in_(BOOKING_STATUSES))
    if vehicle_id is not None:
        query = query.where(Trip.vehicle_id == vehicle_id)
    if membership_id is not None:
        query = query.where((Trip.driver_membership_id == membership_id) | (Trip.turnboy_membership_id == membership_id))
    for trip in (await db.execute(query)).scalars():
        if trip.id == exclude_trip_id:
            continue
        theirs = trip_window(trip)
        if theirs is not None and overlaps(window, theirs):
            return trip
    return None


async def ensure_available(
    db: AsyncSession, vehicle_id: uuid.UUID, crew: list[uuid.UUID], window: tuple[datetime, datetime] | None
) -> None:
    """Raises 409 if the vehicle is in the workshop or the vehicle or anyone in the crew is booked for that time."""
    order = await workshop_order(db, vehicle_id)
    if order is not None:
        raise error(status.HTTP_409_CONFLICT, "in_workshop", f"This vehicle is in the workshop ({order.title}). Finish or cancel that work first.")
    if window is None:
        return
    if await conflicting_trip(db, window, vehicle_id=vehicle_id) is not None:
        raise error(status.HTTP_409_CONFLICT, "vehicle_booked", "This vehicle is already booked for part of that time.")
    for membership_id in crew:
        if await conflicting_trip(db, window, membership_id=membership_id) is not None:
            raise error(status.HTTP_409_CONFLICT, "crew_booked", "The driver or turnboy is already booked for part of that time.")
