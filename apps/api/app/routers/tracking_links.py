"""Client tracking links (masterplan 5.26): a secret, expiring link a client opens to follow one delivery. It shows that delivery's
progress and expected arrival and nothing else (no driver, no other trips), and stops working once the delivery is made."""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.config import settings
from app.db import get_db
from app.deps import Principal, error, require_any
from app.gps_rules import FRESH_SECONDS, eta_minutes, haversine_km
from app.models import (
    Business,
    Client,
    Job,
    LocationPoint,
    SavedRoute,
    TrackingLink,
    Trip,
    TripStatus,
)
from app.phone import normalize_phone
from app.routers.trips import get_trip
from app.security import new_secret_token, sha256
from app.sms import get_sms_sender
from app.tenancy import current_business_id

log = logging.getLogger(__name__)
router = APIRouter(tags=["tracking-links"])
MANAGE = ("trips.manage", "jobs.manage")
ROAD_FACTOR = 1.25  # a road is longer than the straight line to it
STALE_SECONDS = 15 * 60


class LinkIn(BaseModel):
    send_sms: bool = False
    phone: str | None = Field(default=None, max_length=20)  # to text it to; the client's own number is used if left out


def link_url(token: str) -> str:
    return f"{(settings.public_web_url or 'http://localhost:5180').rstrip('/')}/t/{token}"


def link_out(link: TrackingLink) -> dict:
    now = datetime.now(UTC)
    state = "revoked" if link.revoked_at else "expired" if link.expires_at <= now else "active"
    return {"id": link.id, "trip_id": link.trip_id, "created_at": link.created_at, "expires_at": link.expires_at, "state": state, "views": link.views, "last_viewed_at": link.last_viewed_at, "sent_to": link.sent_to}


