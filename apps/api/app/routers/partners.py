"""The partner programme (masterplan Section 9): GPS tracker installers who bring customers in and earn a recurring share of what they pay.

Public: apply, check a code, and read your own private report with the key you were given. Platform admins: approve, suspend, set the
share, record payouts, and export what is owed. A partner never sees anything inside a customer's business, only its name, when it joined,
how it stands (trial, paying, overdue) and how many vehicles it has."""

import csv
import io
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Header, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import partners, ratelimit
from app.config import settings
from app.db import get_db
from app.deps import Principal, error, platform_admin
from app.models import Partner, PartnerCommission
from app.phone import normalize_phone
from app.sms import get_sms_sender

router = APIRouter(tags=["partners"])


class ApplyIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    contact_name: str = Field(min_length=2, max_length=200)
    phone: str
    email: EmailStr | None = None
    city: str | None = Field(default=None, max_length=80)
    kind: Literal["tracker_installer", "other"] = "tracker_installer"
    message: str | None = Field(default=None, max_length=1000)


class ApproveIn(BaseModel):
    commission_pct: int | None = Field(default=None, ge=1, le=50)


class PayoutIn(BaseModel):
    reference: str = Field(min_length=3, max_length=60)


def partner_out(p: Partner) -> dict:
    return {
        "id": p.id, "name": p.name, "contact_name": p.contact_name, "phone": p.phone, "email": p.email, "city": p.city, "kind": p.kind, "message": p.message,
        "status": p.status, "code": p.code, "commission_pct": p.commission_bp / 100, "created_at": p.created_at, "approved_at": p.approved_at,
    }  # fmt: skip


# ---- public --------------------------------------------------------------------------------------------------------------


@router.post("/partners/apply", status_code=status.HTTP_201_CREATED, dependencies=[Depends(ratelimit.limit("partner_apply", 5, 3600))])
async def apply(body: ApplyIn, db: AsyncSession = Depends(get_db)):
    """Anyone can ask to become a partner. Nothing is given out until a person at FleetTms approves the application."""
    phone = normalize_phone(body.phone)
    if phone is None:
        raise error(422, "invalid_phone", "Enter a Kenyan phone number, for example 0712 345 678.")
    row = Partner(name=body.name.strip(), contact_name=body.contact_name.strip(), phone=phone, email=body.email.lower() if body.email else None, city=body.city, kind=body.kind, message=body.message)
    db.add(row)
    await db.commit()
    return {"id": row.id, "status": row.status, "message": "Thank you. We will call you."}


@router.get("/partners/code/{code}", dependencies=[Depends(ratelimit.limit("partner_code", 30, 60))])
async def check_code(code: str, db: AsyncSession = Depends(get_db)):
    """So the sign-up form can say whose code it is before the owner goes on. Only the partner's trading name is returned."""
    partner = await partners.by_code(db, code)
    if partner is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That code was not recognised.")
    return {"partner": partner.name}


@router.get("/partners/portal", dependencies=[Depends(ratelimit.limit("partner_portal", 30, 60))])
async def portal(x_partner_key: str = Header(default=""), db: AsyncSession = Depends(get_db)):
    """A partner's own report: who they brought in, how each stands, and what they have earned and been paid. The key is sent in a header,
    not the address, so it does not end up in logs or browser history."""
    partner = await partners.by_key(db, x_partner_key)
    if partner is None:
        raise error(status.HTTP_401_UNAUTHORIZED, "unauthorised", "That key was not recognised.")
    commissions = (await db.execute(select(PartnerCommission).where(PartnerCommission.partner_id == partner.id).order_by(PartnerCommission.accrued_at.desc()).limit(200))).scalars().all()
    refs = await partners.referrals(db, partner.id)
    return {
        "partner": {"name": partner.name, "status": partner.status, "code": partner.code, "commission_pct": partner.commission_bp / 100, "commission_months": settings.partner_commission_months},
        "totals": {**await partners.totals(db, partner.id), "referred": len(refs), "paying": sum(1 for r in refs if r["state"] == "active")},
        "referrals": refs, "commissions": [partners.commission_out(c) for c in commissions],
    }  # fmt: skip


# ---- platform admins -----------------------------------------------------------------------------------------------------


async def _get(db: AsyncSession, partner_id: uuid.UUID) -> Partner:
    row = await db.get(Partner, partner_id)
    if row is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That partner was not found.")
    return row


