"""Private beta (masterplan Sprint 13): the getting-started checklist for the owner and the feedback button for everyone."""

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.db import get_db
from app.deps import Principal, current_principal, error, platform_admin, require
from app.models import (
    AlertSettings,
    Business,
    Client,
    Feedback,
    Job,
    LocationPoint,
    Membership,
    Role,
    SavedRoute,
    SpendLimit,
    Trip,
    Vehicle,
)
from app.tenancy import current_business_id

router = APIRouter(tags=["beta"])


class FeedbackIn(BaseModel):
    kind: Literal["problem", "idea", "praise"] = "idea"
    message: str = Field(min_length=3, max_length=2000)
    page: str | None = Field(default=None, max_length=200)
    app: Literal["web", "mobile"] | None = None


async def _count(db: AsyncSession, model) -> int:
    """How many real ones: the sample data from "try it with sample data" does not count as having set something up."""
    query = select(func.count()).select_from(model)
    if hasattr(model, "is_sample"):
        query = query.where(model.is_sample.is_(False))
    return int((await db.execute(query)).scalar_one())


@router.get("/onboarding")
async def onboarding(principal: Principal = Depends(require("business.manage")), db: AsyncSession = Depends(get_db)):
    """What a new owner still has to set up, worked out from what is already in the system, so it can never be out of date."""
    business = (await db.execute(select(Business).where(Business.id == current_business_id.get()))).scalar_one()
    staff = [m for m in (await db.execute(select(Membership))).scalars() if Role.OWNER not in {r.role for r in m.roles}]
    items = [
        ("vehicles", "Add your vehicles", "Registration, tank size and the fuel they should burn.", "/vehicles", await _count(db, Vehicle) > 0),
        ("team", "Invite your drivers and managers", "Drivers sign in with their phone number.", "/settings/people", len(staff) > 0),
        ("clients", "Add a client", "Clients are who you quote, dispatch and invoice.", "/clients", await _count(db, Client) > 0),
        ("routes", "Save a route", "Distance, tolls and the time it should take.", "/clients", await _count(db, SavedRoute) > 0),
        ("limits", "Set spending limits", "Above these, an expense waits for your approval.", "/expenses/limits", await _count(db, SpendLimit) > 0),
        ("alerts", "Review your alert settings", "Who is told by text, and how strict the fuel check is.", "/alerts/settings", (await db.execute(select(AlertSettings.id))).first() is not None),
        ("job", "Create your first job", "A client, a route and what is to be carried: three questions.", "/start", await _count(db, Job) > 0),
        ("trip", "Run your first trip", "Start it from the dispatch calendar or the driver's phone.", "/trips", await _count(db, Trip) > 0),
        ("gps", "See a vehicle on the map", "Start a trip with phone tracking on, or fit a tracker.", "/map", await _count(db, LocationPoint) > 0),
    ]
    done = sum(1 for i in items if i[4])
    sample = (await db.execute(select(func.count()).select_from(Vehicle).where(Vehicle.is_sample.is_(True)))).scalar_one() > 0
    return {"has_sample_data": sample, "dismissed": business.onboarding_dismissed_at is not None, "done": done, "total": len(items), "items": [{"key": k, "title": t, "detail": d, "link": link, "done": ok} for k, t, d, link, ok in items]}


class FirstJobIn(BaseModel):
    client_name: str = Field(min_length=2, max_length=160)
    pickup: str = Field(min_length=2, max_length=160)
    dropoff: str = Field(min_length=2, max_length=160)
    distance_km: int = Field(ge=1, le=20_000)
    rate_cents: int = Field(ge=1, le=10_000_000_000)
    billing_method: Literal["per_trip", "per_tonne", "per_km", "monthly_contract"] = "per_trip"
    cargo_description: str | None = Field(default=None, max_length=255)
    weight_tonnes: float = Field(default=0, ge=0, le=1000)
    trips: int = Field(default=1, ge=1, le=500)


