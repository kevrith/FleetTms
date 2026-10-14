"""Clients, their sites and their saved routes (masterplan 5.10): contacts, KRA PIN, default billing method and rate, the places each
client takes deliveries, and each client's routes stored once and reused on every quote and job."""

import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.db import get_db
from app.deps import Principal, error, require, require_any
from app.models import BillingMethod, Client, ClientSite, Job, JobStatus, SavedRoute
from app.phone import normalize_phone
from app.sites import CONFIRMED, DEFAULT_RADIUS_M, UNCONFIRMED, site_out

router = APIRouter(tags=["clients"])
MANAGE = ("clients.manage",)
READ = ("clients.manage", "jobs.manage")
KRA_PIN = re.compile(r"^[AP]\d{9}[A-Z]$")


class ClientIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    contact_name: str | None = Field(default=None, max_length=120)
    phone: str | None = None
    email: str | None = Field(default=None, max_length=255)
    kra_pin: str | None = Field(default=None, max_length=11)
    billing_method: BillingMethod = BillingMethod.PER_TRIP
    rate_cents: int = Field(default=0, ge=0, le=10_000_000_000)
    payment_terms_days: int = Field(default=30, ge=0, le=365)
    vat_pct: Decimal = Field(default=Decimal(0), ge=0, le=30, decimal_places=2)
    notes: str | None = Field(default=None, max_length=2000)
    is_active: bool = True
    reminders_enabled: bool | None = None  # payment reminders; left out means unchanged


class RouteIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    pickup: str = Field(min_length=2, max_length=160)
    dropoff: str = Field(min_length=2, max_length=160)
    dropoff_lat: float | None = Field(default=None, ge=-90, le=90)  # the client's site; a delivery far from it is flagged
    dropoff_lng: float | None = Field(default=None, ge=-180, le=180)
    site_radius_m: int = Field(default=500, ge=50, le=20_000)
    site_id: uuid.UUID | None = None  # one of the client's sites; wins over the coordinates above. Left out means unchanged
    path_notes: str | None = Field(default=None, max_length=2000)
    distance_km: int = Field(ge=0, le=20_000)
    expected_hours: float = Field(default=12, gt=0, le=240)
    tolls_cents: int = Field(default=0, ge=0, le=1_000_000_000)
    crew_cents: int = Field(default=0, ge=0, le=1_000_000_000)
    other_cents: int = Field(default=0, ge=0, le=1_000_000_000)
    notes: str | None = Field(default=None, max_length=2000)
    is_active: bool = True


class SiteIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    address: str | None = Field(default=None, max_length=255)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    radius_m: int = Field(default=DEFAULT_RADIUS_M, ge=50, le=20_000)
    is_active: bool = True


def _clean(body: ClientIn) -> dict:
    data = body.model_dump()
    if data.get("reminders_enabled") is None:
        data.pop("reminders_enabled", None)
    data["name"] = body.name.strip()
    if body.phone:
        phone = normalize_phone(body.phone)
        if phone is None:
            raise error(422, "invalid_phone", "Enter a valid phone number.")
        data["phone"] = phone
    if body.email:
        try:
            data["email"] = validate_email(body.email.strip(), check_deliverability=False).normalized
        except EmailNotValidError:
            raise error(422, "invalid_email", "Enter a valid email address.") from None
    if body.kra_pin:
        pin = body.kra_pin.strip().upper()
        if not KRA_PIN.match(pin):
            raise error(422, "invalid_kra_pin", "A KRA PIN is a letter, nine digits and a letter, like A012345678Z.")
        data["kra_pin"] = pin
    return data


def client_out(c: Client, routes: int = 0, open_jobs: int = 0, sites: int = 0, unconfirmed_sites: int = 0) -> dict:
    return {
        "id": c.id, "name": c.name, "contact_name": c.contact_name, "phone": c.phone, "email": c.email,
        "kra_pin": c.kra_pin, "billing_method": c.billing_method.value, "rate_cents": c.rate_cents,
        "payment_terms_days": c.payment_terms_days, "vat_pct": float(c.vat_pct), "notes": c.notes, "is_active": c.is_active, "reminders_enabled": c.reminders_enabled,
        "needs_review": c.needs_review, "routes": routes, "open_jobs": open_jobs, "sites": sites, "unconfirmed_sites": unconfirmed_sites,
    }  # fmt: skip


def route_out(r: SavedRoute, client_name: str | None = None) -> dict:
    return {
        "id": r.id, "client_id": r.client_id, "client_name": client_name, "name": r.name, "pickup": r.pickup,
        "dropoff": r.dropoff, "dropoff_lat": r.dropoff_lat, "dropoff_lng": r.dropoff_lng, "site_radius_m": r.site_radius_m, "site_id": r.site_id, "path_notes": r.path_notes, "distance_km": r.distance_km, "expected_hours": r.expected_hours,
        "tolls_cents": r.tolls_cents, "crew_cents": r.crew_cents, "other_cents": r.other_cents, "notes": r.notes,
        "is_active": r.is_active,
    }  # fmt: skip


