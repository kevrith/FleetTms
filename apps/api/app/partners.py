"""The partner programme: applying, approving, referral attribution, commission, and what a partner is allowed to see."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import partner_rules, plan_rules
from app.config import settings
from app.models import (
    Business,
    Partner,
    PartnerCommission,
    Subscription,
    SubscriptionInvoice,
    Vehicle,
)
from app.security import new_secret_token, sha256


def _all(stmt):
    return stmt.execution_options(skip_tenant=True)


async def by_code(db: AsyncSession, code: str) -> Partner | None:
    """An approved partner's code. A pending or suspended partner brings in no new referrals."""
    code = partner_rules.normalise_code(code)
    if not code:
        return None
    return (await db.execute(select(Partner).where(Partner.code == code, Partner.status == "approved"))).scalar_one_or_none()


async def approve(db: AsyncSession, partner: Partner, approved_by: uuid.UUID, pct: int | None = None) -> str:
    """Gives the partner their code and a key to their private report. Returns the key, which is shown once: only its hash is kept."""
    while True:
        code = partner_rules.new_code()
        if (await db.execute(select(Partner.id).where(Partner.code == code))).first() is None:
            break
    key = new_secret_token()
    partner.status, partner.code, partner.portal_key_hash = "approved", partner.code or code, sha256(key)
    partner.approved_at, partner.approved_by_user_id = datetime.now(UTC), approved_by
    partner.commission_bp = round((pct if pct is not None else settings.partner_commission_pct) * 100)
    return key


async def reissue_key(partner: Partner) -> str:
    key = new_secret_token()
    partner.portal_key_hash = sha256(key)
    return key


async def by_key(db: AsyncSession, key: str) -> Partner | None:
    if not key:
        return None
    return (await db.execute(select(Partner).where(Partner.portal_key_hash == sha256(key), Partner.status != "pending"))).scalar_one_or_none()


async def accrue(db: AsyncSession, invoice: SubscriptionInvoice, now: datetime | None = None) -> PartnerCommission | None:
    """A referred business has paid a subscription invoice: its partner earns a share. Called from the payment path, so it must be safe to
    repeat (one commission per invoice) and must never get in the way of the payment itself."""
    if invoice.kind != "subscription" or invoice.total_cents <= 0:
        return None
    business = await db.get(Business, invoice.business_id)
    if business is None or business.referred_by_partner_id is None:
        return None
    partner = await db.get(Partner, business.referred_by_partner_id)
    if partner is None or partner.status != "approved":
        return None  # a suspended partner earns nothing new; what was already accrued stays
    if (await db.execute(select(PartnerCommission.id).where(PartnerCommission.invoice_id == invoice.id))).first() is not None:
        return None
    now = now or invoice.paid_at or datetime.now(UTC)
    earlier = (
        await db.execute(_all(select(func.min(SubscriptionInvoice.paid_at)).where(SubscriptionInvoice.business_id == business.id, SubscriptionInvoice.kind == "subscription", SubscriptionInvoice.status == "paid")))
    ).scalar_one()
    if earlier is not None and not partner_rules.in_window(earlier, now, settings.partner_commission_months):
        return None
    row = PartnerCommission(
        partner_id=partner.id, business_id=business.id, business_name=business.name, invoice_id=invoice.id, invoice_number=invoice.number,
        basis_cents=invoice.total_cents, pct_bp=partner.commission_bp, amount_cents=partner_rules.commission_cents(invoice.total_cents, partner.commission_bp), accrued_at=now,
    )  # fmt: skip
    db.add(row)
    await db.flush()
    return row


def commission_out(c: PartnerCommission) -> dict:
    return {
        "id": c.id, "business": c.business_name, "invoice": c.invoice_number, "paid_by_business_cents": c.basis_cents, "share_pct": c.pct_bp / 100, "amount_cents": c.amount_cents,
        "status": c.status, "accrued_at": c.accrued_at, "paid_at": c.paid_at, "payout_reference": c.payout_reference,
    }  # fmt: skip


async def totals(db: AsyncSession, partner_id: uuid.UUID) -> dict:
    rows = (await db.execute(select(PartnerCommission.status, func.coalesce(func.sum(PartnerCommission.amount_cents), 0)).where(PartnerCommission.partner_id == partner_id).group_by(PartnerCommission.status))).all()
    by_status = {status: int(total) for status, total in rows}
    return {"owed_cents": by_status.get("accrued", 0), "paid_cents": by_status.get("paid", 0)}


async def referrals(db: AsyncSession, partner_id: uuid.UUID) -> list[dict]:
    """The businesses a partner brought in: name, when, how it stands, and how big. Nothing about the people or records inside."""
    now = datetime.now(UTC)
    businesses = (await db.execute(select(Business).where(Business.referred_by_partner_id == partner_id).order_by(Business.referred_at.desc()))).scalars().all()
    if not businesses:
        return []
    ids = [b.id for b in businesses]
    subs = {s.business_id: s for s in (await db.execute(_all(select(Subscription).where(Subscription.business_id.in_(ids))))).scalars()}
    vehicles = dict((await db.execute(_all(select(Vehicle.business_id, func.count()).where(Vehicle.business_id.in_(ids), Vehicle.is_active.is_(True)).group_by(Vehicle.business_id)))).all())
    out = []
    for b in businesses:
        sub = subs.get(b.id)
        trial_end = sub.trial_ends_at if sub else b.referred_at
        access = plan_rules.access_state(complimentary=b.complimentary, trial_ends_at=trial_end, paid_until=sub.paid_until if sub else None, now=now, cancelled=bool(sub and sub.cancelled_at))
        state = "cancelled" if sub and sub.cancelled_at else "suspended" if b.suspended_at else access["state"]
        out.append({"business": b.name, "referred_at": b.referred_at, "state": state, "vehicles": int(vehicles.get(b.id, 0))})
    return out
