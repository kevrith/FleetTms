"""The retention policy (masterplan 11.3), run daily by the worker.

| Data                         | What happens                                                                                         |
| Raw GPS points               | deleted after 12 months, once the trip totals are kept (tracking_jobs.purge_old_points)              |
| Odometer and receipt photos  | the image is deleted after 24 months unless tied to an open dispute or alert; the record stays       |
| Audit trail                  | deleted after 5 years (the database refuses anything younger)                                        |
| Financial records            | never deleted on a timer: the five years is a minimum, and ends only when a cancelled business is erased |
| Former staff                 | staff details removed and the person anonymised 5 years after they left                              |
| Cancelled businesses         | read-only for 90 days for export; then personal data, images and tracking are removed; the legally   |
|                              | required records stay until 5 years after cancelling, then the whole business is erased              |

Nothing here writes a person's details to a log; only counts.
"""

import json
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, storage
from app.config import settings
from app.db import get_sessionmaker
from app.models import (
    AskQuestion,
    AuditLog,
    AuthSession,
    BehaviourEvent,
    BehaviourState,
    Business,
    ClaimStatus,
    ComplianceDocument,
    DataExport,
    DeviceCheck,
    DocumentReading,
    Feedback,
    FraudAlert,
    GeofenceEvent,
    GeofencePresence,
    Incident,
    InsuranceClaim,
    LocationPoint,
    Membership,
    MembershipStatus,
    Message,
    MessageRecipient,
    Photo,
    SosAlert,
    StaffProfile,
    Subscription,
    SupportGrant,
    SyncReceipt,
    TrackerAlert,
    TrackingGap,
    TrackingLink,
    User,
)
from app.tenancy import current_business_id

log = logging.getLogger(__name__)

ANONYMOUS_NAME = "Former user"
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

# What is removed from a cancelled business after its 90 days, in an order the foreign keys allow. Everything else stays (invoices,
# payments, expenses, fuel, payroll, leases, the vehicles and trips those refer to, consents and the audit trail) for the legal period.
WIND_DOWN = (
    MessageRecipient, Message, AskQuestion, DataExport, DocumentReading, LocationPoint, TrackingGap, TrackingLink, GeofenceEvent, GeofencePresence,
    BehaviourEvent, BehaviourState, SosAlert, TrackerAlert, SyncReceipt, DeviceCheck, Feedback, SupportGrant, ComplianceDocument, StaffProfile,
)  # fmt: skip


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


async def _each_business(work, *, only: list[uuid.UUID] | None = None) -> dict:
    """Runs `work(db)` once for every business, inside that business's tenant context, committing after each."""
    async with get_sessionmaker()() as db:
        ids = [i for i in (await db.execute(select(Business.id))).scalars().all() if only is None or i in only]
    totals: dict[str, int] = {}
    for business_id in ids:
        async with get_sessionmaker()() as db:
            current_business_id.set(business_id)
            try:
                for key, count in (await work(db)).items():
                    totals[key] = totals.get(key, 0) + count
                await db.commit()
            finally:
                current_business_id.set(None)
    return totals


# ---- photos -------------------------------------------------------------------------------------------------------------


async def protected_photo_ids(db: AsyncSession) -> set[str]:
    """Photos that are evidence in something still open: an unresolved incident, a claim not yet settled, a fraud alert that is
    open or confirmed. They are kept whatever their age."""
    keep: set[str] = set()
    for incident in (await db.execute(select(Incident).where(Incident.status == "open"))).scalars():
        keep.update(incident.photo_ids or [])
    unsettled = (await db.execute(select(InsuranceClaim).where(InsuranceClaim.status.not_in([ClaimStatus.PAID, ClaimStatus.REJECTED])))).scalars().all()
    for claim in unsettled:
        keep.update(claim.document_photo_ids or [])
        incident = await db.get(Incident, claim.incident_id)
        if incident is not None:
            keep.update(incident.photo_ids or [])
    for alert in (await db.execute(select(FraudAlert).where(FraudAlert.status.in_(("open", "confirmed"))))).scalars():
        keep.update(UUID.findall(json.dumps(alert.evidence or {}, default=str)))
    return keep


