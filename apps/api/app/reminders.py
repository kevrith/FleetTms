"""Document expiry reminders by SMS and push (masterplan 5.1 and 5.11).

A reminder goes out at 60, 30, 14, 7 and 1 days before expiry (the first early enough to find the money for an insurance renewal). Each one is recorded, so running the job twice in a
day, or again after a restart, never sends the same reminder twice. If the job missed days, only the most
urgent reminder that is due is sent, and the earlier ones are marked as covered.
"""

import logging
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import push
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
REMINDER_DAYS = (60, 30, 14, 7, 1)
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
        and (m.user.phone or m.user.push_token)
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

        phones = {m.user.phone for m in managers if m.user.phone}
        tokens = {m.user.push_token for m in managers if m.user.push_token}
        if doc.vehicle_id is not None:
            subject = vehicles[doc.vehicle_id].registration if doc.vehicle_id in vehicles else "a vehicle"
        else:
            holder = members.get(doc.membership_id)
            subject = holder.user.name if holder else "a staff member"
            if holder is not None and holder.user.phone:
                phones.add(holder.user.phone)
            if holder is not None and holder.user.push_token:
                tokens.add(holder.user.push_token)

        when = "today" if days_left == 0 else f"in {days_left} day{'s' if days_left != 1 else ''}"
        message = f"FleetTms: {LABELS[doc.doc_type.value]} for {subject} expires {when} ({doc.expires_on.isoformat()})."
        for phone in sorted(phones):
            await sms.send(phone, message)
            count += 1
        if tokens:
            await push.send(
                sorted(tokens), f"{LABELS[doc.doc_type.value]} for {subject} expires {when}", "Plan the renewal now so it does not lapse.",
                {"type": "document", "document_id": str(doc.id), "vehicle_id": str(doc.vehicle_id) if doc.vehicle_id else None},
            )  # fmt: skip
        for days in crossed:
            db.add(DocumentReminder(document_id=doc.id, expires_on=doc.expires_on, days_before=days))
    await _nag_about_lapsed(db, today, managers, members, vehicles)  # pushes only: the count stays the texts sent
    await db.commit()
    return count


LAPSED_NAG_DAYS = 30  # a push every day for this long after a document runs out, unless it is renewed


async def _nag_about_lapsed(db: AsyncSession, today: date, managers: list, members: dict, vehicles: dict) -> int:
    """A document that has run out and not been renewed: a push (no text, which costs money) every day, so a lapsed insurance cannot be
    forgotten. A renewed document is not nagged about, and neither is an old one left behind after a renewal. Returns how many were pushed."""
    docs = (await db.execute(select(ComplianceDocument).where(ComplianceDocument.expires_on < today))).scalars().all()
    if not docs:
        return 0
    newest: dict[tuple, date] = {}
    for d in (await db.execute(select(ComplianceDocument))).scalars():
        key = (d.vehicle_id, d.membership_id, d.doc_type)
        newest[key] = max(newest.get(key, d.expires_on), d.expires_on)
    done = {(r.document_id, r.expires_on, r.days_before) for r in (await db.execute(select(DocumentReminder).where(DocumentReminder.days_before < 0))).scalars()}
    pushed = 0
    for doc in docs:
        overdue = (today - doc.expires_on).days
        key = (doc.vehicle_id, doc.membership_id, doc.doc_type)
        if overdue > LAPSED_NAG_DAYS or newest[key] != doc.expires_on or (doc.id, doc.expires_on, -overdue) in done:
            continue
        tokens = {m.user.push_token for m in managers if m.user.push_token}
        if not tokens:
            continue  # nobody to tell yet; the day is not used up
        if doc.vehicle_id is not None:
            subject = vehicles[doc.vehicle_id].registration if doc.vehicle_id in vehicles else "a vehicle"
        else:
            holder = members.get(doc.membership_id)
            subject = holder.user.name if holder else "a staff member"
        when = "today" if overdue == 0 else f"{overdue} day{'s' if overdue != 1 else ''} ago"
        await push.send(
            sorted(tokens), f"{LABELS[doc.doc_type.value]} for {subject} has expired", f"It ran out {when}. Renew it, then update the date in the app.",
            {"type": "document", "document_id": str(doc.id), "vehicle_id": str(doc.vehicle_id) if doc.vehicle_id else None},
        )  # fmt: skip
        db.add(DocumentReminder(document_id=doc.id, expires_on=doc.expires_on, days_before=-overdue))
        pushed += 1
    return pushed


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
