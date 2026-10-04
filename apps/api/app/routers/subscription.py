"""A business's subscription (masterplan Section 9): where it stands, the plan for each vehicle, invoices, and paying by M-Pesa."""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, plan_rules, platform_mpesa, ratelimit, subscriptions
from app.config import settings
from app.db import get_db
from app.deps import Principal, current_principal, error, require
from app.models import (
    Membership,
    MembershipStatus,
    SubscriptionInvoice,
    SubscriptionPayment,
    Vehicle,
)
from app.phone import normalize_phone
from app.tenancy import current_business_id

log = logging.getLogger(__name__)
router = APIRouter(tags=["subscription"])


class PlansIn(BaseModel):
    vehicles: list[dict] = Field(min_length=1, max_length=500)  # [{"vehicle_id": ..., "plan": "premium"}]


class SettingsIn(BaseModel):
    period: Literal["monthly", "annual"] | None = None
    payroll_enabled: bool | None = None


class PayIn(BaseModel):
    method: Literal["mpesa"] = "mpesa"
    phone: str = Field(min_length=9, max_length=20)


class BundleIn(BaseModel):
    messages: int


def invoice_out(i: SubscriptionInvoice) -> dict:
    return {
        "id": i.id, "number": i.number, "kind": i.kind, "status": i.status, "total_cents": i.total_cents, "period_start": i.period_start, "period_end": i.period_end, "billing_period": i.billing_period,
        "sms_messages": i.sms_messages, "due_date": i.due_date, "paid_at": i.paid_at, "payment_method": i.payment_method, "mpesa_code": i.mpesa_code, "quote": i.quote, "created_at": i.created_at,
    }  # fmt: skip


async def staff_on_payroll(db: AsyncSession) -> int:
    return int((await db.execute(select(func.count()).select_from(Membership).where(Membership.status == MembershipStatus.ACTIVE))).scalar_one())


@router.get("/plans")
async def plans():
    """What the plans cost and include. Public, so a price can be looked up before signing up."""
    return {
        "plans": [{"plan": p, "name": subscriptions.PLAN_NAME[p], "price_cents": plan_rules.PRICE_CENTS[p], "features": [f for f, needed in plan_rules.FEATURES.items() if plan_rules.RANK[needed] <= plan_rules.RANK[p]]} for p in plan_rules.PLANS],
        "features": {f: {"name": subscriptions.FEATURE_NAME.get(f, f), "plan": needed} for f, needed in plan_rules.FEATURES.items()},
        "trial_days": plan_rules.TRIAL_DAYS, "grace_days": plan_rules.GRACE_DAYS, "annual_months_paid": plan_rules.ANNUAL_MONTHS_PAID, "volume": {"from": plan_rules.VOLUME_FROM, "to": plan_rules.VOLUME_TO, "pct": plan_rules.VOLUME_PCT, "custom_from": plan_rules.CUSTOM_FROM},
        "payroll_cents": plan_rules.PAYROLL_CENTS, "sms_bundles": [{"messages": m, "price_cents": c} for m, c in plan_rules.SMS_BUNDLES.items()],
    }  # fmt: skip


async def status_of(db: AsyncSession, business_id: uuid.UUID) -> dict:
    from app.models import Business

    business = await db.get(Business, business_id)
    sub = await subscriptions.get_or_start(db, business)
    access = await subscriptions.access_for(db, business_id)
    vehicles = await subscriptions.active_vehicles(db)
    employees = await staff_on_payroll(db)
    invoices = list((await db.execute(select(SubscriptionInvoice).order_by(SubscriptionInvoice.created_at.desc()).limit(24))).scalars())
    return {
        "access": access, "trial_ends_at": sub.trial_ends_at, "paid_until": sub.paid_until, "period": sub.period, "payroll_enabled": sub.payroll_enabled, "payroll_employees": employees,
        "fleet_plan": await subscriptions.fleet_plan(db, access), "vehicles": [{"vehicle_id": v.id, "registration": v.registration, "plan": v.plan, "effective_plan": subscriptions.effective_plan(v.plan, access)} for v in vehicles],
        "quote": await subscriptions.current_quote(db, sub, employees), "annual_quote": await subscriptions.current_quote(db, sub, employees, "annual"), "custom_monthly_cents": sub.custom_monthly_cents,
        "open_invoice": invoice_out(open_one) if (open_one := next((i for i in invoices if i.status == "issued" and i.kind == "subscription"), None)) else None,
        "invoices": [invoice_out(i) for i in invoices], "sms": await subscriptions.sms_account(db),
        "cancelled_at": sub.cancelled_at, "data_removed_on": sub.cancelled_at + timedelta(days=settings.cancelled_grace_days) if sub.cancelled_at else None,
    }  # fmt: skip


