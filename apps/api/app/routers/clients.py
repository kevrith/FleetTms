"""Clients and their saved routes (masterplan 5.10): contacts, KRA PIN, default billing method and rate, and each client's
routes stored once and reused on every quote and job."""

import re
import uuid
from decimal import Decimal

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.db import get_db
from app.deps import Principal, error, require_any
from app.models import BillingMethod, Client, Job, JobStatus, SavedRoute
from app.phone import normalize_phone

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


class RouteIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    pickup: str = Field(min_length=2, max_length=160)
    dropoff: str = Field(min_length=2, max_length=160)
    dropoff_lat: float | None = Field(default=None, ge=-90, le=90)  # the client's site; a delivery far from it is flagged
    dropoff_lng: float | None = Field(default=None, ge=-180, le=180)
    site_radius_m: int = Field(default=500, ge=50, le=20_000)
    path_notes: str | None = Field(default=None, max_length=2000)
    distance_km: int = Field(ge=0, le=20_000)
    expected_hours: float = Field(default=12, gt=0, le=240)
    tolls_cents: int = Field(default=0, ge=0, le=1_000_000_000)
    crew_cents: int = Field(default=0, ge=0, le=1_000_000_000)
    other_cents: int = Field(default=0, ge=0, le=1_000_000_000)
    notes: str | None = Field(default=None, max_length=2000)
    is_active: bool = True


def _clean(body: ClientIn) -> dict:
    data = body.model_dump()
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


def client_out(c: Client, routes: int = 0, open_jobs: int = 0) -> dict:
    return {
        "id": c.id, "name": c.name, "contact_name": c.contact_name, "phone": c.phone, "email": c.email,
        "kra_pin": c.kra_pin, "billing_method": c.billing_method.value, "rate_cents": c.rate_cents,
        "payment_terms_days": c.payment_terms_days, "vat_pct": float(c.vat_pct), "notes": c.notes, "is_active": c.is_active,
        "routes": routes, "open_jobs": open_jobs,
    }  # fmt: skip


def route_out(r: SavedRoute, client_name: str | None = None) -> dict:
    return {
        "id": r.id, "client_id": r.client_id, "client_name": client_name, "name": r.name, "pickup": r.pickup,
        "dropoff": r.dropoff, "dropoff_lat": r.dropoff_lat, "dropoff_lng": r.dropoff_lng, "site_radius_m": r.site_radius_m, "path_notes": r.path_notes, "distance_km": r.distance_km, "expected_hours": r.expected_hours,
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
    return [client_out(c, routes.get(c.id, 0), open_jobs.get(c.id, 0)) for c in (await db.execute(select(Client).order_by(Client.name))).scalars()]


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
    return client_out(client, sum(1 for r in routes if r.is_active)) | {"route_list": [route_out(r, client.name) for r in routes]}


@router.put("/clients/{client_id}")
async def update_client(client_id: uuid.UUID, body: ClientIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    client = await get_client(db, client_id)
    for field, value in _clean(body).items():
        setattr(client, field, value)
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
    for field, value in body.model_dump().items():
        setattr(route, field, value)
    try:
        await db.flush()
    except IntegrityError:
        raise error(status.HTTP_409_CONFLICT, "duplicate_route", "This client already has a route with that name.") from None
    audit.record(db, actor_user_id=principal.user.id, action="route.updated", entity_type="saved_route", entity_id=route.id, after={"name": route.name})
    await db.commit()
    client = await get_client(db, route.client_id) if route.client_id else None
    return route_out(route, client.name if client else None)
