"""The rest of the Platform Admin console: analytics, renewals, running a customer's subscription (advance, correct, cancel, change a vehicle's
plan, raise or void an invoice), the invoice ledger, internal notes, who may run the console, the platform's audit trail, the feedback inbox and
the system status page. Like platform_console.py it sees subscriptions, plans and counts, never a business's trips, money or people.

What changes a customer's account is written to that customer's own audit trail (so its owner can see what the platform did). What belongs
to no customer (notes, who is an admin, the inbox) goes to the platform's own log (`PlatformAction`)."""

import csv
import io
import math
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager, suppress
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, plan_rules, platform_etims, readiness, subscriptions
from app.config import settings
from app.db import get_db
from app.deps import Principal, error, platform_admin
from app.lease_rules import add_months
from app.models import (
    AuditLog,
    AuthSession,
    BreachIncident,
    Business,
    Feedback,
    Membership,
    MembershipStatus,
    Partner,
    PaymentReminder,
    PlatformAction,
    PlatformEtimsSubmission,
    PlatformNote,
    Role,
    Subscription,
    SubscriptionInvoice,
    SubscriptionPayment,
    SupportGrant,
    User,
    Vehicle,
    WhatsAppMessage,
)
from app.reminders import NAIROBI
from app.routers.platform_console import _all, _facts, _one, _row
from app.sms import get_sms_sender
from app.tenancy import current_business_id

router = APIRouter(tags=["platform"])
DAY = timedelta(days=1)
AUDIT_PREFIXES = ("platform.", "subscription.", "platform_etims.", "support.")


@asynccontextmanager
async def in_business(business_id: uuid.UUID):
    """Runs a block inside one business, for the helpers that read and write through the tenant filter."""
    current_business_id.set(business_id)
    try:
        yield
    finally:
        current_business_id.set(None)


def log_action(db: AsyncSession, principal: Principal, action: str, entity_type: str, entity_id: object = None, business_id: uuid.UUID | None = None, detail: dict | None = None) -> None:
    db.add(PlatformAction(actor_user_id=principal.user.id, action=action, business_id=business_id, entity_type=entity_type, entity_id=str(entity_id) if entity_id else None, detail=detail))


def _iso(value: datetime | date | None) -> str | None:
    return value.isoformat() if value else None


def _safe_cell(value: object) -> object:
    """A spreadsheet runs a cell that starts with = + - or @ as a formula: those are written as text."""
    return "'" + value if isinstance(value, str) and value[:1] in ("=", "+", "-", "@") else value


def _csv(name: str, header: list[str], rows: list[list]) -> Response:
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(header)
    for row in rows:
        writer.writerow([_safe_cell(v) for v in row])
    return Response(out.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}"'})


def _month_keys(months: int, now: datetime) -> list[str]:
    keys = []
    year, month = now.year, now.month
    for _ in range(months):
        keys.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return list(reversed(keys))


def _key(stamp: datetime) -> str:
    return f"{stamp.year:04d}-{stamp.month:02d}"


# ---- analytics ---------------------------------------------------------------------------------------------------------------