@router.get("/subscription")
async def my_subscription(principal: Principal = Depends(require("business.manage")), db: AsyncSession = Depends(get_db)):
    out = await status_of(db, principal.business_id)
    await db.commit()  # a business from before subscriptions existed has its trial recorded the first time it looks
    return out


class CancelIn(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


@router.post("/subscription/cancel")
async def cancel_subscription(body: CancelIn, principal: Principal = Depends(require("business.manage")), db: AsyncSession = Depends(get_db)):
    """The owner ends the subscription. The account turns read-only at once and everything can still be exported; after the
    grace period (90 days) personal data and images are removed, and the records the law requires are kept for their own period."""
    from app.models import Business

    business = await db.get(Business, principal.business_id)
    sub = await subscriptions.get_or_start(db, business)
    if sub.cancelled_at is not None:
        raise error(status.HTTP_409_CONFLICT, "already_cancelled", "This subscription is already cancelled.")
    sub.cancelled_at = datetime.now(UTC)
    audit.record(db, actor_user_id=principal.user.id, action="subscription.cancelled", entity_type="business", entity_id=business.id, note=body.reason)
    await db.commit()
    return await status_of(db, principal.business_id)


@router.post("/subscription/reactivate")
async def reactivate_subscription(principal: Principal = Depends(require("business.manage")), db: AsyncSession = Depends(get_db)):
    """Takes the cancellation back, while the data is still there. Whether the account can then be changed depends on whether it is
    paid up, as at any other time."""
    from app.models import Business

    business = await db.get(Business, principal.business_id)
    sub = await subscriptions.get_or_start(db, business)
    if sub.cancelled_at is None:
        raise error(status.HTTP_409_CONFLICT, "not_cancelled", "This subscription is not cancelled.")
    sub.cancelled_at = None
    audit.record(db, actor_user_id=principal.user.id, action="subscription.reactivated", entity_type="business", entity_id=business.id)
    await db.commit()
    return await status_of(db, principal.business_id)


@router.get("/subscription/banner")
async def banner(principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    """Just enough for every signed-in person to see a warning: not billing details, which are the owner's."""
    if principal.business_id is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "There is no business to show.")
    return {k: v for k, v in (await subscriptions.access_for(db, principal.business_id)).items() if k in ("state", "writable", "days_left", "ends_at", "grace_ends_at", "complimentary", "suspended")}


@router.put("/subscription/plans")
async def set_plans(body: PlansIn, principal: Principal = Depends(require("business.manage")), db: AsyncSession = Depends(get_db)):
    """Chooses the plan for each vehicle. It applies at once and is billed on the next invoice."""
    wanted: dict[uuid.UUID, str] = {}
    for row in body.vehicles:
        try:
            vid, plan = uuid.UUID(str(row["vehicle_id"])), str(row["plan"])
        except (KeyError, ValueError):
            raise error(422, "bad_plan", "Each vehicle needs its id and a plan.") from None
        if plan not in plan_rules.PLANS:
            raise error(422, "bad_plan", f"The plan must be one of: {', '.join(plan_rules.PLANS)}.")
        wanted[vid] = plan
    changed = []
    for v in (await db.execute(select(Vehicle).where(Vehicle.id.in_(list(wanted))))).scalars():
        if v.plan != wanted[v.id]:
            changed.append({"registration": v.registration, "from": v.plan, "to": wanted[v.id]})
            v.plan = wanted[v.id]
    if len(wanted) != len((await db.execute(select(Vehicle.id).where(Vehicle.id.in_(list(wanted))))).all()):
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "One of those vehicles was not found.")
    if changed:
        audit.record(db, actor_user_id=principal.user.id, action="subscription.plans_changed", entity_type="business", entity_id=principal.business_id, after={"changes": changed})
    await db.commit()
    return await status_of(db, principal.business_id)