async def _purge_photos_of(db: AsyncSession, cutoff: datetime, now: datetime, *, everything: bool = False) -> dict:
    keep = set() if everything else await protected_photo_ids(db)
    stmt = select(Photo).where(Photo.purged_at.is_(None))
    if not everything:
        stmt = stmt.where(Photo.created_at < cutoff)
    purged = kept = 0
    for photo in (await db.execute(stmt)).scalars().all():
        if str(photo.id) in keep:
            kept += 1
            continue
        storage.delete(photo.storage_key)
        photo.purged_at, photo.lat, photo.lng = now, None, None  # the record of it stays; the picture and where it was taken do not
        purged += 1
    return {"photos_purged": purged, "photos_kept_for_open_matters": kept}


async def purge_old_photos(now: datetime | None = None) -> dict:
    now = _now(now)
    cutoff = now - timedelta(days=settings.photo_retention_days)
    return {"photos_purged": 0, "photos_kept_for_open_matters": 0, **await _each_business(lambda db: _purge_photos_of(db, cutoff, now))}


# ---- the audit trail ----------------------------------------------------------------------------------------------------


async def purge_old_audit(now: datetime | None = None) -> int:
    """The audit trail is append-only. The one exception is this: rows older than five years, and only when this job says so. The
    five years is also checked inside the database, so a wrong setting here cannot delete recent history."""
    cutoff = _now(now) - timedelta(days=max(settings.audit_retention_days, 1826))
    async with get_sessionmaker()() as db:
        await db.execute(text("SELECT set_config('app.audit_purge', 'on', true)"))
        result = await db.execute(delete(AuditLog).where(AuditLog.created_at < cutoff).execution_options(skip_tenant=True))
        await db.commit()
    removed = result.rowcount or 0
    if removed:
        log.info("Deleted %s audit entries older than five years", removed)
    return removed


# ---- people -------------------------------------------------------------------------------------------------------------


async def anonymise_membership(db: AsyncSession, membership: Membership, now: datetime) -> bool:
    """Removes what a business holds about one person who has left: their staff details and personal documents are deleted, and the
    person is made anonymous if they belong to no other business. What they did (trips, fuel, expenses) stays, under the anonymous name,
    because those are the business's records. Returns True if the person themselves was made anonymous."""
    await db.execute(delete(StaffProfile).where(StaffProfile.membership_id == membership.id))
    await db.execute(delete(ComplianceDocument).where(ComplianceDocument.membership_id == membership.id))
    membership.status, membership.anonymised_at = MembershipStatus.REVOKED, now
    membership.revoked_at = membership.revoked_at or now
    others = (
        await db.execute(select(func.count()).select_from(Membership).where(Membership.user_id == membership.user_id, Membership.id != membership.id).execution_options(skip_tenant=True))
    ).scalar_one()
    user = await db.get(User, membership.user_id)
    if others or user is None or user.is_platform_admin:
        return False
    user.name, user.email, user.phone = ANONYMOUS_NAME, None, None
    user.password_hash = user.totp_secret = user.invite_token_hash = None
    user.totp_enabled = user.sms_2fa_enabled = user.is_active = False
    await db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    return True


async def anonymise_former_staff(now: datetime | None = None) -> int:
    now = _now(now)
    cutoff = now - timedelta(days=settings.former_staff_retention_days)

    async def work(db: AsyncSession) -> dict:
        rows = (
            await db.execute(select(Membership).where(Membership.status == MembershipStatus.REVOKED, Membership.revoked_at < cutoff, Membership.anonymised_at.is_(None)))
        ).scalars().all()
        done = 0
        for membership in rows:
            await anonymise_membership(db, membership, now)
            audit.record(db, actor_user_id=None, action="retention.person_anonymised", entity_type="membership", entity_id=membership.id, note="Staff details removed after the retention period")
            done += 1
        return {"people": done}

    return (await _each_business(work)).get("people", 0)