@router.get("/platform/partners")
async def list_partners(state: str | None = None, principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    stmt = select(Partner).order_by(Partner.created_at.desc())
    if state:
        stmt = stmt.where(Partner.status == state)
    out = []
    for p in (await db.execute(stmt)).scalars():
        refs = await partners.referrals(db, p.id)
        out.append({**partner_out(p), **await partners.totals(db, p.id), "referred": len(refs), "paying": sum(1 for r in refs if r["state"] == "active")})
    return out


@router.get("/platform/partners/commissions.csv")
async def commissions_csv(state: Literal["accrued", "paid"] | None = "accrued", principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    """What is owed (or has been paid), one line per commission, for making the payouts."""
    stmt = select(PartnerCommission, Partner).join(Partner, Partner.id == PartnerCommission.partner_id).order_by(Partner.name, PartnerCommission.accrued_at)
    if state:
        stmt = stmt.where(PartnerCommission.status == state)
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(["partner", "phone", "business", "invoice", "paid by business (KES)", "share %", "commission (KES)", "status", "earned", "paid", "reference"])
    for c, p in (await db.execute(stmt)).all():
        writer.writerow([p.name, p.phone, c.business_name, c.invoice_number, f"{c.basis_cents / 100:.2f}", c.pct_bp / 100, f"{c.amount_cents / 100:.2f}", c.status, c.accrued_at.date(), c.paid_at.date() if c.paid_at else "", c.payout_reference or ""])
    return Response(buffer.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="partner-commissions.csv"'})


@router.get("/platform/partners/{partner_id}")
async def partner_detail(partner_id: uuid.UUID, principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    p = await _get(db, partner_id)
    commissions = (await db.execute(select(PartnerCommission).where(PartnerCommission.partner_id == p.id).order_by(PartnerCommission.accrued_at.desc()).limit(200))).scalars().all()
    return {**partner_out(p), **await partners.totals(db, p.id), "referrals": await partners.referrals(db, p.id), "commissions": [partners.commission_out(c) for c in commissions]}


async def _tell(partner: Partner, key: str) -> None:
    base = settings.web_app_url.rstrip("/")
    link = f"{base}/partners/portal" if base else "the FleetTms partner page"
    await get_sms_sender().send_platform(partner.phone, f"FleetTms partner: your code is {partner.code}. Give it to your customers to type when they sign up. Your private report is at {link}, key {key}")


@router.post("/platform/partners/{partner_id}/approve")
async def approve_partner(partner_id: uuid.UUID, body: ApproveIn, principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    """Gives the partner their code and a key, and texts both to them. The key is also returned here, once, in case the text does not arrive."""
    p = await _get(db, partner_id)
    if p.status != "pending":
        raise error(status.HTTP_409_CONFLICT, "not_pending", "That application has already been decided.")
    key = await partners.approve(db, p, principal.user.id, body.commission_pct)
    await db.commit()
    await _tell(p, key)
    return {**partner_out(p), "portal_key": key}


@router.post("/platform/partners/{partner_id}/reissue-key")
async def reissue_key(partner_id: uuid.UUID, principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    """A lost or leaked key is replaced; the old one stops working."""
    p = await _get(db, partner_id)
    if p.status == "pending":
        raise error(status.HTTP_409_CONFLICT, "not_approved", "Approve the application first.")
    key = await partners.reissue_key(p)
    await db.commit()
    await _tell(p, key)
    return {"portal_key": key}


@router.post("/platform/partners/{partner_id}/commission")
async def set_commission(partner_id: uuid.UUID, body: ApproveIn, principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    """A new share for what the partner earns from now on. Commission already earned keeps the share it was earned at."""
    p = await _get(db, partner_id)
    if body.commission_pct is None:
        raise error(422, "share_needed", "Say what percentage.")
    p.commission_bp = body.commission_pct * 100
    await db.commit()
    return partner_out(p)


@router.post("/platform/partners/{partner_id}/payout")
async def record_payout(partner_id: uuid.UUID, body: PayoutIn, principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    """Marks everything owed to the partner as paid, with the reference of the payment you made (an M-Pesa code or a bank reference)."""
    p = await _get(db, partner_id)
    owed = (await db.execute(select(PartnerCommission).where(PartnerCommission.partner_id == p.id, PartnerCommission.status == "accrued"))).scalars().all()
    if not owed:
        raise error(status.HTTP_409_CONFLICT, "nothing_owed", "Nothing is owed to this partner.")
    now = datetime.now(UTC)
    for c in owed:
        c.status, c.paid_at, c.payout_reference = "paid", now, body.reference
    await db.commit()
    return {"paid_cents": sum(c.amount_cents for c in owed), "commissions": len(owed), "reference": body.reference, **await partners.totals(db, p.id)}


@router.get("/platform/partner-summary")
async def summary(principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    pending = (await db.execute(select(func.count()).select_from(Partner).where(Partner.status == "pending"))).scalar_one()
    owed = (await db.execute(select(func.coalesce(func.sum(PartnerCommission.amount_cents), 0)).where(PartnerCommission.status == "accrued"))).scalar_one()
    return {"applications_waiting": pending, "owed_cents": int(owed)}


@router.post("/platform/partners/{partner_id}/{action}")
async def set_partner_state(partner_id: uuid.UUID, action: Literal["suspend", "reactivate", "reject"], principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    """Suspending stops new referrals and new commission; what is already owed stays owed. Rejecting removes an application."""
    p = await _get(db, partner_id)
    if action == "reject":
        if p.status != "pending":
            raise error(status.HTTP_409_CONFLICT, "not_pending", "Only an application can be rejected.")
        await db.delete(p)
        await db.commit()
        return {"deleted": True}
    if p.status == "pending":
        raise error(status.HTTP_409_CONFLICT, "not_approved", "Approve the application first.")
    p.status = "suspended" if action == "suspend" else "approved"
    await db.commit()
    return partner_out(p)