@router.put("/subscription/settings")
async def set_settings(body: SettingsIn, principal: Principal = Depends(require("business.manage")), db: AsyncSession = Depends(get_db)):
    from app.models import Business

    sub = await subscriptions.get_or_start(db, await db.get(Business, principal.business_id))
    if body.period is not None:
        sub.period = body.period
    if body.payroll_enabled is not None:
        sub.payroll_enabled = body.payroll_enabled
    audit.record(db, actor_user_id=principal.user.id, action="subscription.settings_changed", entity_type="business", entity_id=principal.business_id, after={"period": sub.period, "payroll": sub.payroll_enabled})
    await db.commit()
    return await status_of(db, principal.business_id)


@router.post("/subscription/invoices", status_code=status.HTTP_201_CREATED)
async def raise_invoice(principal: Principal = Depends(require("business.manage")), db: AsyncSession = Depends(get_db)):
    """The invoice for the next period, from the plans the vehicles are on now. One open invoice at a time: asking again returns it."""
    from app.models import Business

    sub = await subscriptions.get_or_start(db, await db.get(Business, principal.business_id))
    existing = await subscriptions.open_invoice(db)
    if existing is not None:
        return invoice_out(existing)
    quote = await subscriptions.current_quote(db, sub, await staff_on_payroll(db))
    if quote["custom"]:
        raise error(422, "custom_pricing", "A fleet of 31 or more vehicles is priced by agreement. We will contact you with the price.")
    if quote["vehicles"] == 0:
        raise error(422, "no_vehicles", "Add a vehicle first: the subscription is priced per vehicle.")
    invoice = await subscriptions.raise_invoice(db, sub, quote)
    audit.record(db, actor_user_id=principal.user.id, action="subscription.invoice_raised", entity_type="subscription_invoice", entity_id=invoice.id, after={"number": invoice.number, "total_cents": invoice.total_cents})
    await db.commit()
    return invoice_out(invoice)


@router.post("/subscription/sms-bundles", status_code=status.HTTP_201_CREATED)
async def buy_sms_bundle(body: BundleIn, principal: Principal = Depends(require("business.manage")), db: AsyncSession = Depends(get_db)):
    if body.messages not in plan_rules.SMS_BUNDLES:
        raise error(422, "bad_bundle", f"Choose a bundle of {', '.join(str(m) for m in plan_rules.SMS_BUNDLES)} messages.")
    invoice = await subscriptions.raise_sms_invoice(db, body.messages)
    audit.record(db, actor_user_id=principal.user.id, action="subscription.sms_bundle_invoiced", entity_type="subscription_invoice", entity_id=invoice.id, after={"messages": body.messages})
    await db.commit()
    return invoice_out(invoice)


