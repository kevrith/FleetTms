"""Client sites: where a client takes deliveries. A site is added by the office, or saved by a driver from the place they
delivered to. What a driver saves guides the next driver but is not held against anyone until the office confirms it."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.deps import Principal
from app.geo import distance_m
from app.models import ClientSite, Job, SavedRoute, Trip

DEFAULT_RADIUS_M = 300
CONFIRMED, UNCONFIRMED = "confirmed", "unconfirmed"


class SaveSiteIn(BaseModel):
    """A driver saying 'this place is where [client] takes deliveries'. Sent with the delivery, so it works with no network."""

    name: str = Field(min_length=2, max_length=160)
    address: str | None = Field(default=None, max_length=255)
    lat: float | None = Field(default=None, ge=-90, le=90)  # missing: the place of the proof of delivery is used
    lng: float | None = Field(default=None, ge=-180, le=180)


@dataclass
class Spot:
    """Where a trip's delivery is expected: a site, or the coordinates an older route carries."""

    lat: float
    lng: float
    radius_m: int
    confirmed: bool  # only a confirmed place is held against a driver (an `outside_site` flag)
    site_id: uuid.UUID | None = None
    name: str | None = None
    address: str | None = None

    def out(self) -> dict:
        return {
            "id": self.site_id, "name": self.name, "address": self.address, "lat": self.lat, "lng": self.lng,
            "radius_m": self.radius_m, "status": CONFIRMED if self.confirmed else UNCONFIRMED,
        }  # fmt: skip


def site_out(s: ClientSite) -> dict:
    return {
        "id": s.id, "client_id": s.client_id, "name": s.name, "address": s.address, "lat": s.lat, "lng": s.lng,
        "radius_m": s.radius_m, "status": s.status, "verified_by_code": s.verified_by_code, "is_active": s.is_active,
        "saved_by_user_id": s.saved_by_user_id, "confirmed_at": s.confirmed_at,
    }  # fmt: skip


def _spot_of_site(s: ClientSite) -> Spot:
    return Spot(s.lat, s.lng, s.radius_m, s.status == CONFIRMED, s.id, s.name, s.address)


async def route_for(db: AsyncSession, trip: Trip) -> SavedRoute | None:
    if not trip.job_id:
        return None
    return (await db.execute(select(SavedRoute).join(Job, Job.route_id == SavedRoute.id).where(Job.id == trip.job_id))).scalar_one_or_none()


async def trip_spot(db: AsyncSession, trip: Trip, route: SavedRoute | None = None) -> Spot | None:
    """Where this trip is to be delivered: the site chosen for the trip, else the site its route ends at, else the coordinates the route itself carries."""
    if trip.site_id:
        site = (await db.execute(select(ClientSite).where(ClientSite.id == trip.site_id))).scalar_one_or_none()
        if site is not None and site.is_active:
            return _spot_of_site(site)
    route = route or await route_for(db, trip)
    if route is None:
        return None
    if route.site_id:
        site = (await db.execute(select(ClientSite).where(ClientSite.id == route.site_id))).scalar_one_or_none()
        if site is not None and site.is_active:
            return _spot_of_site(site)
    if route.dropoff_lat is not None and route.dropoff_lng is not None:
        return Spot(route.dropoff_lat, route.dropoff_lng, route.site_radius_m or 500, True, None, route.dropoff, None)
    return None


async def save_site(
    db: AsyncSession, principal: Principal, trip: Trip, body: SaveSiteIn, *, fallback: tuple[float | None, float | None], by_code: bool
) -> ClientSite | None:
    """Saves the place a trip was delivered to as a site of its client, and ties the trip to it. Nothing happens when the trip has no
    client, already has a place, or the phone gave no location. A place already saved under that name, or within its radius of one, is
    reused rather than doubled. The caller commits."""
    if trip.client_id is None or trip.site_id is not None:
        return None
    if await trip_spot(db, trip) is not None:
        return None  # the route already says where this client is delivered to
    lat = body.lat if body.lat is not None and body.lng is not None else fallback[0]
    lng = body.lng if body.lat is not None and body.lng is not None else fallback[1]
    if lat is None or lng is None:
        return None
    name = body.name.strip()
    known = (await db.execute(select(ClientSite).where(ClientSite.client_id == trip.client_id, ClientSite.is_active.is_(True)))).scalars().all()
    site = next((s for s in known if s.name.lower() == name.lower() or distance_m(lat, lng, s.lat, s.lng) <= s.radius_m), None)
    if site is None:
        senior = "clients.manage" in principal.permissions  # the owner or a manager saving it is the confirmation
        site = ClientSite(
            client_id=trip.client_id, name=name, address=(body.address or "").strip() or None, lat=lat, lng=lng, radius_m=DEFAULT_RADIUS_M,
            status=CONFIRMED if senior else UNCONFIRMED, saved_by_user_id=principal.user.id, saved_from_trip_id=trip.id, verified_by_code=by_code,
            confirmed_by_user_id=principal.user.id if senior else None, confirmed_at=datetime.now(UTC) if senior else None,
        )  # fmt: skip
        db.add(site)
        await db.flush()
        audit.record(
            db, actor_user_id=principal.user.id, action="site.saved", entity_type="client_site", entity_id=site.id,
            after={"client_id": str(site.client_id), "name": site.name, "status": site.status, "verified_by_code": by_code}, note="Saved from a delivery",
        )  # fmt: skip
    trip.site_id = site.id
    route = await route_for(db, trip)
    if route is not None and route.site_id is None and route.dropoff_lat is None:
        route.site_id = site.id  # the next job on this route is guided to the same place
    return site