async def get_client(db: AsyncSession, client_id: uuid.UUID) -> Client:
    client = (await db.execute(select(Client).where(Client.id == client_id))).scalar_one_or_none()
    if client is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That client was not found.")
    return client


@router.get("/clients")
async def list_clients(principal: Principal = Depends(require_any(*READ)), db: AsyncSession = Depends(get_db)):
    routes = dict((await db.execute(select(SavedRoute.client_id, func.count()).where(SavedRoute.is_active.is_(True)).group_by(SavedRoute.client_id))).all())
    open_jobs = dict(
        (await db.execute(select(Job.client_id, func.count()).where(Job.status.in_((JobStatus.PLANNED, JobStatus.DISPATCHED, JobStatus.IN_PROGRESS))).group_by(Job.client_id))).all()
    )
    site_counts: dict = {}
    for client_id, status_, n in (await db.execute(select(ClientSite.client_id, ClientSite.status, func.count()).where(ClientSite.is_active.is_(True)).group_by(ClientSite.client_id, ClientSite.status))).all():
        counts = site_counts.setdefault(client_id, [0, 0])
        counts[0] += n
        counts[1] += n if status_ == UNCONFIRMED else 0
    return [client_out(c, routes.get(c.id, 0), open_jobs.get(c.id, 0), *site_counts.get(c.id, (0, 0))) for c in (await db.execute(select(Client).order_by(Client.name))).scalars()]


