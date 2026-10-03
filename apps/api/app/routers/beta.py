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
from app.deps import Principal, current_principal, platform_admin, require
from app.models import (
    AlertSettings,
    Business,
    Client,
    Feedback,
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
    return int((await db.execute(select(func.count()).select_from(model))).scalar_one())


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
        ("trip", "Run your first trip", "Start it from the dispatch calendar or the driver's phone.", "/trips", await _count(db, Trip) > 0),
        ("gps", "See a vehicle on the map", "Start a trip with phone tracking on, or fit a tracker.", "/map", await _count(db, LocationPoint) > 0),
    ]
    done = sum(1 for i in items if i[4])
    return {"dismissed": business.onboarding_dismissed_at is not None, "done": done, "total": len(items), "items": [{"key": k, "title": t, "detail": d, "link": link, "done": ok} for k, t, d, link, ok in items]}


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
