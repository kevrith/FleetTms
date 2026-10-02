"""Document expiry reminders by SMS (masterplan 5.1 and 5.11).

A reminder goes out at 30, 14 and 7 days before expiry. Each one is recorded, so running the job twice in a
day, or again after a restart, never sends the same reminder twice. If the job missed days, only the most
urgent reminder that is due is sent, and the earlier ones are marked as covered.
"""

import logging
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_sessionmaker
from app.models import (
    Business,
    ComplianceDocument,
    DocumentReminder,
    Membership,
    MembershipStatus,
    Role,
    Vehicle,
)
from app.sms import get_sms_sender
from app.tenancy import current_business_id

log = logging.getLogger(__name__)

NAIROBI = ZoneInfo("Africa/Nairobi")
REMINDER_DAYS = (30, 14, 7)
LABELS = {
    "insurance": "Insurance",
    "inspection": "Inspection",
    "ntsa_licence": "NTSA licence",
    "tlb_licence": "TLB licence",
    "permit": "Permit",
    "driving_licence": "Driving licence",
    "other": "Document",
}


def nairobi_today() -> date:
    return datetime.now(UTC).astimezone(NAIROBI).date()


async def _send_for_business(db: AsyncSession, today: date) -> int:
    members = {m.id: m for m in (await db.execute(select(Membership))).scalars()}
    managers = [
        m
        for m in members.values()
        if m.status == MembershipStatus.ACTIVE
        and m.user.phone
        and {r.role for r in m.roles} & {Role.OWNER, Role.MANAGER}
    ]
    vehicles = {v.id: v for v in (await db.execute(select(Vehicle))).scalars()}
    sent_keys = {
        (r.document_id, r.expires_on, r.days_before) for r in (await db.execute(select(DocumentReminder))).scalars()
    }
    sms = get_sms_sender()
    count = 0

    docs = (
        await db.execute(
            select(ComplianceDocument).where(
                ComplianceDocument.expires_on >= today,
                ComplianceDocument.expires_on <= date.fromordinal(today.toordinal() + max(REMINDER_DAYS)),
            )
        )
    ).scalars()
    for doc in docs:
        days_left = (doc.expires_on - today).days
        crossed = [d for d in REMINDER_DAYS if d >= days_left and (doc.id, doc.expires_on, d) not in sent_keys]
        if not crossed:
            continue

        if doc.vehicle_id is not None:
            subject = vehicles[doc.vehicle_id].registration if doc.vehicle_id in vehicles else "a vehicle"
            phones = {m.user.phone for m in managers}
        else:
            holder = members.get(doc.membership_id)
            subject = holder.user.name if holder else "a staff member"
            phones = {m.user.phone for m in managers}
            if holder is not None and holder.user.phone:
                phones.add(holder.user.phone)

        when = "today" if days_left == 0 else f"in {days_left} day{'s' if days_left != 1 else ''}"
        message = f"FleetTms: {LABELS[doc.doc_type.value]} for {subject} expires {when} ({doc.expires_on.isoformat()})."
        for phone in sorted(phones):
            await sms.send(phone, message)
            count += 1
        for days in crossed:
            db.add(DocumentReminder(document_id=doc.id, expires_on=doc.expires_on, days_before=days))
    await db.commit()
    return count


async def send_document_reminders(today: date | None = None) -> int:
    """Runs across every business. `today` is injectable so tests can use fake dates."""
    today = today or nairobi_today()
    total = 0
    async with get_sessionmaker()() as db:
        business_ids = (await db.execute(select(Business.id))).scalars().all()
    for business_id in business_ids:
        async with get_sessionmaker()() as db:
            current_business_id.set(business_id)
            try:
                total += await _send_for_business(db, today)
            finally:
                current_business_id.set(None)
    log.info("Sent %s document reminder messages", total)
    return total


async def document_reminders_job(ctx: dict) -> int:
    return await send_document_reminders()