@router.post("/clients", status_code=status.HTTP_201_CREATED)
async def add_client(body: ClientIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    client = Client(**_clean(body))
    db.add(client)
    try:
        await db.flush()
    except IntegrityError:
        raise error(status.HTTP_409_CONFLICT, "duplicate_client", "A client with that name already exists.") from None
    audit.record(db, actor_user_id=principal.user.id, action="client.added", entity_type="client", entity_id=client.id, after={"name": client.name})
    await db.commit()
    return client_out(client)


@router.get("/clients/{client_id}")
async def read_client(client_id: uuid.UUID, principal: Principal = Depends(require_any(*READ)), db: AsyncSession = Depends(get_db)):
    client = await get_client(db, client_id)
    routes = (await db.execute(select(SavedRoute).where(SavedRoute.client_id == client.id).order_by(SavedRoute.name))).scalars().all()
    sites = (await db.execute(select(ClientSite).where(ClientSite.client_id == client.id).order_by(ClientSite.name))).scalars().all()
    live = [x for x in sites if x.is_active]
    return client_out(client, sum(1 for r in routes if r.is_active), 0, len(live), sum(1 for x in live if x.status == UNCONFIRMED)) | {
        "route_list": [route_out(r, client.name) for r in routes],
        "site_list": [site_out(x) for x in sites],
    }


@router.put("/clients/{client_id}")
async def update_client(client_id: uuid.UUID, body: ClientIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    client = await get_client(db, client_id)
    for field, value in _clean(body).items():
        setattr(client, field, value)
    client.needs_review = False  # the office has looked at it
    try:
        await db.flush()
    except IntegrityError:
        raise error(status.HTTP_409_CONFLICT, "duplicate_client", "A client with that name already exists.") from None
    audit.record(db, actor_user_id=principal.user.id, action="client.updated", entity_type="client", entity_id=client.id, after={"name": client.name})
    await db.commit()
    return client_out(client)


# ---- Saved routes ----------------------------------------------------------------------------------


@router.get("/routes")
async def list_routes(principal: Principal = Depends(require_any(*READ)), db: AsyncSession = Depends(get_db)):
    names = {c.id: c.name for c in (await db.execute(select(Client))).scalars()}
    return [route_out(r, names.get(r.client_id)) for r in (await db.execute(select(SavedRoute).where(SavedRoute.is_active.is_(True)).order_by(SavedRoute.name))).scalars()]


@router.post("/clients/{client_id}/routes", status_code=status.HTTP_201_CREATED)
async def add_route(client_id: uuid.UUID, body: RouteIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    client = await get_client(db, client_id)
    await _check_route_site(db, client.id, body.site_id)
    route = SavedRoute(client_id=client.id, **body.model_dump())
    db.add(route)
    try:
        await db.flush()
    except IntegrityError:
        raise error(status.HTTP_409_CONFLICT, "duplicate_route", "This client already has a route with that name.") from None
    audit.record(db, actor_user_id=principal.user.id, action="route.added", entity_type="saved_route", entity_id=route.id, after={"client": client.name, "name": route.name})
    await db.commit()
    return route_out(route, client.name)


@router.put("/routes/{route_id}")
async def update_route(route_id: uuid.UUID, body: RouteIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    route = (await db.execute(select(SavedRoute).where(SavedRoute.id == route_id))).scalar_one_or_none()
    if route is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That route was not found.")
    await _check_route_site(db, route.client_id, body.site_id)
    for field, value in body.model_dump().items():
        if field == "site_id" and field not in body.model_fields_set:
            continue
        setattr(route, field, value)
    try:
        await db.flush()
    except IntegrityError:
        raise error(status.HTTP_409_CONFLICT, "duplicate_route", "This client already has a route with that name.") from None
    audit.record(db, actor_user_id=principal.user.id, action="route.updated", entity_type="saved_route", entity_id=route.id, after={"name": route.name})
    await db.commit()
    client = await get_client(db, route.client_id) if route.client_id else None
    return route_out(route, client.name if client else None)


async def _check_route_site(db: AsyncSession, client_id: uuid.UUID | None, site_id: uuid.UUID | None) -> None:
    if site_id is None:
        return
    site = (await db.execute(select(ClientSite).where(ClientSite.id == site_id))).scalar_one_or_none()
    if site is None or site.client_id != client_id:
        raise error(422, "wrong_site", "That place does not belong to this client.")


# ---- Client sites ----------------------------------------------------------------------------------


async def get_site(db: AsyncSession, site_id: uuid.UUID) -> ClientSite:
    site = (await db.execute(select(ClientSite).where(ClientSite.id == site_id))).scalar_one_or_none()
    if site is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That place was not found.")
    return site


@router.post("/clients/{client_id}/sites", status_code=status.HTTP_201_CREATED)
async def add_site(client_id: uuid.UUID, body: SiteIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    client = await get_client(db, client_id)
    now = datetime.now(UTC)
    site = ClientSite(
        client_id=client.id, name=body.name.strip(), address=(body.address or "").strip() or None, lat=body.lat, lng=body.lng, radius_m=body.radius_m,
        status=CONFIRMED, saved_by_user_id=principal.user.id, confirmed_by_user_id=principal.user.id, confirmed_at=now, is_active=body.is_active,
    )  # fmt: skip
    db.add(site)
    try:
        await db.flush()
    except IntegrityError:
        raise error(status.HTTP_409_CONFLICT, "duplicate_site", "This client already has a place with that name.") from None
    audit.record(db, actor_user_id=principal.user.id, action="site.added", entity_type="client_site", entity_id=site.id, after={"client": client.name, "name": site.name})
    await db.commit()
    return site_out(site)


@router.put("/sites/{site_id}")
async def update_site(site_id: uuid.UUID, body: SiteIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    site = await get_site(db, site_id)
    site.name, site.address, site.lat, site.lng, site.radius_m, site.is_active = body.name.strip(), (body.address or "").strip() or None, body.lat, body.lng, body.radius_m, body.is_active
    try:
        await db.flush()
    except IntegrityError:
        raise error(status.HTTP_409_CONFLICT, "duplicate_site", "This client already has a place with that name.") from None
    audit.record(db, actor_user_id=principal.user.id, action="site.updated", entity_type="client_site", entity_id=site.id, after={"name": site.name, "is_active": site.is_active})
    await db.commit()
    return site_out(site)


@router.post("/sites/{site_id}/confirm")
async def confirm_site(site_id: uuid.UUID, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    """The office saying a place a driver saved really is where the client takes deliveries. From then on a delivery away from it is flagged."""
    site = await get_site(db, site_id)
    if site.status != CONFIRMED:
        site.status, site.confirmed_by_user_id, site.confirmed_at = CONFIRMED, principal.user.id, datetime.now(UTC)
        audit.record(db, actor_user_id=principal.user.id, action="site.confirmed", entity_type="client_site", entity_id=site.id, after={"name": site.name})
        await db.commit()
    return site_out(site)


@router.get("/me/clients")
async def clients_to_deliver_to(principal: Principal = Depends(require("trips.own")), db: AsyncSession = Depends(get_db)):
    """The clients a driver can pick for a trip, each with the places saved for it. Names and places only: nothing about money."""
    sites: dict = {}
    for x in (await db.execute(select(ClientSite).where(ClientSite.is_active.is_(True)).order_by(ClientSite.name))).scalars():
        sites.setdefault(x.client_id, []).append(site_out(x))
    return [
        {"id": c.id, "name": c.name, "needs_review": c.needs_review, "has_phone": bool(c.phone), "sites": sites.get(c.id, [])}
        for c in (await db.execute(select(Client).where(Client.is_active.is_(True)).order_by(Client.name))).scalars()
    ]
