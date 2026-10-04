"""Subscriptions (masterplan Section 9): the 14 day trial, per-vehicle plans, invoices and M-Pesa payment, what a plan allows, and what
an account may still do once it has not paid. The rules are in app/plan_rules.py; this holds the database side. What an account may do
now is always worked out from its dates, never stored, so there is nothing to get out of step."""

import logging
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import plan_rules
from app.config import settings
from app.deps import error
from app.lease_rules import add_months
from app.models import (
    Business,
    SmsAccount,
    Subscription,
    SubscriptionInvoice,
    SubscriptionPayment,
    Vehicle,
)
from app.numbering import create_numbered
from app.reminders import NAIROBI
from app.tenancy import current_business_id

log = logging.getLogger(__name__)
READ_ONLY_OK = ("/auth/", "/subscription", "/data-exports", "/data-requests", "/me/data-requests", "/privacy", "/documents/accept", "/sos", "/me/sos", "/feedback", "/platform/")  # still allowed when read-only


def now_utc() -> datetime:
    return datetime.now(UTC)


async def subscription_of(db: AsyncSession) -> Subscription | None:
    return (await db.execute(select(Subscription))).scalars().first()


async def start_trial(db: AsyncSession, business: Business, now: datetime | None = None) -> Subscription:
    """A new business gets 14 days of everything in Standard, with no payment details."""
    now = now or now_utc()
    sub = Subscription(trial_ends_at=now + timedelta(days=plan_rules.TRIAL_DAYS))
    db.add(sub)
    await db.flush()
    return sub


async def get_or_start(db: AsyncSession, business: Business) -> Subscription:
    """A business that signed up before subscriptions existed has its trial counted from the day it was created."""
    sub = await subscription_of(db)
    if sub is None:
        sub = await start_trial(db, business, business.created_at)
    return sub


async def access_for(db: AsyncSession, business_id: uuid.UUID, now: datetime | None = None) -> dict:
    """What this business may do right now: full access, full access with a warning, or read-only."""
    now = now or now_utc()
    business = await db.get(Business, business_id)
    if business is None:
        return {"state": "read_only", "writable": False, "ends_at": None, "grace_ends_at": None, "days_left": 0, "complimentary": False, "suspended": False}
    if business.suspended_at is not None:
        return {"state": "suspended", "writable": False, "ends_at": None, "grace_ends_at": None, "days_left": 0, "complimentary": business.complimentary, "suspended": True, "reason": business.suspended_reason}
    sub = await subscription_of(db)
    trial_end = sub.trial_ends_at if sub else business.created_at + timedelta(days=plan_rules.TRIAL_DAYS)
    out = plan_rules.access_state(complimentary=business.complimentary, trial_ends_at=trial_end, paid_until=sub.paid_until if sub else None, now=now, cancelled=bool(sub and sub.cancelled_at))
    if sub is not None and sub.cancelled_at is not None:
        # A cancelled account is read-only for the data-export period, free accounts included.
        out = {**out, "state": "read_only", "writable": False, "days_left": 0}
    return {**out, "complimentary": business.complimentary, "suspended": False}


def allowed_when_read_only(path: str) -> bool:
    return any(path == p.rstrip("/") or path.startswith(p) for p in READ_ONLY_OK)


async def active_vehicles(db: AsyncSession) -> list[Vehicle]:
    return list((await db.execute(select(Vehicle).where(Vehicle.is_active.is_(True)).order_by(Vehicle.registration))).scalars())


def effective_plan(plan: str, access: dict) -> str:
    """A trial is Standard whatever a vehicle is set to, so Premium cannot be had free by switching every vehicle over."""
    if access["state"] == "trialing" and plan_rules.RANK[plan] > plan_rules.RANK["standard"]:
        return "standard"
    return plan


async def fleet_plan(db: AsyncSession, access: dict) -> str:
    return plan_rules.best_plan([effective_plan(v.plan, access) for v in await active_vehicles(db)])


