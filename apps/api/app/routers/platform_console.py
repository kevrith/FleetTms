"""The Platform Admin console (masterplan Section 3): how the businesses on the platform are doing as customers, and the few things the
platform may do about it. It sees subscriptions, plans and counts, never a business's trips, money or people; to look inside, a business
must grant support access (see support.py). Every change is written to that business's own audit trail, so its owner can see it."""

import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, plan_rules, subscriptions
from app.config import settings
from app.db import database_is_up, get_db
from app.deps import Principal, error, platform_admin
from app.models import (
    BreachIncident,
    Business,
    Membership,
    Subscription,
    SubscriptionInvoice,
    User,
    Vehicle,
)
from app.tenancy import current_business_id

router = APIRouter(tags=["platform"])


class ExtendIn(BaseModel):
    days: int = Field(ge=1, le=90)
    reason: str = Field(min_length=3, max_length=255)


class FlagIn(BaseModel):
    value: bool
    reason: str = Field(min_length=3, max_length=255)


class SuspendIn(BaseModel):
    reason: str = Field(min_length=3, max_length=255)


class PriceIn(BaseModel):
    monthly_cents: int = Field(ge=100_000, le=1_000_000_000)


class MarkPaidIn(BaseModel):
    method: Literal["bank", "manual", "card"] = "bank"
    reference: str = Field(min_length=3, max_length=12)


def _all(stmt):
    return stmt.execution_options(skip_tenant=True)


async def _facts(db: AsyncSession) -> dict[uuid.UUID, dict]:
    """Per business: its subscription, its vehicles by plan, how many people it has, and what it is in right now."""
    businesses = (await db.execute(select(Business))).scalars().all()
    subs = {s.business_id: s for s in (await db.execute(_all(select(Subscription)))).scalars()}
    plans: dict[uuid.UUID, list[str]] = defaultdict(list)
    for business_id, plan in (await db.execute(_all(select(Vehicle.business_id, Vehicle.plan).where(Vehicle.is_active.is_(True))))).all():
        plans[business_id].append(plan)
    people = dict((await db.execute(_all(select(Membership.business_id, func.count()).group_by(Membership.business_id)))).all())
    now = datetime.now(UTC)
    out = {}
    for b in businesses:
        sub = subs.get(b.id)
        trial_end = sub.trial_ends_at if sub else b.created_at + timedelta(days=plan_rules.TRIAL_DAYS)
        access = plan_rules.access_state(complimentary=b.complimentary, trial_ends_at=trial_end, paid_until=sub.paid_until if sub else None, now=now)
        if b.suspended_at is not None:
            access = {**access, "state": "suspended", "writable": False}
        quote = plan_rules.quote_subscription(plans.get(b.id, []), period=sub.period if sub else "monthly", payroll_employees=0)
        monthly = sub.custom_monthly_cents if sub and sub.custom_monthly_cents and quote["custom"] else quote["monthly_cents"]
        out[b.id] = {"business": b, "sub": sub, "access": access, "plans": plans.get(b.id, []), "people": people.get(b.id, 0), "monthly_cents": monthly}
    return out


def _row(f: dict) -> dict:
    b, sub, a = f["business"], f["sub"], f["access"]
    return {
        "id": b.id, "name": b.name, "created_at": b.created_at, "state": a["state"], "complimentary": b.complimentary, "suspended": b.suspended_at is not None, "days_left": a.get("days_left"),
        "trial_ends_at": sub.trial_ends_at if sub else None, "paid_until": sub.paid_until if sub else None, "period": sub.period if sub else "monthly", "vehicles": len(f["plans"]),
        "plans": {p: f["plans"].count(p) for p in plan_rules.PLANS if f["plans"].count(p)}, "people": f["people"], "monthly_cents": f["monthly_cents"], "custom_monthly_cents": sub.custom_monthly_cents if sub else None,
    }  # fmt: skip


