"""Lease due-date reminders and overdue alerts (masterplan 5.23): a text to the owner and accountant three days before a lease
payment falls due and again when it is overdue (and, for a leased-out lorry, to the lessee when they are late). Each goes once
per month's charge."""

import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_sessionmaker
from app.leases import entries_of, standing_of
from app.models import (
    Business,
    LeaseAgreement,
    LeaseNotice,
    Membership,
    MembershipStatus,
    Party,
    Role,
    Vehicle,
)
from app.reminders import nairobi_today
from app.sms import get_sms_sender
from app.tenancy import current_business_id

log = logging.getLogger(__name__)
SOON_DAYS = 3


def kes(cents: int) -> str:
    return f"KES {cents / 100:,.2f}"


async def notify_staff(db: AsyncSession, message: str) -> int:
    sent = 0
    for m in (await db.execute(select(Membership).where(Membership.status == MembershipStatus.ACTIVE))).scalars():
        if {r.role for r in m.roles} & {Role.OWNER, Role.ACCOUNTANT} and m.user.phone:
            await get_sms_sender().send(m.user.phone, message)
            sent += 1
    return sent


async def notices_for_business(db: AsyncSession) -> int:
    today = nairobi_today()
    business = (await db.execute(select(Business).where(Business.id == current_business_id.get()))).scalar_one()
    sent = 0
    for a in (await db.execute(select(LeaseAgreement).where(LeaseAgreement.status == "active"))).scalars():
        entries = await entries_of(db, a.id)
        standing = standing_of(entries, today)
        if standing["balance_cents"] <= 0:
            continue
        reg = (await db.execute(select(Vehicle.registration).where(Vehicle.id == a.vehicle_id))).scalar_one()
        party = (await db.execute(select(Party).where(Party.id == a.party_id))).scalar_one()
        for charge in (e for e in entries if e.kind == "charge" and e.due_date is not None):
            kind = "overdue" if standing["overdue_cents"] > 0 and charge.due_date < today else "due" if today <= charge.due_date <= today + timedelta(days=SOON_DAYS) else None
            if kind is None:
                continue
            if (await db.execute(select(LeaseNotice.id).where(LeaseNotice.agreement_id == a.id, LeaseNotice.period_start == charge.period_start, LeaseNotice.kind == kind))).first():
                continue
            if a.direction == "in":
                text = f"{business.name}: lease payment for {reg} to {party.name}, {kes(standing['balance_cents'])}, is " + (f"overdue since {charge.due_date:%d %b}." if kind == "overdue" else f"due on {charge.due_date:%d %b}.")
            else:
                text = f"{business.name}: the lease payment for {reg} from {party.name}, {kes(standing['balance_cents'])}, is " + (f"overdue since {charge.due_date:%d %b}." if kind == "overdue" else f"due on {charge.due_date:%d %b}.")
            count = await notify_staff(db, text)
            if a.direction == "out" and kind == "overdue" and party.phone:
                await get_sms_sender().send(party.phone, f"{business.name}: your lease payment for {reg} of {kes(standing['overdue_cents'])} was due on {charge.due_date:%d %b}. Please pay as soon as you can.")
                count += 1
            db.add(LeaseNotice(agreement_id=a.id, period_start=charge.period_start, kind=kind, sent_to=count))
            await db.commit()
            sent += count
    return sent


async def run_lease_notices() -> int:
    total = 0
    async with get_sessionmaker()() as db:
        business_ids = (await db.execute(select(Business.id))).scalars().all()
    for business_id in business_ids:
        async with get_sessionmaker()() as db:
            current_business_id.set(business_id)
            try:
                total += await notices_for_business(db)
            finally:
                current_business_id.set(None)
    return total


async def lease_notices_job(ctx: dict) -> int:
    return await run_lease_notices()


async def run_lease_charges() -> int:
    """On the 1st: works out last month's charge for every running lease, and for any that ended in it."""
    from app.leases import run_month

    month = nairobi_today().replace(day=1) - timedelta(days=1)
    total = 0
    async with get_sessionmaker()() as db:
        business_ids = (await db.execute(select(Business.id))).scalars().all()
    for business_id in business_ids:
        async with get_sessionmaker()() as db:
            current_business_id.set(business_id)
            try:
                for a in (await db.execute(select(LeaseAgreement))).scalars().all():
                    first = month.replace(day=1)
                    if a.start_date <= month and (a.end_date is None or a.end_date >= first):
                        if a.direction == "out" and (a.per_trip_cents or a.per_km_cents or float(a.revenue_pct) or float(a.profit_pct)):
                            continue  # waits for the lessee's figures
                        await run_month(db, a, first, None)
                        total += 1
                await db.commit()
            finally:
                current_business_id.set(None)
    return total


async def lease_charges_job(ctx: dict) -> int:
    return await run_lease_charges()
