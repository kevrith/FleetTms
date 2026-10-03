"""Background jobs for phone GPS: spotting a lorry that has gone quiet in the middle of a trip, and deleting raw location points
after twelve months (masterplan 5.13, 11.3)."""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import alerts, fraud, fuel_prices, tracking
from app.config import settings
from app.db import get_sessionmaker
from app.models import (
    Business,
    LocationPoint,
    Membership,
    MembershipStatus,
    Role,
    TrackerDevice,
    TrackingGap,
    Trip,
    TripStatus,
    Vehicle,
)
from app.sms import get_sms_sender
from app.tenancy import current_business_id

log = logging.getLogger(__name__)


async def notify_managers(db: AsyncSession, message: str) -> int:
    sent = 0
    for m in (await db.execute(select(Membership).where(Membership.status == MembershipStatus.ACTIVE))).scalars():
        if {r.role for r in m.roles} & {Role.OWNER, Role.MANAGER} and m.user.phone:
            await get_sms_sender().send(m.user.phone, message)
            sent += 1
    return sent


async def watch_business(db: AsyncSession, now: datetime | None = None) -> int:
    """Opens a gap (and texts the owner and managers once) for each trip in progress whose phone has not reported for too long, and
    for a trip that started and never reported at all. A gap closes when the next fix arrives. Returns gaps opened."""
    now = now or datetime.now(UTC)
    limit = timedelta(minutes=settings.going_dark_minutes)
    opened = 0
    trips = (await db.execute(select(Trip).where(Trip.status.in_((TripStatus.IN_PROGRESS, TripStatus.DELIVERED)), Trip.started_at.is_not(None)))).scalars().all()
    for trip in trips:
        last = await tracking.last_point_time(db, trip.id)
        quiet_since = last or trip.started_at
        if now - quiet_since <= limit:
            continue
        if (await db.execute(select(TrackingGap.id).where(TrackingGap.trip_id == trip.id, TrackingGap.resolved_at.is_(None)))).first():
            continue
        reg = (await db.execute(select(Vehicle.registration).where(Vehicle.id == trip.vehicle_id))).scalar_one()
        minutes = int((now - quiet_since).total_seconds() // 60)
        business = (await db.execute(select(Business).where(Business.id == current_business_id.get()))).scalar_one()
        text = f"{business.name}: {reg} has not reported its location for {minutes} minutes during a trip." if last else f"{business.name}: {reg} started a trip {minutes} minutes ago and has not reported its location at all."
        gap = TrackingGap(trip_id=trip.id, vehicle_id=trip.vehicle_id, last_seen_at=last, detected_at=now)
        db.add(gap)
        gap.notified = await notify_managers(db, text)
        await db.commit()
        opened += 1
    return opened


async def _each_business(fn) -> int:
    total = 0
    async with get_sessionmaker()() as db:
        business_ids = (await db.execute(select(Business.id))).scalars().all()
    for business_id in business_ids:
        async with get_sessionmaker()() as db:
            current_business_id.set(business_id)
            try:
                total += await fn(db)
            finally:
                current_business_id.set(None)
    return total


async def watch_devices(db: AsyncSession, now: datetime | None = None) -> int:
    """A tracker nobody has heard from for too long is offline: an alert (red if the vehicle is on a trip), the owner and managers
    texted once. It closes itself when the tracker is heard again."""
    now = now or datetime.now(UTC)
    limit = timedelta(minutes=settings.tracker_offline_minutes)
    opened = 0
    for d in (await db.execute(select(TrackerDevice).where(TrackerDevice.is_active.is_(True), TrackerDevice.last_seen_at.is_not(None)))).scalars().all():
        if d.online_state == "offline" or now - d.last_seen_at <= limit:
            continue
        vehicle = (await db.execute(select(Vehicle).where(Vehicle.id == d.vehicle_id))).scalar_one()
        on_trip = (await db.execute(select(Trip.id).where(Trip.vehicle_id == vehicle.id, Trip.status.in_((TripStatus.IN_PROGRESS, TripStatus.DELIVERED))))).first() is not None
        minutes = int((now - d.last_seen_at).total_seconds() // 60)
        d.online_state = "offline"
        if await alerts.raise_alert(db, vehicle, "device_offline", now, device_id=d.id, details={"quiet_minutes": minutes}, severity="red" if on_trip else "amber", text=f"the tracker has not reported for {minutes} minutes."):
            opened += 1
        await db.commit()
    return opened


async def watch_everything(db: AsyncSession) -> int:
    return await watch_business(db) + await watch_devices(db)


async def run_watch() -> int:
    return await _each_business(watch_everything)


async def going_dark_job(ctx: dict) -> int:
    return await run_watch()


async def purge_old_points(now: datetime | None = None) -> int:
    """Deletes raw location points older than the retention period, across every business. Before a trip's points go, its
    distance totals are made sure of, so what remains is the trip's summary (masterplan 11.3)."""
    cutoff = (now or datetime.now(UTC)) - timedelta(days=settings.gps_retention_days)
    async with get_sessionmaker()() as db:
        business_ids = (await db.execute(select(Business.id))).scalars().all()
    for business_id in business_ids:
        async with get_sessionmaker()() as db:
            current_business_id.set(business_id)
            try:
                trip_ids = (await db.execute(select(LocationPoint.trip_id).where(LocationPoint.recorded_at < cutoff, LocationPoint.trip_id.is_not(None)).distinct())).scalars().all()
                for trip in (await db.execute(select(Trip).where(Trip.id.in_(trip_ids), Trip.gps_distance_km.is_(None)))).scalars():
                    await tracking.finalise(db, trip)
                await db.commit()
            finally:
                current_business_id.set(None)
    async with get_sessionmaker()() as db:
        result = await db.execute(delete(LocationPoint).where(LocationPoint.recorded_at < cutoff).execution_options(skip_tenant=True))
        await db.commit()
    removed = result.rowcount or 0
    if removed:
        log.info("Deleted %s location points older than %s days", removed, settings.gps_retention_days)
    return removed


async def gps_retention_job(ctx: dict) -> int:
    return await purge_old_points()


async def run_fraud_sweep() -> int:
    """Every check the fraud engine makes that is not tied to one event, for every business (masterplan 5.13)."""

    async def one(db: AsyncSession) -> int:
        raised = await fraud.sweep(db)
        await db.commit()
        return raised

    return await _each_business(one)


async def fraud_sweep_job(ctx: dict) -> int:
    return await run_fraud_sweep()


async def run_fuel_price_fetch() -> int:
    """Once a day, fetches this month's EPRA prices for any business that has none yet and has a feed to read."""
    if not settings.epra_prices_url:
        return 0

    async def one(db: AsyncSession) -> int:
        try:
            saved = await fuel_prices.fetch_prices(db, only_if_missing=True)
        except fuel_prices.FeedError:
            log.warning("The EPRA price feed could not be read")
            return 0
        await db.commit()
        return saved

    return await _each_business(one)


async def fuel_price_job(ctx: dict) -> int:
    return await run_fuel_price_fetch()