@router.get("/platform/overview")
async def overview(principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    """Customers by state, vehicles by plan, and the recurring revenue of those who are paying."""
    facts = await _facts(db)
    by_state: dict[str, int] = defaultdict(int)
    plans: dict[str, int] = defaultdict(int)
    mrr = 0
    for f in facts.values():
        by_state[f["access"]["state"]] += 1
        for p in f["plans"]:
            plans[p] += 1
        if f["access"]["state"] in ("active", "grace") and not f["business"].complimentary:
            mrr += f["monthly_cents"]
    unpaid = (await db.execute(_all(select(func.count()).select_from(SubscriptionInvoice).where(SubscriptionInvoice.status == "issued")))).scalar_one()
    from app.routers.breaches import out as breach_out

    breaches = [breach_out(b) for b in (await db.execute(select(BreachIncident).where(BreachIncident.status != "closed"))).scalars()]
    return {"breaches_open": len(breaches), "breaches_overdue": sum(1 for b in breaches if b["odpc_overdue"]), "businesses": len(facts), "by_state": dict(by_state), "vehicles": sum(plans.values()), "vehicles_by_plan": dict(plans), "mrr_cents": mrr, "open_invoices": int(unpaid)}


@router.get("/platform/customers")
async def businesses(state: str | None = None, q: str | None = None, principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    rows = [_row(f) for f in (await _facts(db)).values()]
    if state:
        rows = [r for r in rows if r["state"] == state]
    if q:
        rows = [r for r in rows if q.lower() in r["name"].lower()]
    return sorted(rows, key=lambda r: r["created_at"], reverse=True)


async def _one(db: AsyncSession, business_id: uuid.UUID) -> dict:
    f = (await _facts(db)).get(business_id)
    if f is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That business was not found.")
    return f


@router.get("/platform/businesses/{business_id}")
async def business_detail(business_id: uuid.UUID, principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    f = await _one(db, business_id)
    invoices = (await db.execute(_all(select(SubscriptionInvoice).where(SubscriptionInvoice.business_id == business_id).order_by(SubscriptionInvoice.created_at.desc()).limit(24)))).scalars().all()
    owner = (await db.execute(_all(select(User).join(Membership, Membership.user_id == User.id).where(Membership.business_id == business_id).order_by(Membership.created_at).limit(1)))).scalars().first()
    return {
        **_row(f), "kra_pin": f["business"].kra_pin, "suspended_reason": f["business"].suspended_reason, "owner": {"name": owner.name, "email": owner.email, "phone": owner.phone} if owner else None,
        "invoices": [{"id": i.id, "number": i.number, "kind": i.kind, "status": i.status, "total_cents": i.total_cents, "due_date": i.due_date, "paid_at": i.paid_at, "payment_method": i.payment_method} for i in invoices],
    }  # fmt: skip


async def _act(db: AsyncSession, principal: Principal, business_id: uuid.UUID, action: str, after: dict) -> None:
    """Writes what the platform did into the business's own audit trail."""
    current_business_id.set(business_id)
    try:
        audit.record(db, actor_user_id=principal.user.id, action=f"platform.{action}", entity_type="business", entity_id=business_id, after=after)
        await db.flush()
    finally:
        current_business_id.set(None)


async def _sub(db: AsyncSession, business_id: uuid.UUID, business: Business) -> Subscription:
    current_business_id.set(business_id)
    try:
        return await subscriptions.get_or_start(db, business)
    finally:
        current_business_id.set(None)


@router.post("/platform/businesses/{business_id}/extend-trial")
async def extend_trial(business_id: uuid.UUID, body: ExtendIn, principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    """More time before the first payment is due, from whichever is later: today or the current trial end."""
    f = await _one(db, business_id)
    sub = await _sub(db, business_id, f["business"])
    sub.trial_ends_at = max(sub.trial_ends_at, datetime.now(UTC)) + timedelta(days=body.days)
    await _act(db, principal, business_id, "trial_extended", {"days": body.days, "reason": body.reason})
    await db.commit()
    return _row((await _facts(db))[business_id])


@router.post("/platform/businesses/{business_id}/complimentary")
async def complimentary(business_id: uuid.UUID, body: FlagIn, principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    """A free account: every feature, never billed (the pilot, a partner, a gift)."""
    f = await _one(db, business_id)
    f["business"].complimentary = body.value
    await _act(db, principal, business_id, "complimentary_set", {"value": body.value, "reason": body.reason})
    await db.commit()
    return _row((await _facts(db))[business_id])


@router.post("/platform/businesses/{business_id}/suspend")
async def suspend(business_id: uuid.UUID, body: SuspendIn, principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    """Puts the account on hold: read-only, with nothing deleted. For abuse or a dispute, not for non-payment (that is automatic)."""
    f = await _one(db, business_id)
    f["business"].suspended_at, f["business"].suspended_reason = datetime.now(UTC), body.reason
    await _act(db, principal, business_id, "suspended", {"reason": body.reason})
    await db.commit()
    return _row((await _facts(db))[business_id])


@router.post("/platform/businesses/{business_id}/unsuspend")
async def unsuspend(business_id: uuid.UUID, principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    f = await _one(db, business_id)
    f["business"].suspended_at, f["business"].suspended_reason = None, None
    await _act(db, principal, business_id, "unsuspended", {})
    await db.commit()
    return _row((await _facts(db))[business_id])


@router.post("/platform/businesses/{business_id}/custom-price")
async def custom_price(business_id: uuid.UUID, body: PriceIn, principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    """The monthly price agreed with a fleet of 31 or more vehicles."""
    f = await _one(db, business_id)
    sub = await _sub(db, business_id, f["business"])
    sub.custom_monthly_cents = body.monthly_cents
    await _act(db, principal, business_id, "custom_price_set", {"monthly_cents": body.monthly_cents})
    await db.commit()
    return _row((await _facts(db))[business_id])


@router.post("/platform/invoices/{invoice_id}/mark-paid")
async def mark_paid(invoice_id: uuid.UUID, body: MarkPaidIn, principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    """A bank transfer (or card payment taken outside the system) has arrived: the invoice is paid and the period starts."""
    invoice = (await db.execute(_all(select(SubscriptionInvoice).where(SubscriptionInvoice.id == invoice_id)))).scalar_one_or_none()
    if invoice is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That invoice was not found.")
    if invoice.status != "issued":
        raise error(status.HTTP_409_CONFLICT, "not_payable", "That invoice is not waiting for payment.")
    current_business_id.set(invoice.business_id)
    try:
        await subscriptions.apply_paid(db, invoice, method=body.method, code=body.reference.upper())
        audit.record(db, actor_user_id=principal.user.id, action="platform.invoice_marked_paid", entity_type="subscription_invoice", entity_id=invoice.id, after={"number": invoice.number, "method": body.method, "reference": body.reference})
        await db.commit()
    finally:
        current_business_id.set(None)
    return {"id": invoice.id, "status": invoice.status}


@router.get("/platform/health")
async def health(principal: Principal = Depends(platform_admin)):
    """Is the platform itself up: the database and the job queue's Redis."""
    redis_ok = False
    try:
        from redis.asyncio import Redis

        client = Redis.from_url(settings.redis_url, socket_connect_timeout=2)
        redis_ok = bool(await client.ping())
        await client.aclose()
    except Exception:  # noqa: BLE001
        redis_ok = False
    return {"database": await database_is_up(), "redis": redis_ok, "version": settings.version, "checked_at": datetime.now(UTC)}