@router.get("/platform/analytics")
async def analytics(months: int = Query(12, ge=3, le=36), principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    """The numbers a business owner would ask of their own company: recurring revenue, growth, conversion, churn, what is owed to us."""
    now = datetime.now(UTC)
    facts = await _facts(db)
    states: dict[str, int] = defaultdict(int)
    mrr = paying = 0
    plans: dict[str, int] = defaultdict(int)
    for f in facts.values():
        states[f["access"]["state"]] += 1
        for p in f["plans"]:
            plans[p] += 1
        if f["access"]["state"] in ("active", "grace") and not f["business"].complimentary:
            mrr += f["monthly_cents"]
            paying += 1
    keys = _month_keys(months, now)
    since = datetime(int(keys[0][:4]), int(keys[0][5:]), 1, tzinfo=UTC)
    paid = (await db.execute(_all(select(SubscriptionInvoice).where(SubscriptionInvoice.status == "paid", SubscriptionInvoice.paid_at >= since)))).scalars().all()
    revenue = {k: {"month": k, "subscription_cents": 0, "sms_cents": 0, "invoices": 0} for k in keys}
    for i in paid:
        row = revenue.get(_key(i.paid_at))
        if row is not None:
            row["sms_cents" if i.kind == "sms_bundle" else "subscription_cents"] += i.total_cents
            row["invoices"] += 1
    created = (await db.execute(select(Business.created_at).where(Business.created_at >= since))).scalars().all()
    signups = {k: 0 for k in keys}
    for c in created:
        if _key(c) in signups:
            signups[_key(c)] += 1
    cancelled_at = (await db.execute(_all(select(Subscription.cancelled_at).where(Subscription.cancelled_at.is_not(None), Subscription.cancelled_at >= since)))).scalars().all()
    cancellations = {k: 0 for k in keys}
    for c in cancelled_at:
        if _key(c) in cancellations:
            cancellations[_key(c)] += 1
    thirty = now - timedelta(days=30)
    new_30 = (await db.execute(select(func.count()).select_from(Business).where(Business.created_at >= thirty))).scalar_one()
    churned_30 = (await db.execute(_all(select(func.count()).select_from(Subscription).where(Subscription.cancelled_at >= thirty)))).scalar_one()
    collected_30 = (await db.execute(_all(select(func.coalesce(func.sum(SubscriptionInvoice.total_cents), 0)).where(SubscriptionInvoice.status == "paid", SubscriptionInvoice.paid_at >= thirty)))).scalar_one()
    today = datetime.now(NAIROBI).date()
    outstanding = (await db.execute(_all(select(func.coalesce(func.sum(SubscriptionInvoice.total_cents), 0)).where(SubscriptionInvoice.status == "issued")))).scalar_one()
    overdue = (await db.execute(_all(select(func.coalesce(func.sum(SubscriptionInvoice.total_cents), 0)).where(SubscriptionInvoice.status == "issued", SubscriptionInvoice.due_date < today)))).scalar_one()
    ever_paid = {b for b in (await db.execute(_all(select(SubscriptionInvoice.business_id).where(SubscriptionInvoice.status == "paid", SubscriptionInvoice.kind == "subscription")))).scalars()}
    past_trial = [f for f in facts.values() if not f["business"].complimentary and f["sub"] is not None and f["sub"].trial_ends_at < now]
    converted = sum(1 for f in past_trial if f["business"].id in ever_paid)
    methods: dict[str, int] = defaultdict(int)
    for i in paid:
        if i.paid_at >= now - timedelta(days=90):
            methods[i.payment_method or "other"] += i.total_cents
    top = sorted((f for f in facts.values() if f["access"]["state"] in ("active", "grace") and not f["business"].complimentary), key=lambda f: -f["monthly_cents"])[:10]
    return {
        "kpis": {
            "mrr_cents": mrr, "arr_cents": mrr * 12, "paying": paying, "arpa_cents": mrr // paying if paying else 0, "businesses": len(facts), "vehicles": sum(plans.values()),
            "new_30d": int(new_30), "churned_30d": int(churned_30), "collected_30d_cents": int(collected_30), "outstanding_cents": int(outstanding), "overdue_cents": int(overdue),
            "trial_conversion_pct": round(100 * converted / len(past_trial)) if past_trial else None, "past_trial": len(past_trial), "converted": converted,
        },
        "states": dict(states), "vehicles_by_plan": dict(plans), "revenue": list(revenue.values()), "signups": [{"month": k, "count": signups[k]} for k in keys],
        "cancellations": [{"month": k, "count": cancellations[k]} for k in keys], "payment_methods": dict(methods),
        "top_customers": [{"id": f["business"].id, "name": f["business"].name, "monthly_cents": f["monthly_cents"], "vehicles": len(f["plans"]), "period": f["sub"].period if f["sub"] else "monthly"} for f in top],
    }  # fmt: skip


@router.get("/platform/attention")
async def attention(principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    """What needs a person today, most urgent first: each item says how many and where to go."""
    now = datetime.now(UTC)
    today = datetime.now(NAIROBI).date()
    facts = await _facts(db)
    items: list[dict] = []

    def add(key: str, label: str, count: int, severity: str, link: str) -> None:
        if count:
            items.append({"key": key, "label": label, "count": int(count), "severity": severity, "link": link})

    from app.routers.breaches import out as breach_out

    breaches = [breach_out(x) for x in (await db.execute(select(BreachIncident).where(BreachIncident.status != "closed"))).scalars()]
    overdue_breaches = sum(1 for x in breaches if x["odpc_overdue"])
    add("breaches_overdue", "Data breaches past the Commissioner's 72 hours", overdue_breaches, "red", "/platform/breaches")
    add("etims_review", "Our tax invoices KRA refused or that keep failing", (await db.execute(select(func.count()).select_from(PlatformEtimsSubmission).where(PlatformEtimsSubmission.status == "needs_review"))).scalar_one(), "red", "/platform/kra")
    add("invoices_overdue", "Invoices unpaid past their due date", (await db.execute(_all(select(func.count()).select_from(SubscriptionInvoice).where(SubscriptionInvoice.status == "issued", SubscriptionInvoice.due_date < today)))).scalar_one(), "amber", "/platform/invoices?status=overdue")
    add("read_only", "Customers read-only for non-payment", sum(1 for f in facts.values() if f["access"]["state"] == "read_only"), "amber", "/platform/renewals?category=overdue")
    add("grace", "Customers in their week of grace", sum(1 for f in facts.values() if f["access"]["state"] == "grace"), "amber", "/platform/renewals?category=overdue")
    add("trials_ending", "Trials ending within 3 days", sum(1 for f in facts.values() if f["access"]["state"] == "trialing" and (f["access"].get("days_left") or 99) <= 3), "amber", "/platform/renewals?category=trial")
    add("breaches_open", "Open data breaches", len(breaches), "amber", "/platform/breaches")
    add("partners_pending", "Partner applications waiting", (await db.execute(select(func.count()).select_from(Partner).where(Partner.status == "pending"))).scalar_one(), "amber", "/platform/partners")
    add("feedback_new", "Feedback not yet read", (await db.execute(_all(select(func.count()).select_from(Feedback).where(Feedback.status == "new")))).scalar_one(), "blue", "/platform/feedback")
    add("whatsapp_failed", "WhatsApp messages that failed in the last day", (await db.execute(_all(select(func.count()).select_from(WhatsAppMessage).where(WhatsAppMessage.status == "failed", WhatsAppMessage.created_at >= now - DAY)))).scalar_one(), "blue", "/platform/system")
    add("suspended", "Customers on hold", sum(1 for f in facts.values() if f["access"]["state"] == "suspended"), "blue", "/platform/customers?state=suspended")
    order = {"red": 0, "amber": 1, "blue": 2}
    return sorted(items, key=lambda i: (order[i["severity"]], -i["count"]))


# ---- renewals ----------------------------------------------------------------------------------------------------------------


def _renewal_row(f: dict, now: datetime, owner: User | None, open_invoice: SubscriptionInvoice | None) -> dict | None:
    b, sub, a = f["business"], f["sub"], f["access"]
    if b.complimentary:
        return None
    ends = sub.paid_until if sub is not None and sub.paid_until is not None else (sub.trial_ends_at if sub is not None else None)
    if ends is None:
        return None
    days = math.ceil((ends - now).total_seconds() / 86400)
    state = a["state"]
    category = "overdue" if state in ("grace", "read_only") else "trial" if state == "trialing" else "suspended" if state == "suspended" else "renewing"
    return {
        "id": b.id, "name": b.name, "state": state, "category": category, "ends_at": ends, "days_left": days, "period": sub.period if sub else "monthly", "monthly_cents": f["monthly_cents"],
        "vehicles": len(f["plans"]), "cancelled": bool(sub and sub.cancelled_at), "owner": {"name": owner.name, "email": owner.email, "phone": owner.phone} if owner else None,
        "open_invoice": {"id": open_invoice.id, "number": open_invoice.number, "total_cents": open_invoice.total_cents, "due_date": open_invoice.due_date} if open_invoice else None,
    }  # fmt: skip


@router.get("/platform/renewals")
async def renewals(
    window: int = Query(30, ge=1, le=365), category: Literal["all", "overdue", "trial", "renewing"] = "all", principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)
):
    """Every paying or trialing customer by the date its paid time or trial ends: overdue first, then the soonest. `window` is how many days
    ahead to look; overdue customers are always shown."""
    now = datetime.now(UTC)
    facts = await _facts(db)
    owners: dict[uuid.UUID, User] = {}
    for m, u in (await db.execute(_all(select(Membership, User).join(User, User.id == Membership.user_id).order_by(Membership.created_at)))).all():
        owners.setdefault(m.business_id, u)
    open_invoices: dict[uuid.UUID, SubscriptionInvoice] = {}
    for i in (await db.execute(_all(select(SubscriptionInvoice).where(SubscriptionInvoice.status == "issued", SubscriptionInvoice.kind == "subscription").order_by(SubscriptionInvoice.created_at)))).scalars():
        open_invoices[i.business_id] = i
    rows = [r for f in facts.values() if (r := _renewal_row(f, now, owners.get(f["business"].id), open_invoices.get(f["business"].id)))]
    rows = [r for r in rows if r["category"] == "overdue" or r["days_left"] <= window]
    if category != "all":
        rows = [r for r in rows if r["category"] == category]
    rows.sort(key=lambda r: (r["category"] != "overdue", r["days_left"]))
    due = [r for r in rows if r["category"] != "overdue"]
    return {
        "window": window, "rows": rows,
        "totals": {"overdue": sum(r["category"] == "overdue" for r in rows), "trial": sum(r["category"] == "trial" for r in rows), "renewing": sum(r["category"] == "renewing" for r in rows),
                   "expected_cents": sum(r["monthly_cents"] for r in due if r["category"] == "renewing"), "at_risk_cents": sum(r["monthly_cents"] for r in rows if r["category"] == "overdue")},
    }  # fmt: skip


# ---- one customer's subscription ---------------------------------------------------------------------------------------------


def _invoice_row(i: SubscriptionInvoice, business: str | None = None, tax: str | None = None) -> dict:
    today = datetime.now(NAIROBI).date()
    return {
        "id": i.id, "number": i.number, "business_id": i.business_id, "business": business, "kind": i.kind, "status": i.status, "total_cents": i.total_cents, "billing_period": i.billing_period,
        "sms_messages": i.sms_messages, "period_start": i.period_start, "period_end": i.period_end, "due_date": i.due_date, "created_at": i.created_at, "paid_at": i.paid_at,
        "payment_method": i.payment_method, "reference": i.mpesa_code, "overdue": i.status == "issued" and i.due_date < today, "tax_invoice": tax,
    }  # fmt: skip


@router.get("/platform/businesses/{business_id}/subscription")
async def subscription_detail(business_id: uuid.UUID, principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    """The whole of one customer's subscription: where it stands, what it would cost today, every vehicle's plan, every invoice and payment."""
    f = await _one(db, business_id)
    b = f["business"]
    async with in_business(business_id):
        sub = await subscriptions.get_or_start(db, b)
        access = await subscriptions.access_for(db, business_id)
        vehicles = await subscriptions.active_vehicles(db)
        employees = int((await db.execute(select(func.count()).select_from(Membership).where(Membership.status == MembershipStatus.ACTIVE))).scalar_one())
        quote = await subscriptions.current_quote(db, sub, employees)
        annual = await subscriptions.current_quote(db, sub, employees, "annual")
        invoices = list((await db.execute(select(SubscriptionInvoice).order_by(SubscriptionInvoice.created_at.desc()).limit(100))).scalars())
        payments = list((await db.execute(select(SubscriptionPayment).order_by(SubscriptionPayment.created_at.desc()).limit(30))).scalars())
        sms = await subscriptions.sms_account(db)
        grant = (await db.execute(select(SupportGrant).where(SupportGrant.revoked_at.is_(None), SupportGrant.expires_at > datetime.now(UTC)).order_by(SupportGrant.expires_at.desc()))).scalars().first()
    await db.commit()  # a customer from before subscriptions existed has its trial recorded the first time it is looked at
    taxed = {r.subscription_invoice_id: r.status for r in (await db.execute(select(PlatformEtimsSubmission).where(PlatformEtimsSubmission.business_id == business_id))).scalars()}
    return {
        "business": _row(f), "access": access, "complimentary": b.complimentary, "suspended": b.suspended_at is not None, "suspended_reason": b.suspended_reason,
        "subscription": {"trial_ends_at": sub.trial_ends_at, "paid_until": sub.paid_until, "period": sub.period, "payroll_enabled": sub.payroll_enabled, "custom_monthly_cents": sub.custom_monthly_cents, "cancelled_at": sub.cancelled_at,
                         "data_removed_on": sub.cancelled_at + timedelta(days=settings.cancelled_grace_days) if sub.cancelled_at else None, "created_at": sub.created_at},
        "quote": quote, "annual_quote": annual, "payroll_employees": employees,
        "vehicles": [{"vehicle_id": v.id, "registration": v.registration, "plan": v.plan, "effective_plan": subscriptions.effective_plan(v.plan, access)} for v in vehicles],
        "invoices": [_invoice_row(i, b.name, taxed.get(i.id)) for i in invoices],
        "payments": [{"id": p.id, "invoice_id": p.invoice_id, "method": p.method, "status": p.status, "amount_cents": p.amount_cents, "note": p.result_note, "created_at": p.created_at, "answered_at": p.answered_at} for p in payments],
        "sms": sms, "support_grant": {"active": True, "expires_at": grant.expires_at} if grant else {"active": False, "expires_at": None},
    }  # fmt: skip


class ReasonIn(BaseModel):
    reason: str = Field(min_length=3, max_length=255)


class SubscriptionEditIn(BaseModel):
    """Corrects what is recorded. Only the fields sent are changed; `paid_until` and `custom_monthly_cents` can be sent as null to clear them."""

    reason: str = Field(min_length=3, max_length=255)
    period: Literal["monthly", "annual"] | None = None
    payroll_enabled: bool | None = None
    paid_until: datetime | None = None
    trial_ends_at: datetime | None = None
    custom_monthly_cents: int | None = Field(default=None, ge=100_000, le=1_000_000_000)


class AdvanceIn(BaseModel):
    months: int = Field(default=0, ge=0, le=36)
    days: int = Field(default=0, ge=0, le=1100)
    reason: str = Field(min_length=3, max_length=255)


def _aware(stamp: datetime) -> datetime:
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)


@router.put("/platform/businesses/{business_id}/subscription")
async def edit_subscription(business_id: uuid.UUID, body: SubscriptionEditIn, principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    """Sets the paid-until date, the trial end, the billing period, payroll or the agreed price by hand, for a correction or a deal. Everything
    changed is written, with the old and new value and the reason, into the customer's own audit trail."""
    f = await _one(db, business_id)
    sent = body.model_fields_set - {"reason"}
    if not sent:
        raise error(422, "nothing_to_change", "Send at least one thing to change.")
    far = datetime.now(UTC) + timedelta(days=366 * 5)
    for name in ("paid_until", "trial_ends_at"):
        value = getattr(body, name)
        if value is not None and _aware(value) > far:
            raise error(422, "too_far", "That date is more than five years away.")
    if "trial_ends_at" in sent and body.trial_ends_at is None:
        raise error(422, "trial_needed", "A trial end date cannot be cleared.")
    before: dict = {}
    after: dict = {}
    async with in_business(business_id):
        sub = await subscriptions.get_or_start(db, f["business"])
        for name in ("period", "payroll_enabled", "paid_until", "trial_ends_at", "custom_monthly_cents"):
            if name in sent:
                new = getattr(body, name)
                new = _aware(new) if isinstance(new, datetime) else new
                old = getattr(sub, name)
                if old != new:
                    before[name], after[name] = _iso(old) if isinstance(old, datetime) else old, _iso(new) if isinstance(new, datetime) else new
                    setattr(sub, name, new)
        if "paid_until" in after:
            sub.last_notice = None  # the next period's reminders start afresh
    if not after:
        raise error(status.HTTP_409_CONFLICT, "no_change", "That is already how it is.")
    current_business_id.set(business_id)
    try:
        audit.record(db, actor_user_id=principal.user.id, action="platform.subscription_edited", entity_type="business", entity_id=business_id, before=before, after=after, note=body.reason)
        await db.commit()
    finally:
        current_business_id.set(None)
    return await subscription_detail(business_id, principal, db)


@router.post("/platform/businesses/{business_id}/subscription/advance")
async def advance_subscription(business_id: uuid.UUID, body: AdvanceIn, principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    """Moves the renewal date forward by months and days without an invoice (a goodwill month, a delay on our side, a settled dispute). It
    counts from the current paid-until date, or from today if that has passed or nothing has been paid."""
    if body.months == 0 and body.days == 0:
        raise error(422, "nothing_to_change", "Say how many months or days.")
    f = await _one(db, business_id)
    now = datetime.now(UTC)
    async with in_business(business_id):
        sub = await subscriptions.get_or_start(db, f["business"])
        old = sub.paid_until
        start = old if old is not None and old > now else now
        local = start.astimezone(NAIROBI)
        moved = datetime.combine(add_months(local.date(), body.months), local.timetz()).astimezone(UTC) + timedelta(days=body.days)
        sub.paid_until, sub.last_notice = moved, None
    current_business_id.set(business_id)
    try:
        audit.record(db, actor_user_id=principal.user.id, action="platform.subscription_advanced", entity_type="business", entity_id=business_id, before={"paid_until": _iso(old)}, after={"paid_until": _iso(moved), "months": body.months, "days": body.days}, note=body.reason)
        await db.commit()
    finally:
        current_business_id.set(None)
    return await subscription_detail(business_id, principal, db)


@router.post("/platform/businesses/{business_id}/subscription/cancel")
async def platform_cancel(business_id: uuid.UUID, body: ReasonIn, principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    """Ends the subscription on the customer's behalf (they asked by phone or email). Read-only at once; personal data is removed after the grace period."""
    f = await _one(db, business_id)
    async with in_business(business_id):
        sub = await subscriptions.get_or_start(db, f["business"])
        if sub.cancelled_at is not None:
            raise error(status.HTTP_409_CONFLICT, "already_cancelled", "This subscription is already cancelled.")
        sub.cancelled_at = datetime.now(UTC)
    current_business_id.set(business_id)
    try:
        audit.record(db, actor_user_id=principal.user.id, action="platform.subscription_cancelled", entity_type="business", entity_id=business_id, note=body.reason)
        await db.commit()
    finally:
        current_business_id.set(None)
    return await subscription_detail(business_id, principal, db)


@router.post("/platform/businesses/{business_id}/subscription/reactivate")
async def platform_reactivate(business_id: uuid.UUID, body: ReasonIn, principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    f = await _one(db, business_id)
    async with in_business(business_id):
        sub = await subscriptions.get_or_start(db, f["business"])
        if sub.cancelled_at is None:
            raise error(status.HTTP_409_CONFLICT, "not_cancelled", "This subscription is not cancelled.")
        sub.cancelled_at = None
    current_business_id.set(business_id)
    try:
        audit.record(db, actor_user_id=principal.user.id, action="platform.subscription_reactivated", entity_type="business", entity_id=business_id, note=body.reason)
        await db.commit()
    finally:
        current_business_id.set(None)
    return await subscription_detail(business_id, principal, db)


class VehiclePlanIn(BaseModel):
    plan: Literal["starter", "standard", "premium"]
    reason: str = Field(min_length=3, max_length=255)


@router.put("/platform/businesses/{business_id}/vehicles/{vehicle_id}/plan")
async def set_vehicle_plan(business_id: uuid.UUID, vehicle_id: uuid.UUID, body: VehiclePlanIn, principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    """Changes the plan one of the customer's vehicles is billed at. Applies at once and is billed on the next invoice."""
    await _one(db, business_id)
    async with in_business(business_id):
        vehicle = (await db.execute(select(Vehicle).where(Vehicle.id == vehicle_id))).scalar_one_or_none()
        if vehicle is None:
            raise error(status.HTTP_404_NOT_FOUND, "not_found", "That vehicle was not found.")
        if vehicle.plan == body.plan:
            raise error(status.HTTP_409_CONFLICT, "no_change", "That vehicle is already on that plan.")
        old, registration = vehicle.plan, vehicle.registration
        vehicle.plan = body.plan
    current_business_id.set(business_id)
    try:
        audit.record(db, actor_user_id=principal.user.id, action="platform.vehicle_plan_changed", entity_type="business", entity_id=business_id, before={"plan": old}, after={"plan": body.plan, "registration": registration}, note=body.reason)
        await db.commit()
    finally:
        current_business_id.set(None)
    return await subscription_detail(business_id, principal, db)


class InvoiceIn(BaseModel):
    kind: Literal["subscription", "sms_bundle"] = "subscription"
    messages: int | None = None
    total_cents: int | None = Field(default=None, ge=100, le=1_000_000_000_00)  # a negotiated amount instead of the price list
    reason: str = Field(min_length=3, max_length=255)


@router.post("/platform/businesses/{business_id}/invoices", status_code=status.HTTP_201_CREATED)
async def raise_invoice_for(business_id: uuid.UUID, body: InvoiceIn, principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    """Raises the next invoice for a customer from the plans its vehicles are on now (or a text bundle), optionally at an agreed total."""
    f = await _one(db, business_id)
    async with in_business(business_id):
        sub = await subscriptions.get_or_start(db, f["business"])
        if body.kind == "sms_bundle":
            if body.messages not in plan_rules.SMS_BUNDLES:
                raise error(422, "bad_bundle", f"The bundle must be one of: {', '.join(str(m) for m in plan_rules.SMS_BUNDLES)}.")
            invoice = await subscriptions.raise_sms_invoice(db, body.messages)
        else:
            if await subscriptions.open_invoice(db) is not None:
                raise error(status.HTTP_409_CONFLICT, "invoice_open", "That customer already has an invoice waiting for payment. Void it first to raise another.")
            employees = int((await db.execute(select(func.count()).select_from(Membership).where(Membership.status == MembershipStatus.ACTIVE))).scalar_one())
            quote = await subscriptions.current_quote(db, sub, employees)
            if quote["vehicles"] == 0:
                raise error(422, "no_vehicles", "That customer has no vehicles yet: the subscription is priced per vehicle.")
            if quote["custom"] and body.total_cents is None:
                raise error(422, "custom_pricing", "A fleet of 31 or more vehicles is priced by agreement: set its custom price first, or give the total.")
            invoice = await subscriptions.raise_invoice(db, sub, quote)
        if body.total_cents is not None:
            invoice.total_cents = body.total_cents
            invoice.quote = {**(invoice.quote or {}), "agreed_total_cents": body.total_cents, "total_cents": body.total_cents}
        await db.flush()
    current_business_id.set(business_id)
    try:
        audit.record(db, actor_user_id=principal.user.id, action="platform.invoice_raised", entity_type="subscription_invoice", entity_id=invoice.id, after={"number": invoice.number, "kind": invoice.kind, "total_cents": invoice.total_cents}, note=body.reason)
        await db.commit()
    finally:
        current_business_id.set(None)
    return _invoice_row(invoice, f["business"].name)


@router.post("/platform/invoices/{invoice_id}/void")
async def void_invoice(invoice_id: uuid.UUID, body: ReasonIn, principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    """Cancels an invoice nobody has paid (raised by mistake, a deal that changed). A paid invoice cannot be voided: it needs a refund, outside FleetTms."""
    invoice = (await db.execute(_all(select(SubscriptionInvoice).where(SubscriptionInvoice.id == invoice_id).with_for_update()))).scalar_one_or_none()
    if invoice is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That invoice was not found.")
    if invoice.status != "issued":
        raise error(status.HTTP_409_CONFLICT, "not_voidable", "Only an invoice waiting for payment can be voided.")
    current_business_id.set(invoice.business_id)
    try:
        invoice.status = "void"
        await db.execute(update(SubscriptionPayment).where(SubscriptionPayment.invoice_id == invoice.id, SubscriptionPayment.status == "pending").values(status="failed", result_note="The invoice was voided."))
        audit.record(db, actor_user_id=principal.user.id, action="platform.invoice_voided", entity_type="subscription_invoice", entity_id=invoice.id, after={"number": invoice.number, "total_cents": invoice.total_cents}, note=body.reason)
        await db.commit()
    finally:
        current_business_id.set(None)
    return _invoice_row(invoice)


@router.post("/platform/businesses/{business_id}/remind")
async def remind_now(business_id: uuid.UUID, principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    """Texts the owner and managers the reminder that fits where the account is now (trial ending, renewal due, overdue), without waiting
    for the daily pass. A customer that needs no reminder is told so rather than texted."""
    f = await _one(db, business_id)
    if f["business"].complimentary:
        raise error(status.HTTP_409_CONFLICT, "nothing_to_send", "A free account has nothing to be reminded about.")
    due = subscriptions.notice_for(f["access"])
    if due is None:
        raise error(status.HTTP_409_CONFLICT, "nothing_to_send", "That customer is not near a renewal, so there is nothing to remind them of.")
    key, text = due
    sent = 0
    async with in_business(business_id):
        for m in (await db.execute(select(Membership).where(Membership.status == MembershipStatus.ACTIVE))).scalars():
            if {r.role for r in m.roles} & {Role.OWNER, Role.MANAGER} and m.user.phone:
                await get_sms_sender().send(m.user.phone, text)
                sent += 1
    if sent == 0:
        raise error(status.HTTP_409_CONFLICT, "no_phone", "Neither the owner nor a manager has a phone number to text.")
    current_business_id.set(business_id)
    try:
        audit.record(db, actor_user_id=principal.user.id, action="platform.reminder_sent", entity_type="business", entity_id=business_id, after={"notice": key, "texts": sent})
        await db.commit()
    finally:
        current_business_id.set(None)
    return {"sent": sent, "notice": key}


class BusinessEditIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    kra_pin: str | None = Field(default=None, max_length=20)
    reason: str = Field(min_length=3, max_length=255)


@router.put("/platform/businesses/{business_id}")
async def edit_business(business_id: uuid.UUID, body: BusinessEditIn, principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    """Corrects the business's name or KRA PIN (a typo at sign-up, a rename). The old value is kept in the customer's audit trail."""
    f = await _one(db, business_id)
    b = f["business"]
    sent = body.model_fields_set - {"reason"}
    before, after = {}, {}
    if "name" in sent and body.name is not None and body.name.strip() != b.name:
        before["name"], after["name"] = b.name, body.name.strip()
        b.name = body.name.strip()
    if "kra_pin" in sent:
        pin = (body.kra_pin or "").strip().upper() or None
        if pin != b.kra_pin:
            before["kra_pin"], after["kra_pin"] = b.kra_pin, pin
            b.kra_pin = pin
    if not after:
        raise error(status.HTTP_409_CONFLICT, "no_change", "That is already how it is.")
    current_business_id.set(business_id)
    try:
        audit.record(db, actor_user_id=principal.user.id, action="platform.business_edited", entity_type="business", entity_id=business_id, before=before, after=after, note=body.reason)
        await db.commit()
    finally:
        current_business_id.set(None)
    return _row((await _facts(db))[business_id])


# ---- the invoice ledger ------------------------------------------------------------------------------------------------------


def _invoice_clauses(status_filter: str | None, kind: str | None, q: str | None, business_id: uuid.UUID | None, start: date | None, end: date | None) -> list:
    today = datetime.now(NAIROBI).date()
    clauses: list = []
    if status_filter == "overdue":
        clauses += [SubscriptionInvoice.status == "issued", SubscriptionInvoice.due_date < today]
    elif status_filter in ("issued", "paid", "void"):
        clauses.append(SubscriptionInvoice.status == status_filter)
    if kind in ("subscription", "sms_bundle"):
        clauses.append(SubscriptionInvoice.kind == kind)
    if business_id:
        clauses.append(SubscriptionInvoice.business_id == business_id)
    if q:
        like = f"%{q.strip()}%"
        clauses.append(or_(SubscriptionInvoice.number.ilike(like), Business.name.ilike(like), SubscriptionInvoice.mpesa_code.ilike(like)))
    if start:
        clauses.append(SubscriptionInvoice.created_at >= datetime.combine(start, datetime.min.time(), tzinfo=NAIROBI))
    if end:
        clauses.append(SubscriptionInvoice.created_at < datetime.combine(end + DAY, datetime.min.time(), tzinfo=NAIROBI))
    return clauses


@router.get("/platform/invoices")
async def invoice_ledger(
    status_filter: str | None = Query(None, alias="status"), kind: str | None = None, q: str | None = None, business_id: uuid.UUID | None = None, start: date | None = None, end: date | None = None,
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db),
):  # fmt: skip
    """Every invoice FleetTms has raised, across customers, with filters, totals and paging."""
    clauses = _invoice_clauses(status_filter, kind, q, business_id, start, end)
    joined = select(SubscriptionInvoice, Business.name).join(Business, Business.id == SubscriptionInvoice.business_id).where(*clauses)
    total = (await db.execute(_all(select(func.count()).select_from(SubscriptionInvoice).join(Business, Business.id == SubscriptionInvoice.business_id).where(*clauses)))).scalar_one()
    sums = (await db.execute(_all(select(SubscriptionInvoice.status, func.coalesce(func.sum(SubscriptionInvoice.total_cents), 0), func.count()).join(Business, Business.id == SubscriptionInvoice.business_id).where(*clauses).group_by(SubscriptionInvoice.status)))).all()
    rows = (await db.execute(_all(joined.order_by(SubscriptionInvoice.created_at.desc()).offset((page - 1) * page_size).limit(page_size)))).all()
    ids = [i.id for i, _ in rows]
    taxed = {r.subscription_invoice_id: r.status for r in (await db.execute(select(PlatformEtimsSubmission).where(PlatformEtimsSubmission.subscription_invoice_id.in_(ids)))).scalars()} if ids else {}
    return {
        "total": int(total), "page": page, "page_size": page_size, "pages": max(1, math.ceil(total / page_size)),
        "sums": {s: {"cents": int(c), "count": int(n)} for s, c, n in sums}, "rows": [_invoice_row(i, name, taxed.get(i.id)) for i, name in rows],
    }  # fmt: skip


@router.get("/platform/invoices.csv")
async def invoice_csv(
    status_filter: str | None = Query(None, alias="status"), kind: str | None = None, q: str | None = None, business_id: uuid.UUID | None = None, start: date | None = None, end: date | None = None,
    principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db),
):  # fmt: skip
    joined = select(SubscriptionInvoice, Business.name).join(Business, Business.id == SubscriptionInvoice.business_id).where(*_invoice_clauses(status_filter, kind, q, business_id, start, end))
    rows = (await db.execute(_all(joined.order_by(SubscriptionInvoice.created_at.desc()).limit(20000)))).all()
    return _csv(
        "fleettms-invoices.csv", ["number", "customer", "kind", "status", "total_kes", "issued", "due", "paid", "method", "reference"],
        [[i.number, name, i.kind, i.status, f"{i.total_cents / 100:.2f}", _iso(i.created_at.date()), _iso(i.due_date), _iso(i.paid_at.date() if i.paid_at else None), i.payment_method or "", i.mpesa_code or ""] for i, name in rows],
    )  # fmt: skip


@router.get("/platform/customers.csv")
async def customer_csv(principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    facts = await _facts(db)
    rows = []
    for f in sorted(facts.values(), key=lambda f: f["business"].name.lower()):
        r = _row(f)
        rows.append([r["name"], r["state"], r["vehicles"], r["people"], r["period"], f"{r['monthly_cents'] / 100:.2f}", _iso(r["trial_ends_at"]), _iso(r["paid_until"]), _iso(r["created_at"].date())])
    return _csv("fleettms-customers.csv", ["name", "state", "vehicles", "people", "period", "monthly_kes", "trial_ends", "paid_until", "joined"], rows)


# ---- notes -------------------------------------------------------------------------------------------------------------------


class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)
    pinned: bool = False


class NotePatch(BaseModel):
    body: str | None = Field(default=None, min_length=1, max_length=2000)
    pinned: bool | None = None


async def _note_out(db: AsyncSession, notes: list[PlatformNote]) -> list[dict]:
    names = {u.id: u.name for u in (await db.execute(select(User).where(User.id.in_([n.author_user_id for n in notes if n.author_user_id])))).scalars()} if notes else {}
    return [{"id": n.id, "business_id": n.business_id, "body": n.body, "pinned": n.pinned, "author": names.get(n.author_user_id), "created_at": n.created_at, "updated_at": n.updated_at} for n in notes]


@router.get("/platform/businesses/{business_id}/notes")
async def list_notes(business_id: uuid.UUID, principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    await _one(db, business_id)
    notes = list((await db.execute(select(PlatformNote).where(PlatformNote.business_id == business_id).order_by(PlatformNote.pinned.desc(), PlatformNote.created_at.desc()))).scalars())
    return await _note_out(db, notes)


@router.post("/platform/businesses/{business_id}/notes", status_code=status.HTTP_201_CREATED)
async def add_note(business_id: uuid.UUID, body: NoteIn, principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    await _one(db, business_id)
    note = PlatformNote(business_id=business_id, author_user_id=principal.user.id, body=body.body.strip(), pinned=body.pinned)
    db.add(note)
    await db.flush()
    log_action(db, principal, "note.added", "platform_note", note.id, business_id)
    await db.commit()
    return (await _note_out(db, [note]))[0]


async def _note(db: AsyncSession, note_id: uuid.UUID) -> PlatformNote:
    note = (await db.execute(select(PlatformNote).where(PlatformNote.id == note_id))).scalar_one_or_none()
    if note is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That note was not found.")
    return note


@router.put("/platform/notes/{note_id}")
async def edit_note(note_id: uuid.UUID, body: NotePatch, principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    note = await _note(db, note_id)
    if body.body is not None:
        note.body = body.body.strip()
    if body.pinned is not None:
        note.pinned = body.pinned
    log_action(db, principal, "note.edited", "platform_note", note.id, note.business_id)
    await db.commit()
    return (await _note_out(db, [note]))[0]


@router.delete("/platform/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(note_id: uuid.UUID, principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    note = await _note(db, note_id)
    log_action(db, principal, "note.deleted", "platform_note", note.id, note.business_id)
    await db.delete(note)
    await db.commit()


# ---- who may run the console -------------------------------------------------------------------------------------------------


class AdminIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)


def _admin_out(u: User) -> dict:
    return {"id": u.id, "name": u.name, "email": u.email, "phone": u.phone, "active": u.is_active, "created_at": u.created_at}


@router.get("/platform/admins")
async def list_admins(principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    admins = (await db.execute(select(User).where(User.is_platform_admin.is_(True)).order_by(User.created_at))).scalars().all()
    return [{**_admin_out(u), "you": u.id == principal.user.id} for u in admins]


@router.post("/platform/admins", status_code=status.HTTP_201_CREATED)
async def add_admin(body: AdminIn, principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    """Gives an existing user the console. They must already have an account (and two-step sign-in, which every session needs anyway)."""
    user = (await db.execute(select(User).where(func.lower(User.email) == body.email.strip().lower()))).scalar_one_or_none()
    if user is None or not user.is_active:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "No active user has that email address. They must sign up first.")
    if user.is_platform_admin:
        raise error(status.HTTP_409_CONFLICT, "already_admin", "That user already runs the console.")
    user.is_platform_admin = True
    log_action(db, principal, "admin.granted", "user", user.id, detail={"email": user.email})
    await db.commit()
    return _admin_out(user)


@router.delete("/platform/admins/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_admin(user_id: uuid.UUID, principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    """Takes the console away from a user, and ends any support session they have open. Not yourself, and never the last admin."""
    if user_id == principal.user.id:
        raise error(status.HTTP_409_CONFLICT, "self", "You cannot remove your own access. Ask another admin to.")
    user = (await db.execute(select(User).where(User.id == user_id, User.is_platform_admin.is_(True)))).scalar_one_or_none()
    if user is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That user does not run the console.")
    if (await db.execute(select(func.count()).select_from(User).where(User.is_platform_admin.is_(True)))).scalar_one() <= 1:
        raise error(status.HTTP_409_CONFLICT, "last_admin", "There must always be one admin.")
    user.is_platform_admin = False
    await db.execute(update(AuthSession).where(AuthSession.user_id == user.id, AuthSession.support_access.is_(True), AuthSession.revoked_at.is_(None)).values(revoked_at=datetime.now(UTC)))
    log_action(db, principal, "admin.revoked", "user", user.id, detail={"email": user.email})
    await db.commit()


# ---- the platform's audit trail ----------------------------------------------------------------------------------------------


@router.get("/platform/audit")
async def platform_audit(
    source: Literal["all", "customers", "platform"] = "all", action: str | None = None, business_id: uuid.UUID | None = None, days: int = Query(30, ge=1, le=730),
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db),
):  # fmt: skip
    """What the platform has done, newest first: changes to customers' accounts (from their own trails) and the platform's own actions."""
    since = datetime.now(UTC) - timedelta(days=days)
    want = page * page_size
    entries: list[dict] = []
    businesses = {b.id: b.name for b in (await db.execute(select(Business))).scalars()}
    users = {u.id: u.name for u in (await db.execute(select(User).where(User.is_platform_admin.is_(True)))).scalars()}
    total = 0
    if source in ("all", "customers"):
        stmt = select(AuditLog).where(AuditLog.created_at >= since, or_(*[AuditLog.action.like(f"{p}%") for p in AUDIT_PREFIXES]))
        if action:
            stmt = stmt.where(AuditLog.action.like(f"{action}%"))
        if business_id:
            stmt = stmt.where(AuditLog.business_id == business_id)
        total += (await db.execute(_all(select(func.count()).select_from(stmt.subquery())))).scalar_one()
        for e in (await db.execute(_all(stmt.order_by(AuditLog.created_at.desc()).limit(want)))).scalars():
            entries.append({"id": e.id, "at": e.created_at, "source": "customer", "action": e.action, "actor": users.get(e.actor_user_id) if e.actor_user_id else "System", "business_id": e.business_id, "business": businesses.get(e.business_id),
                            "entity_type": e.entity_type, "entity_id": e.entity_id, "note": e.note, "before": e.before, "after": e.after})  # fmt: skip
    if source in ("all", "platform"):
        stmt = select(PlatformAction).where(PlatformAction.created_at >= since)
        if action:
            stmt = stmt.where(PlatformAction.action.like(f"{action}%"))
        if business_id:
            stmt = stmt.where(PlatformAction.business_id == business_id)
        total += (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        for e in (await db.execute(stmt.order_by(PlatformAction.created_at.desc()).limit(want))).scalars():
            entries.append({"id": e.id, "at": e.created_at, "source": "platform", "action": e.action, "actor": users.get(e.actor_user_id) if e.actor_user_id else "System", "business_id": e.business_id, "business": businesses.get(e.business_id) if e.business_id else None,
                            "entity_type": e.entity_type, "entity_id": e.entity_id, "note": None, "before": None, "after": e.detail})  # fmt: skip
    entries.sort(key=lambda e: e["at"], reverse=True)
    return {"total": int(total), "page": page, "page_size": page_size, "pages": max(1, math.ceil(total / page_size)), "rows": entries[(page - 1) * page_size : page * page_size]}


# ---- the feedback inbox ------------------------------------------------------------------------------------------------------


class FeedbackPatch(BaseModel):
    status: Literal["new", "read", "resolved"]
    note: str | None = Field(default=None, max_length=500)


@router.put("/platform/feedback/{feedback_id}")
async def handle_feedback(feedback_id: uuid.UUID, body: FeedbackPatch, principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    """Marks what a customer sent as read or resolved, with a note about what was done."""
    f = (await db.execute(_all(select(Feedback).where(Feedback.id == feedback_id)))).scalar_one_or_none()
    if f is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That feedback was not found.")
    current_business_id.set(f.business_id)
    try:
        f.status, f.handled_note = body.status, body.note
        f.handled_by_user_id, f.handled_at = (principal.user.id, datetime.now(UTC)) if body.status != "new" else (None, None)
        log_action(db, principal, f"feedback.{body.status}", "feedback", f.id, f.business_id)
        await db.commit()
    finally:
        current_business_id.set(None)
    return {"id": f.id, "status": f.status, "note": f.handled_note, "handled_at": f.handled_at}


# ---- system status -----------------------------------------------------------------------------------------------------------


@router.get("/platform/system")
async def system_status(principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    """Is everything working, and what is stuck: the readiness checks (database, queue, storage, worker, backups) and the work waiting on a person."""
    now = datetime.now(UTC)
    ready = await readiness.readiness()
    queue_depth = None
    heartbeat_age = None
    with suppress(Exception):  # the readiness checks already say if Redis is down
        from redis.asyncio import Redis

        client = Redis.from_url(settings.redis_url, socket_connect_timeout=2)
        queue_depth = int(await client.zcard("arq:queue"))
        beat = await client.get(readiness.HEARTBEAT_KEY)
        heartbeat_age = int(now.timestamp() - int(beat)) if beat else None
        await client.aclose()
    day = now - DAY
    return {
        "ready": ready["ready"], "failing": ready["failing"], "checks": ready["checks"], "version": settings.version, "environment": settings.environment, "checked_at": now,
        "queue": {"waiting": queue_depth, "worker_heartbeat_seconds": heartbeat_age},
        "integrations": {
            "sms": type(getattr(get_sms_sender(), "inner", get_sms_sender())).__name__, "etims_platform": platform_etims.enabled(), "storage": settings.storage_backend,
            "cards": bool(settings.paystack_secret_key), "whatsapp": bool(settings.whatsapp_token and settings.whatsapp_phone_number_id), "mpesa": bool(settings.platform_shortcode),
        },
        "stuck": {
            "etims_review": int((await db.execute(select(func.count()).select_from(PlatformEtimsSubmission).where(PlatformEtimsSubmission.status == "needs_review"))).scalar_one()),
            "etims_waiting": int((await db.execute(select(func.count()).select_from(PlatformEtimsSubmission).where(PlatformEtimsSubmission.status == "pending"))).scalar_one()),
            "whatsapp_failed_24h": int((await db.execute(_all(select(func.count()).select_from(WhatsAppMessage).where(WhatsAppMessage.status == "failed", WhatsAppMessage.created_at >= day)))).scalar_one()),
            "reminders_failed_24h": int((await db.execute(_all(select(func.count()).select_from(PaymentReminder).where(PaymentReminder.status == "failed", PaymentReminder.sent_at >= day)))).scalar_one()),
            "card_payments_pending": int((await db.execute(_all(select(func.count()).select_from(SubscriptionPayment).where(SubscriptionPayment.method == "card", SubscriptionPayment.status == "pending", SubscriptionPayment.created_at < now - timedelta(hours=1))))).scalar_one()),
        },
    }  # fmt: skip