@router.post("/onboarding/first-job", status_code=status.HTTP_201_CREATED)
async def first_job(body: FirstJobIn, principal: Principal = Depends(require("business.manage")), db: AsyncSession = Depends(get_db)):
    """A first job from three answers: who it is for, where from and to, and what they pay. The client and the route are made as part of
    it (or found, if they already exist), so there is nothing else to fill in before there is a job to dispatch."""
    from decimal import Decimal

    from app.models import BillingMethod
    from app.routers import jobs as jobs_router

    name = body.client_name.strip()
    client = (await db.execute(select(Client).where(func.lower(Client.name) == name.lower()))).scalars().first()
    if client is None:
        client = Client(name=name, billing_method=BillingMethod(body.billing_method), rate_cents=body.rate_cents)
        db.add(client)
        await db.flush()
        audit.record(db, actor_user_id=principal.user.id, action="client.added", entity_type="client", entity_id=client.id, after={"name": client.name}, note="Created by the setup guide")
    route_name = f"{body.pickup.strip()} to {body.dropoff.strip()}"
    route = (await db.execute(select(SavedRoute).where(SavedRoute.client_id == client.id, SavedRoute.name == route_name))).scalars().first()
    if route is None:
        route = SavedRoute(client_id=client.id, name=route_name, pickup=body.pickup.strip(), dropoff=body.dropoff.strip(), distance_km=body.distance_km)
        db.add(route)
        await db.flush()
        audit.record(db, actor_user_id=principal.user.id, action="route.added", entity_type="saved_route", entity_id=route.id, after={"name": route.name}, note="Created by the setup guide")
    job = await jobs_router.create_job(
        jobs_router.JobIn(client_id=client.id, route_id=route.id, cargo_description=body.cargo_description, weight_tonnes=Decimal(str(body.weight_tonnes)), trips=body.trips, billing_method=BillingMethod(body.billing_method), rate_cents=body.rate_cents),
        principal, db,
    )  # fmt: skip
    return {"client_id": client.id, "route_id": route.id, "job": job}


SAMPLE = {"registration": "DEMO 001A", "client": "Sample Client Ltd", "route": "Mombasa to Nairobi (sample)"}


@router.post("/onboarding/sample-data", status_code=status.HTTP_201_CREATED)
async def add_sample_data(principal: Principal = Depends(require("business.manage")), db: AsyncSession = Depends(get_db)):
    """A lorry, a client, a route and a job to click around in. All of it is marked as a sample, is left out of the checklist, and can be
    removed again once nothing has been started on it."""
    from decimal import Decimal

    from app.models import BillingMethod, FuelType
    from app.numbering import create_numbered

    if (await db.execute(select(Vehicle.id).where(Vehicle.is_sample.is_(True)))).first() is not None:
        raise error(status.HTTP_409_CONFLICT, "already_there", "The sample data is already there.")
    vehicle = Vehicle(registration=SAMPLE["registration"], make="Isuzu", model="FVZ", capacity_tonnes=Decimal(30), fuel_type=FuelType.DIESEL, tank_litres=400, expected_kmpl_loaded=Decimal("3.5"), expected_kmpl_empty=Decimal(5), odometer_km=100_000, is_sample=True)
    client = Client(name=SAMPLE["client"], billing_method=BillingMethod.PER_TONNE, rate_cents=300_000, is_sample=True)
    db.add_all([vehicle, client])
    await db.flush()
    route = SavedRoute(client_id=client.id, name=SAMPLE["route"], pickup="Mombasa", dropoff="Nairobi", distance_km=480, expected_hours=14, tolls_cents=600_000, crew_cents=700_000, other_cents=200_000, is_sample=True)
    db.add(route)
    await db.flush()
    job = await create_numbered(db, Job, "J", client_id=client.id, route_id=route.id, cargo_description="Cement (sample)", weight_tonnes=Decimal(30), trips_planned=1, billing_method=BillingMethod.PER_TONNE, rate_cents=300_000, price_cents=9_000_000, expected_profit_cents=0, created_by_user_id=principal.user.id, is_sample=True)
    audit.record(db, actor_user_id=principal.user.id, action="onboarding.sample_data_added", entity_type="business", entity_id=principal.business_id)
    await db.commit()
    return {"vehicle_id": vehicle.id, "client_id": client.id, "route_id": route.id, "job_id": job.id}