@router.post("/trips/{trip_id}/tracking-link", status_code=status.HTTP_201_CREATED)
async def create_link(trip_id: uuid.UUID, body: LinkIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    """Makes a link for a trip that has not been delivered yet. The link itself is shown once: only a hash of it is kept."""
    trip = await get_trip(db, principal, trip_id)
    if trip.status not in (TripStatus.SCHEDULED, TripStatus.IN_PROGRESS):
        raise error(status.HTTP_409_CONFLICT, "already_delivered", "That trip has already been delivered, so there is nothing left to follow.")
    token = new_secret_token()
    link = TrackingLink(trip_id=trip.id, token_hash=sha256(token), expires_at=datetime.now(UTC) + timedelta(days=settings.tracking_link_days), created_by_user_id=principal.user.id)
    url = link_url(token)
    if body.send_sms:
        phone = None
        if body.phone:
            phone = normalize_phone(body.phone)
            if phone is None:
                raise error(422, "invalid_phone", "Enter a valid phone number.")
        elif trip.job_id:
            row = (await db.execute(select(Client.phone).join(Job, Job.client_id == Client.id).where(Job.id == trip.job_id))).first()
            phone = row[0] if row else None
        if not phone:
            raise error(422, "no_phone", "The client has no phone number on file. Enter one to send the link to.")
        business = (await db.execute(select(Business).where(Business.id == principal.business_id))).scalar_one()
        await get_sms_sender().send(phone, f"{business.name}: follow your delivery here: {url}")
        link.sent_to = phone
    db.add(link)
    await db.flush()
    audit.record(db, actor_user_id=principal.user.id, action="tracking_link.created", entity_type="trip", entity_id=trip.id, after={"link_id": str(link.id), "sent_to": link.sent_to})
    await db.commit()
    return {**link_out(link), "url": url}


@router.get("/trips/{trip_id}/tracking-links")
async def list_links(trip_id: uuid.UUID, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    trip = await get_trip(db, principal, trip_id)
    return [link_out(link) for link in (await db.execute(select(TrackingLink).where(TrackingLink.trip_id == trip.id).order_by(TrackingLink.created_at.desc()))).scalars()]


@router.delete("/tracking-links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_link(link_id: uuid.UUID, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    link = (await db.execute(select(TrackingLink).where(TrackingLink.id == link_id))).scalar_one_or_none()
    if link is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That link was not found.")
    link.revoked_at = link.revoked_at or datetime.now(UTC)
    audit.record(db, actor_user_id=principal.user.id, action="tracking_link.revoked", entity_type="trip", entity_id=link.trip_id, after={"link_id": str(link.id)})
    await db.commit()


# ---- what the client sees (no sign-in: the secret in the address is the key) ------------------------------------------------


def _gone(code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_410_GONE, content={"detail": {"code": code, "message": message}})


@router.get("/track/{token}")
async def follow(token: str, db: AsyncSession = Depends(get_db)):
    """The client's view of one delivery. Unknown links look the same as wrong ones; ended links say why they ended."""
    link = (await db.execute(select(TrackingLink).where(TrackingLink.token_hash == sha256(token)).execution_options(skip_tenant=True))).scalar_one_or_none()
    if link is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That link is not valid.")
    current_business_id.set(link.business_id)
    now = datetime.now(UTC)
    if link.revoked_at is not None:
        return _gone("revoked", "This link has been switched off.")
    if link.expires_at <= now:
        return _gone("expired", "This link has expired.")
    trip = (await db.execute(select(Trip).where(Trip.id == link.trip_id))).scalar_one()
    if trip.status in (TripStatus.DELIVERED, TripStatus.COMPLETED):
        return _gone("delivered", "This delivery has been made. Thank you.")
    if trip.status == TripStatus.CANCELLED:
        return _gone("cancelled", "This delivery was cancelled.")
    link.views += 1
    link.last_viewed_at = now
    business = (await db.execute(select(Business).where(Business.id == link.business_id))).scalar_one()
    out: dict = {
        "business": business.name, "status": "scheduled" if trip.status == TripStatus.SCHEDULED else "on_the_way", "origin": trip.origin, "destination": trip.destination,
        "cargo": trip.cargo_description, "scheduled_for": trip.scheduled_for, "started_at": trip.started_at, "expected_arrival": trip.planned_end, "position": None,
        "minutes_remaining": None, "progress_pct": None, "as_of": now,
    }  # fmt: skip
    if trip.status == TripStatus.IN_PROGRESS:
        recent = (await db.execute(select(LocationPoint).where(LocationPoint.trip_id == trip.id).order_by(LocationPoint.recorded_at.desc()).limit(20))).scalars().all()
        first = (await db.execute(select(LocationPoint).where(LocationPoint.trip_id == trip.id).order_by(LocationPoint.recorded_at).limit(1))).scalar_one_or_none()
        if recent:
            last = recent[0]
            age = (now - last.recorded_at).total_seconds()
            out["position"] = {"lat": last.lat, "lng": last.lng, "updated_at": last.recorded_at, "stale": age > STALE_SECONDS}
            route = (await db.execute(select(SavedRoute).join(Job, Job.route_id == SavedRoute.id).where(Job.id == trip.job_id))).scalar_one_or_none() if trip.job_id else None
            if route is not None and route.dropoff_lat is not None and route.dropoff_lng is not None:
                remaining = haversine_km(last.lat, last.lng, route.dropoff_lat, route.dropoff_lng) * ROAD_FACTOR
                total = haversine_km(first.lat, first.lng, route.dropoff_lat, route.dropoff_lng) * ROAD_FACTOR if first else remaining
                out["progress_pct"] = max(0, min(100, round(100 * (1 - remaining / total)))) if total > 0 else 100
                if age <= STALE_SECONDS:
                    minutes = eta_minutes(remaining, [p.speed_kmh for p in recent if p.speed_kmh is not None and (now - p.recorded_at).total_seconds() <= FRESH_SECONDS * 3])
                    out["minutes_remaining"] = minutes
                    out["expected_arrival"] = now + timedelta(minutes=minutes) if minutes is not None else out["expected_arrival"]
    await db.commit()
    return out


