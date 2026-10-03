"""Phone GPS ingestion (masterplan 5.3): the crew's phone sends the fixes it took during a trip, in batches."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import tracking
from app.config import settings
from app.db import get_db
from app.deps import Principal, error, require_any
from app.models import LocationPoint, Trip, TripStatus
from app.reminders import NAIROBI
from app.routers.trips import _is_crew

router = APIRouter(tags=["locations"])


class PointIn(BaseModel):
    recorded_at: datetime
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    speed_kmh: float | None = Field(default=None, ge=0, le=400)
    heading: float | None = Field(default=None, ge=0, le=360)
    accuracy_m: float | None = Field(default=None, ge=0, le=100_000)

    @field_validator("recorded_at")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("The time of a fix must say its time zone.")
        return v


class BatchIn(BaseModel):
    points: list[PointIn] = Field(min_length=1)


@router.post("/trips/{trip_id}/locations")
async def send_locations(trip_id: uuid.UUID, body: BatchIn, principal: Principal = Depends(require_any("trips.own")), db: AsyncSession = Depends(get_db)):
    """The crew's phone reports where the lorry has been. Only the trip's own crew may, only while the trip runs: a fix from before it
    started or after it ended is refused. Sending the same fix again is harmless."""
    if len(body.points) > settings.max_points_per_batch:
        raise error(422, "too_many_points", f"Send at most {settings.max_points_per_batch} locations at a time.")
    trip = (await db.execute(select(Trip).where(Trip.id == trip_id))).scalar_one_or_none()
    if trip is None or not _is_crew(principal, trip):
        raise error(404, "not_found", "That trip was not found.")
    try:
        result = await tracking.ingest(db, trip, principal.user.id, [p.model_dump() for p in body.points])
    except tracking.TrackingError as e:
        raise error(409, e.code, e.message) from None
    await db.commit()
    return {"accepted": result.accepted, "duplicate": result.duplicate, "rejected": result.rejected, "tracking": trip.ended_at is None}


@router.get("/me/tracking")
async def my_tracking(principal: Principal = Depends(require_any("trips.own")), db: AsyncSession = Depends(get_db)):
    """What the driver can check about their own tracking: whether it is on, when it last reported, and how it is kept."""
    trip = (
        await db.execute(
            select(Trip).where(Trip.status.in_((TripStatus.IN_PROGRESS, TripStatus.DELIVERED)), (Trip.driver_membership_id == principal.membership_id) | (Trip.turnboy_membership_id == principal.membership_id))
        )
    ).scalars().first()  # fmt: skip
    last = await tracking.last_point_time(db, trip.id) if trip else None
    today = datetime.now(NAIROBI).replace(hour=0, minute=0, second=0, microsecond=0)
    count = (
        await db.execute(select(func.count()).select_from(LocationPoint).where(LocationPoint.user_id == principal.user.id, LocationPoint.recorded_at >= today))
    ).scalar_one()
    return {"tracking": trip is not None, "trip_id": trip.id if trip else None, "last_fix_at": last, "fixes_today": int(count), "retention_days": settings.gps_retention_days}