@router.delete("/onboarding/sample-data", status_code=status.HTTP_204_NO_CONTENT)
async def remove_sample_data(principal: Principal = Depends(require("business.manage")), db: AsyncSession = Depends(get_db)):
    """Takes the sample data away again. Not once a trip has been started on it: that would be real work."""
    vehicles = (await db.execute(select(Vehicle).where(Vehicle.is_sample.is_(True)))).scalars().all()
    jobs = (await db.execute(select(Job).where(Job.is_sample.is_(True)))).scalars().all()
    if (await db.execute(select(Trip.id).where((Trip.vehicle_id.in_([v.id for v in vehicles])) | (Trip.job_id.in_([j.id for j in jobs]))).limit(1))).first() is not None:
        raise error(status.HTTP_409_CONFLICT, "sample_in_use", "A trip has been started on the sample data, so it is kept. Delete or finish that trip first.")
    for model in (Job, SavedRoute, Client, Vehicle):
        for row in (await db.execute(select(model).where(model.is_sample.is_(True)))).scalars().all():
            await db.delete(row)
    audit.record(db, actor_user_id=principal.user.id, action="onboarding.sample_data_removed", entity_type="business", entity_id=principal.business_id)
    await db.commit()


@router.post("/onboarding/dismiss", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss(principal: Principal = Depends(require("business.manage")), db: AsyncSession = Depends(get_db)):
    business = (await db.execute(select(Business).where(Business.id == current_business_id.get()))).scalar_one()
    business.onboarding_dismissed_at = datetime.now(UTC)
    await db.commit()


@router.post("/onboarding/restore", status_code=status.HTTP_204_NO_CONTENT)
async def restore(principal: Principal = Depends(require("business.manage")), db: AsyncSession = Depends(get_db)):
    business = (await db.execute(select(Business).where(Business.id == current_business_id.get()))).scalar_one()
    business.onboarding_dismissed_at = None
    await db.commit()


@router.post("/feedback", status_code=status.HTTP_201_CREATED)
async def send_feedback(body: FeedbackIn, principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    """Anyone signed in can tell us what is wrong, what is missing or what they like. It is stored with where they were in the app."""
    row = Feedback(user_id=principal.user.id, kind=body.kind, message=body.message.strip(), page=body.page, app=body.app)
    db.add(row)
    await db.flush()
    audit.record(db, actor_user_id=principal.user.id, action="feedback.sent", entity_type="feedback", entity_id=row.id, after={"kind": body.kind})
    await db.commit()
    return {"id": row.id}


def _feedback_out(f: Feedback, names: dict[uuid.UUID, str], business: str | None = None) -> dict:
    return {"id": f.id, "kind": f.kind, "message": f.message, "page": f.page, "app": f.app, "from": names.get(f.user_id), "business": business, "created_at": f.created_at}


@router.get("/feedback")
async def my_business_feedback(principal: Principal = Depends(require("business.manage")), db: AsyncSession = Depends(get_db)):
    """What this business's own people have sent."""
    names = {m.user_id: m.user.name for m in (await db.execute(select(Membership))).scalars()}
    return [_feedback_out(f, names) for f in (await db.execute(select(Feedback).order_by(Feedback.created_at.desc()).limit(200))).scalars()]


@router.get("/platform/feedback")
async def all_feedback(principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    """Everything beta testers have sent, from every business, for the people running the beta."""
    from app.models import User

    businesses = {b.id: b.name for b in (await db.execute(select(Business))).scalars()}
    names = {u.id: u.name for u in (await db.execute(select(User))).scalars()}
    rows = (await db.execute(select(Feedback).order_by(Feedback.created_at.desc()).limit(500).execution_options(skip_tenant=True))).scalars().all()
    return [_feedback_out(f, names, businesses.get(f.business_id)) for f in rows]