# ---- cancelled businesses -----------------------------------------------------------------------------------------------


def wind_down_due(sub: Subscription | None, business: Business, now: datetime) -> bool:
    return bool(sub and sub.cancelled_at and business.wound_down_at is None and sub.cancelled_at + timedelta(days=settings.cancelled_grace_days) <= now)


def erasure_due(sub: Subscription | None, now: datetime) -> bool:
    return bool(sub and sub.cancelled_at and sub.cancelled_at + timedelta(days=settings.financial_retention_days) <= now)


async def wind_down(db: AsyncSession, business: Business, now: datetime) -> dict:
    """Stage one, 90 days after cancelling: every image, every tracking and messaging record and every person's details go. The records
    the law requires stay (and the people in them show as anonymous) until stage two."""
    counts = await _purge_photos_of(db, now, now, everything=True)
    for model in WIND_DOWN:
        if model is DataExport:
            for export in (await db.execute(select(DataExport))).scalars():
                if export.storage_key:
                    storage.delete(export.storage_key)
        result = await db.execute(delete(model))
        counts[model.__tablename__] = result.rowcount or 0
    people = 0
    for membership in (await db.execute(select(Membership).where(Membership.anonymised_at.is_(None)))).scalars().all():
        people += await anonymise_membership(db, membership, now)
    business.wound_down_at = now
    audit.record(db, actor_user_id=None, action="retention.business_wound_down", entity_type="business", entity_id=business.id, note="90 days after cancelling: personal data and images removed")
    counts["people_anonymised"] = people
    return counts


async def erase_business(db: AsyncSession, business_id: uuid.UUID) -> None:
    """Stage two, when the legal retention of a cancelled business has run out: everything it ever had is deleted, including its audit
    trail (the database allows that only for the business named here)."""
    await db.execute(text("SELECT set_config('app.audit_purge', 'on', true), set_config('app.business_erasure', :b, true)"), {"b": str(business_id)})
    await db.execute(delete(Business).where(Business.id == business_id))
    # people who belonged only to this business are already anonymous and now belong to nothing
    orphans = select(User.id).where(User.name == ANONYMOUS_NAME, ~select(Membership.id).where(Membership.user_id == User.id).exists())
    await db.execute(delete(User).where(User.id.in_(orphans.scalar_subquery())).execution_options(skip_tenant=True))


async def process_cancelled(now: datetime | None = None) -> dict:
    now = _now(now)
    async with get_sessionmaker()() as db:
        ids = [
            i
            for i in (await db.execute(select(Subscription.business_id).where(Subscription.cancelled_at.is_not(None)).execution_options(skip_tenant=True))).scalars().all()
        ]
    winding = erased = 0
    for business_id in ids:
        async with get_sessionmaker()() as db:
            current_business_id.set(business_id)
            try:
                business = await db.get(Business, business_id)
                sub = (await db.execute(select(Subscription))).scalars().first()
                if business is None or sub is None:
                    continue
                if erasure_due(sub, now):
                    await erase_business(db, business_id)
                    await db.commit()
                    erased += 1
                elif wind_down_due(sub, business, now):
                    await wind_down(db, business, now)
                    await db.commit()
                    winding += 1
            finally:
                current_business_id.set(None)
    return {"wound_down": winding, "erased": erased}


async def run_all(now: datetime | None = None) -> dict:
    """Everything in the policy, once. Called by the daily worker job."""
    out: dict = {}
    out.update(await purge_old_photos(now))
    out["audit_entries_purged"] = await purge_old_audit(now)
    out["people_anonymised"] = await anonymise_former_staff(now)
    out.update(await process_cancelled(now))
    log.info("Retention run: %s", out)
    return out


async def retention_job(ctx: dict) -> dict:
    return await run_all()