PLAN_NAME = {"starter": "Starter", "standard": "Standard", "premium": "Premium"}
FEATURE_NAME = {
    "trackers": "GPS tracker integration", "live_map": "The live fleet map", "replay": "Trip replay and driving behaviour", "geofences": "Mapped areas", "scorecards": "Driver scorecards",
    "tyres_parts": "Tyres and the parts store", "tracking_links": "Client tracking links", "etims": "eTIMS invoicing", "custom_reports": "Custom reports", "all_roles": "Roles beyond owner and driver",
    "fuel_sensors": "Fuel sensors", "immobiliser": "The remote immobiliser", "predictions": "Predictions and learned models", "ask": "Asking questions in plain English", "scheduled_reports": "Scheduled reports",
}  # fmt: skip


def plan_required(feature: str):
    needed = plan_rules.FEATURES[feature]
    return error(402, "plan_required", f"{FEATURE_NAME.get(feature, feature)} is part of the {PLAN_NAME[needed]} plan. Move a vehicle to {PLAN_NAME[needed]} in Settings, Subscription.")


async def require_feature(db: AsyncSession, business_id: uuid.UUID, feature: str) -> None:
    """Raises 402 unless the business's best plan includes the feature. A free account has everything."""
    if not settings.enforce_plans:
        return
    access = await access_for(db, business_id)
    if access["complimentary"]:
        return
    if not plan_rules.allows(await fleet_plan(db, access), feature):
        raise plan_required(feature)


async def require_vehicle_feature(db: AsyncSession, business_id: uuid.UUID, vehicle: Vehicle, feature: str) -> None:
    """For things that belong to one vehicle (its tracker, its fuel sensor, its immobiliser): that vehicle's own plan decides."""
    if not settings.enforce_plans:
        return
    access = await access_for(db, business_id)
    if access["complimentary"]:
        return
    if not plan_rules.allows(effective_plan(vehicle.plan, access), feature):
        raise plan_required(feature)


# ---- invoices and payment ----------------------------------------------------------------------------------------------------


async def open_invoice(db: AsyncSession) -> SubscriptionInvoice | None:
    return (await db.execute(select(SubscriptionInvoice).where(SubscriptionInvoice.status == "issued", SubscriptionInvoice.kind == "subscription").order_by(SubscriptionInvoice.created_at.desc()))).scalars().first()


async def current_quote(db: AsyncSession, sub: Subscription, payroll_employees: int = 0, period: str | None = None) -> dict:
    vehicles = await active_vehicles(db)
    q = plan_rules.quote_subscription([v.plan for v in vehicles], period=period or sub.period, payroll_employees=payroll_employees if sub.payroll_enabled else 0)
    if q["custom"] and sub.custom_monthly_cents:
        months_paid = q["months_paid"]
        q = {**q, "monthly_cents": sub.custom_monthly_cents, "total_cents": sub.custom_monthly_cents * months_paid, "saving_cents": sub.custom_monthly_cents * q["months_covered"] - sub.custom_monthly_cents * months_paid, "custom": False, "agreed": True}
    return q


async def raise_invoice(db: AsyncSession, sub: Subscription, quote: dict, now: datetime | None = None) -> SubscriptionInvoice:
    """The invoice for the next period: it starts where the paid time ends (or today), and an annual one runs twelve months."""
    now = now or now_utc()
    start = sub.paid_until if sub.paid_until is not None and sub.paid_until > now else now
    end_date = add_months(start.astimezone(NAIROBI).date(), quote["months_covered"])
    end = datetime.combine(end_date, start.astimezone(NAIROBI).timetz()).astimezone(UTC)
    return await create_numbered(db, SubscriptionInvoice, "SUB", kind="subscription", period_start=start, period_end=end, billing_period=quote["period"], quote=quote, total_cents=quote["total_cents"], due_date=start.astimezone(NAIROBI).date())


async def raise_sms_invoice(db: AsyncSession, messages: int) -> SubscriptionInvoice:
    price = plan_rules.SMS_BUNDLES[messages]
    return await create_numbered(db, SubscriptionInvoice, "SUB", kind="sms_bundle", sms_messages=messages, quote={"messages": messages, "total_cents": price}, total_cents=price, due_date=datetime.now(NAIROBI).date())