@router.post("/subscription/invoices/{invoice_id}/pay")
async def pay_invoice(invoice_id: uuid.UUID, body: PayIn, principal: Principal = Depends(require("business.manage")), db: AsyncSession = Depends(get_db)):
    """Asks the owner's phone to pay the invoice by M-Pesa. The invoice is marked paid when Safaricom says it was, not before."""
    invoice = (await db.execute(select(SubscriptionInvoice).where(SubscriptionInvoice.id == invoice_id))).scalar_one_or_none()
    if invoice is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That invoice was not found.")
    if invoice.status != "issued":
        raise error(status.HTTP_409_CONFLICT, "not_payable", "That invoice is not waiting for payment.")
    phone = normalize_phone(body.phone)
    if phone is None:
        raise error(422, "invalid_phone", "That is not a Kenyan phone number.")
    pending = (await db.execute(select(SubscriptionPayment).where(SubscriptionPayment.invoice_id == invoice.id, SubscriptionPayment.status == "pending"))).scalars().first()
    if pending is not None and (datetime.now(pending.created_at.tzinfo) - pending.created_at).total_seconds() < 60:
        raise error(status.HTTP_409_CONFLICT, "prompt_sent", "A payment request was just sent to that phone. Check it, or wait a minute and try again.")
    amount_kes = -(-invoice.total_cents // 100)
    try:
        checkout = await platform_mpesa.get_prompts().push(phone=phone, amount_kes=amount_kes, reference=invoice.number, description="FleetTms", callback_url=platform_mpesa.callback_url())
    except platform_mpesa.PromptError as e:
        raise error(status.HTTP_502_BAD_GATEWAY, "prompt_failed", str(e)) from None
    payment = SubscriptionPayment(invoice_id=invoice.id, phone=phone, amount_cents=amount_kes * 100, checkout_id=checkout)
    db.add(payment)
    audit.record(db, actor_user_id=principal.user.id, action="subscription.payment_requested", entity_type="subscription_invoice", entity_id=invoice.id, after={"amount_cents": payment.amount_cents})
    await db.commit()
    return {"payment_id": payment.id, "status": "pending", "message": f"A payment request for KES {amount_kes:,} was sent to {phone}. Enter your M-Pesa PIN to pay."}


@router.get("/subscription/invoices/{invoice_id}")
async def invoice_status(invoice_id: uuid.UUID, principal: Principal = Depends(require("business.manage")), db: AsyncSession = Depends(get_db)):
    """For the screen waiting on the phone: is the invoice paid yet."""
    invoice = (await db.execute(select(SubscriptionInvoice).where(SubscriptionInvoice.id == invoice_id))).scalar_one_or_none()
    if invoice is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That invoice was not found.")
    last = (await db.execute(select(SubscriptionPayment).where(SubscriptionPayment.invoice_id == invoice.id).order_by(SubscriptionPayment.created_at.desc()))).scalars().first()
    return {**invoice_out(invoice), "last_payment": {"status": last.status, "note": last.result_note} if last else None}


@router.post("/hooks/subscription-pay/{key}", dependencies=[Depends(ratelimit.hook_guard)])
async def payment_callback(key: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Safaricom's answer to a payment request. The secret in the address says it is Safaricom; the checkout id must be one of ours and
    the amount must be the invoice's, or nothing is credited. Always answers 200: Safaricom retries anything else."""
    import hmac

    ok = {"ResultCode": 0, "ResultDesc": "Accepted"}
    if not hmac.compare_digest(platform_mpesa.callback_key(), key):
        raise error(status.HTTP_403_FORBIDDEN, "forbidden", "Not allowed.")
    try:
        body = await request.json()
    except ValueError:
        return ok
    result = platform_mpesa.parse_callback(body)
    if result is None:
        return ok
    payment = (await db.execute(select(SubscriptionPayment).where(SubscriptionPayment.checkout_id == result["checkout_id"]).execution_options(skip_tenant=True))).scalars().first()
    if payment is None or payment.status != "pending":
        return ok  # not ours, or already answered: a repeated callback changes nothing
    current_business_id.set(payment.business_id)
    invoice = (await db.execute(select(SubscriptionInvoice).where(SubscriptionInvoice.id == payment.invoice_id))).scalar_one()
    payment.answered_at = datetime.now(payment.created_at.tzinfo)
    if not result["ok"]:
        payment.status, payment.result_note = "failed", result["note"]
    elif result["amount"] is None or int(float(result["amount"]) * 100) < invoice.total_cents - 100:
        payment.status, payment.result_note = "failed", "The amount paid was less than the invoice."
        log.warning("A subscription payment came in for less than its invoice")
    else:
        payment.status, payment.mpesa_code, payment.result_note = "paid", result["receipt"], "Paid"
        await subscriptions.apply_paid(db, invoice, method="mpesa", code=result["receipt"])
        audit.record(db, actor_user_id=None, action="subscription.paid", entity_type="subscription_invoice", entity_id=invoice.id, after={"number": invoice.number, "mpesa_code": result["receipt"]})
    await db.commit()
    return ok