async def apply_paid(db: AsyncSession, invoice: SubscriptionInvoice, *, method: str, code: str | None, now: datetime | None = None) -> None:
    """The invoice is paid: a subscription period is paid for (full access straight away, nothing lost), or text credits are added.
    Safe to call twice: a paid invoice is left alone."""
    if invoice.status == "paid":
        return
    now = now or now_utc()
    invoice.status, invoice.paid_at, invoice.payment_method, invoice.mpesa_code = "paid", now, method, code
    if invoice.kind == "sms_bundle":
        account = (await db.execute(select(SmsAccount))).scalars().first()
        if account is None:
            account = SmsAccount(credits=0, sent_total=0, sent_this_month=0)
            db.add(account)
        account.credits += invoice.sms_messages or 0
        return
    sub = await subscription_of(db)
    if sub is not None:
        sub.paid_until = max(sub.paid_until or invoice.period_end, invoice.period_end)
        sub.period = invoice.billing_period or sub.period
        sub.last_notice = None


async def payment_for_checkout(db: AsyncSession, checkout_id: str) -> SubscriptionPayment | None:
    return (await db.execute(select(SubscriptionPayment).where(SubscriptionPayment.checkout_id == checkout_id))).scalars().first()


# ---- text message accounting ----------------------------------------------------------------------------------------------


async def record_sms(db: AsyncSession, segments: int, today: date | None = None) -> None:
    """Counts messages sent for the business. Credits may go below zero: a message is never held back for want of a bundle."""
    today = today or datetime.now(NAIROBI).date()
    account = (await db.execute(select(SmsAccount))).scalars().first()
    if account is None:
        account = SmsAccount(credits=0, sent_total=0, sent_month=today.replace(day=1), sent_this_month=0)
        db.add(account)
    if account.sent_month != today.replace(day=1):
        account.sent_month, account.sent_this_month = today.replace(day=1), 0
    account.credits = (account.credits or 0) - segments
    account.sent_total = (account.sent_total or 0) + segments
    account.sent_this_month = (account.sent_this_month or 0) + segments


async def sms_account(db: AsyncSession) -> dict:
    a = (await db.execute(select(SmsAccount))).scalars().first()
    return {"credits": a.credits if a else 0, "sent_total": a.sent_total if a else 0, "sent_this_month": a.sent_this_month if a else 0, "low": bool(a and a.credits < 50 and a.sent_total > 0)}


def current_business() -> uuid.UUID | None:
    return current_business_id.get()


# ---- reminders ---------------------------------------------------------------------------------------------------------------


def notice_for(access: dict) -> tuple[str, str] | None:
    """The reminder due for where an account is now: (key, text). None when nothing is due. Each is sent once per period."""
    state, left = access["state"], access.get("days_left")
    if state == "trialing" and left is not None and left <= 3:
        return "trial_ending", f"Your FleetTms free trial ends in {left} day{'s' if left != 1 else ''}. Choose your plan and pay in Settings, Subscription to keep adding records."
    if state == "active" and left is not None and left <= 3:
        return "renewal_due", f"Your FleetTms subscription runs out in {left} day{'s' if left != 1 else ''}. Pay in Settings, Subscription to carry on without a break."
    if state == "grace":
        return "grace", f"Your FleetTms subscription has run out. Everything still works for {left} more day{'s' if left != 1 else ''}, then the account goes read-only (nothing is deleted). Pay in Settings, Subscription."
    if state == "read_only":
        return "read_only", "Your FleetTms account is now read-only because the subscription has not been paid. Nothing has been lost: pay in Settings, Subscription and it works again at once."
    return None


async def send_notices(db: AsyncSession, now: datetime | None = None) -> int:
    """Texts the owner (and manager) once per period about a trial ending, a payment due, a grace period or read-only mode."""
    from app.models import Membership, MembershipStatus, Role
    from app.sms import get_sms_sender

    now = now or now_utc()
    business_id = current_business_id.get()
    business = await db.get(Business, business_id)
    if business is None or business.complimentary:
        return 0
    sub = await get_or_start(db, business)
    access = await access_for(db, business_id, now)
    due = notice_for(access)
    if due is None:
        return 0
    key, text = due
    stamp = f"{key}:{(access['ends_at'] or now).date().isoformat()}"
    if sub.last_notice == stamp:
        return 0
    sent = 0
    for m in (await db.execute(select(Membership).where(Membership.status == MembershipStatus.ACTIVE))).scalars():
        if Role.OWNER in {r.role for r in m.roles} and m.user.phone:
            await get_sms_sender().send_platform(m.user.phone, f"{business.name}: {text}")
            sent += 1
    sub.last_notice = stamp
    return sent
