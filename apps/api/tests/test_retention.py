"""The retention policy (masterplan 11.3), one row of the table at a time."""

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError

from app import retention, storage
from app.config import settings
from app.db import get_sessionmaker
from app.models import (
    AuditLog,
    Business,
    Expense,
    Incident,
    IncidentType,
    LocationPoint,
    Membership,
    MembershipStatus,
    Message,
    Photo,
    StaffProfile,
    Subscription,
    User,
)
from app.tenancy import current_business_id
from tests.helpers import bearer, owner_session
from tests.shots import begin_trip, fleet, jpeg, photo_id


def now() -> datetime:
    return datetime.now(UTC)


async def business_id_of(client, tokens) -> uuid.UUID:
    return uuid.UUID((await client.get("/auth/me", headers=bearer(tokens))).json()["business"]["id"])


@asynccontextmanager
async def inside(business_id):
    current_business_id.set(business_id)
    try:
        async with get_sessionmaker()() as db:
            yield db
    finally:
        current_business_id.set(None)


async def count(business_id, model) -> int:
    async with inside(business_id) as db:
        return (await db.execute(select(func.count()).select_from(model))).scalar_one()


async def backdate_photos(business_id, days, only=None):
    async with inside(business_id) as db:
        stmt = update(Photo).values(created_at=now() - timedelta(days=days))
        if only:
            stmt = stmt.where(Photo.id.in_([uuid.UUID(i) for i in only]))
        await db.execute(stmt)
        await db.commit()


async def distinct_photo(client, tokens, n, kind="receipt"):
    return await photo_id(client, tokens, kind, data=jpeg(size=(640 + n, 480)))


# ---- photos: 24 months, unless tied to something open -------------------------------------------------------------------


async def test_a_photo_older_than_24_months_loses_its_picture_but_keeps_its_record(client):
    f = await fleet(client)
    bid = await business_id_of(client, f.owner)
    old, recent = await distinct_photo(client, f.driver, 1), await distinct_photo(client, f.driver, 2)
    await backdate_photos(bid, 800, only=[old])
    async with inside(bid) as db:
        key = (await db.get(Photo, uuid.UUID(old))).storage_key
    assert await storage.exists(key)

    result = await retention.purge_old_photos()
    assert result == {"photos_purged": 1, "photos_kept_for_open_matters": 0}
    assert not await storage.exists(key)
    async with inside(bid) as db:
        gone, kept = await db.get(Photo, uuid.UUID(old)), await db.get(Photo, uuid.UUID(recent))
    assert gone.purged_at is not None and gone.lat is None and gone.lng is None and gone.sha256  # the record stays, the place does not
    assert kept.purged_at is None and kept.lat is not None
    from app.photos import photo_out

    assert photo_out(gone)["purged"] is True and photo_out(gone)["url"] is None
    assert photo_out(kept)["purged"] is False and photo_out(kept)["url"]
    assert (await retention.purge_old_photos()) == {"photos_purged": 0, "photos_kept_for_open_matters": 0}  # nothing twice


async def test_an_old_photo_tied_to_an_open_incident_a_claim_or_an_alert_is_kept(client):
    f = await fleet(client)
    bid = await business_id_of(client, f.owner)
    open_incident = await distinct_photo(client, f.driver, 1)
    resolved_incident = await distinct_photo(client, f.driver, 2)
    evidence = await distinct_photo(client, f.driver, 3)
    await backdate_photos(bid, 900)
    async with inside(bid) as db:
        for photo, status in ((open_incident, "open"), (resolved_incident, "resolved")):
            db.add(Incident(type=IncidentType.ACCIDENT, occurred_at=now() - timedelta(days=900), photo_ids=[photo], status=status, vehicle_id=uuid.UUID(f.vehicle["id"])))
        from app.models import FraudAlert

        db.add(FraudAlert(kind="odometer_gap", severity="amber", title="Odometer jump", status="open", dedupe_key="t1", evidence={"photo_id": evidence}, vehicle_id=uuid.UUID(f.vehicle["id"])))
        await db.commit()
    result = await retention.purge_old_photos()
    assert result["photos_kept_for_open_matters"] == 2
    async with inside(bid) as db:
        states = {p: (await db.get(Photo, uuid.UUID(p))).purged_at is not None for p in (open_incident, resolved_incident, evidence)}
    assert states == {open_incident: False, resolved_incident: True, evidence: False}


# ---- the audit trail: 5 years, enforced by the database -----------------------------------------------------------------


async def seed_audit(business_id, age_days, action):
    async with inside(business_id) as db:
        row = AuditLog(actor_user_id=None, action=action, entity_type="test", created_at=now() - timedelta(days=age_days))
        db.add(row)
        await db.commit()


async def test_audit_entries_over_five_years_old_are_deleted_and_younger_ones_never_are(client):
    owner, _ = await owner_session(client)
    bid = await business_id_of(client, owner)
    for age, action in ((2200, "old.six"), (1900, "old.five_and_a_bit"), (1500, "young.four"), (5, "young.recent")):
        await seed_audit(bid, age, action)
    assert await retention.purge_old_audit() == 2
    async with inside(bid) as db:
        actions = set((await db.execute(select(AuditLog.action).where(AuditLog.action.like("old.%") | AuditLog.action.like("young.%")))).scalars())
    assert actions == {"young.four", "young.recent"}


async def test_the_database_itself_refuses_to_delete_recent_or_any_audit_row_without_the_retention_switch(client):
    owner, _ = await owner_session(client)
    bid = await business_id_of(client, owner)
    await seed_audit(bid, 5, "young.recent")
    await seed_audit(bid, 2200, "old.six")

    async def attempt(statement, switch):
        async with inside(bid) as db:
            if switch:
                await db.execute(text("SELECT set_config('app.audit_purge', 'on', true)"))
            await db.execute(statement)
            await db.commit()

    from sqlalchemy import delete

    with pytest.raises(DBAPIError, match="append-only"):
        await attempt(delete(AuditLog).where(AuditLog.action == "young.recent"), switch=True)  # too young, even with the switch
    with pytest.raises(DBAPIError, match="append-only"):
        await attempt(delete(AuditLog).where(AuditLog.action == "old.six"), switch=False)  # old enough, but nobody said so
    with pytest.raises(DBAPIError, match="append-only"):
        await attempt(update(AuditLog).where(AuditLog.action == "old.six").values(note="rewritten"), switch=True)  # never edited
    await attempt(delete(AuditLog).where(AuditLog.action == "old.six"), switch=True)  # the one allowed case


# ---- former staff -------------------------------------------------------------------------------------------------------


async def revoke(client, f, phone, days_ago):
    membership = f.ids[phone]
    async with inside(await business_id_of(client, f.owner)) as db:
        m = await db.get(Membership, uuid.UUID(membership))
        m.status, m.revoked_at = MembershipStatus.REVOKED, now() - timedelta(days=days_ago)
        await db.commit()
    return uuid.UUID(membership)


async def test_a_person_who_left_over_five_years_ago_is_made_anonymous_but_their_work_stays(client):
    f = await fleet(client)
    bid = await business_id_of(client, f.owner)
    trip = await begin_trip(client, f)
    assert (await client.post("/expenses", headers=bearer(f.driver), json={"category": "toll", "amount_cents": 50_000, "vehicle_id": f.vehicle["id"], "trip_id": trip["id"]})).status_code == 201
    driver_m = await revoke(client, f, "+254712345678", 2000)
    turnboy_m = await revoke(client, f, "+254722345678", 400)  # left last year: still within the retention
    assert await retention.anonymise_former_staff() == 1
    async with inside(bid) as db:
        gone = await db.get(Membership, driver_m)
        user = await db.get(User, gone.user_id)
        kept_m = await db.get(Membership, turnboy_m)
        kept_user = await db.get(User, kept_m.user_id)
        assert gone.anonymised_at is not None and (user.name, user.email, user.phone, user.password_hash, user.is_active) == (retention.ANONYMOUS_NAME, None, None, None, False)
        assert (await db.execute(select(func.count()).select_from(StaffProfile).where(StaffProfile.membership_id == driver_m))).scalar_one() == 0
        assert kept_m.anonymised_at is None and kept_user.phone is not None
        assert (await db.execute(select(func.count()).select_from(Expense))).scalar_one() == 1  # what they did is the business's record
        audited = (await db.execute(select(AuditLog.action).where(AuditLog.action == "retention.person_anonymised"))).scalars().all()
        assert len(audited) == 1
    assert await retention.anonymise_former_staff() == 0


async def test_a_person_who_works_for_another_business_too_is_not_made_anonymous(client):
    f = await fleet(client)
    bid = await business_id_of(client, f.owner)
    membership = await revoke(client, f, "+254712345678", 2000)
    async with inside(bid) as db:
        user_id = (await db.get(Membership, membership)).user_id
    other, _ = await owner_session(client, "Bravo Transporters", "b@example.com")
    other_id = await business_id_of(client, other)
    async with inside(other_id) as db:
        db.add(Membership(user_id=user_id))
        await db.commit()
    await retention.anonymise_former_staff()
    async with inside(bid) as db:
        user = await db.get(User, user_id)
        assert user.phone is not None and user.is_active  # still someone else's employee
        assert (await db.get(Membership, membership)).anonymised_at is not None  # but this business no longer holds their details
        assert (await db.execute(select(func.count()).select_from(StaffProfile).where(StaffProfile.membership_id == membership))).scalar_one() == 0


# ---- cancelling ---------------------------------------------------------------------------------------------------------


async def test_cancelling_makes_the_account_read_only_at_once_and_can_be_taken_back(client, billing):
    owner, _ = await owner_session(client)
    cancelled = await client.post("/subscription/cancel", headers=bearer(owner), json={"reason": "Selling the lorries"})
    assert cancelled.status_code == 200, cancelled.text
    body = cancelled.json()
    assert body["access"]["writable"] is False and body["cancelled_at"] and body["data_removed_on"]
    assert (await client.post("/depots", headers=bearer(owner), json={"name": "Yard"})).status_code == 402
    assert (await client.get("/depots", headers=bearer(owner))).status_code == 200  # still readable
    assert (await client.post("/data-exports", headers=bearer(owner), json={"include_photos": False})).status_code < 300  # and exportable
    assert (await client.post("/subscription/cancel", headers=bearer(owner), json={})).status_code == 409
    assert (await client.post("/subscription/reactivate", headers=bearer(owner))).status_code == 200
    assert (await client.post("/subscription/reactivate", headers=bearer(owner))).status_code == 409
    assert "subscription.cancelled" in [a["action"] for a in (await client.get("/audit", headers=bearer(owner))).json()]


async def cancelled_business(client, days_ago):
    f = await fleet(client)
    bid = await business_id_of(client, f.owner)
    trip = await begin_trip(client, f)
    await client.post("/expenses", headers=bearer(f.driver), json={"category": "toll", "amount_cents": 50_000, "vehicle_id": f.vehicle["id"], "trip_id": trip["id"]})
    await client.post("/messages", headers=bearer(f.owner), json={"body": "Use Athi River today.", "all_drivers": True})
    async with inside(bid) as db:
        db.add(LocationPoint(recorded_at=now() - timedelta(days=2), vehicle_id=uuid.UUID(f.vehicle["id"]), trip_id=uuid.UUID(trip["id"]), lat=-1.3, lng=36.8))
        await db.commit()
    assert (await client.post("/subscription/cancel", headers=bearer(f.owner), json={})).status_code == 200
    async with inside(bid) as db:
        sub = (await db.execute(select(Subscription))).scalars().one()
        sub.cancelled_at = now() - timedelta(days=days_ago)
        await db.commit()
    return bid


async def test_nothing_is_removed_from_a_cancelled_business_before_its_90_days_are_up(client):
    bid = await cancelled_business(client, 89)
    assert await retention.process_cancelled() == {"wound_down": 0, "erased": 0}
    assert await count(bid, Photo) > 0 and await count(bid, Message) == 1 and await count(bid, LocationPoint) == 1


async def test_after_90_days_personal_data_images_and_tracking_go_but_the_legally_kept_records_stay(client):
    bid = await cancelled_business(client, 91)
    photos_before = await count(bid, Photo)
    assert photos_before > 0
    async with inside(bid) as db:
        keys = [p.storage_key for p in (await db.execute(select(Photo))).scalars()]
    assert any([await storage.exists(k) for k in keys])
    assert await retention.process_cancelled() == {"wound_down": 1, "erased": 0}
    assert not any([await storage.exists(k) for k in keys])  # every image file is gone
    assert await count(bid, LocationPoint) == 0 and await count(bid, Message) == 0 and await count(bid, StaffProfile) == 0
    assert await count(bid, Expense) == 1  # financial records are kept for their own period
    assert await count(bid, Photo) == photos_before  # the records of the photos stay, without the pictures
    async with inside(bid) as db:
        business = await db.get(Business, bid)
        assert business.wound_down_at is not None
        names = set((await db.execute(select(User.name).join(Membership, Membership.user_id == User.id))).scalars())
        assert names & {"driver user", "turnboy user"} == set()  # the people are anonymous
        assert (await db.execute(select(func.count()).select_from(AuditLog).where(AuditLog.action == "retention.business_wound_down"))).scalar_one() == 1
    assert await retention.process_cancelled() == {"wound_down": 0, "erased": 0}  # once only


async def test_after_the_legal_retention_the_whole_business_is_erased_and_nobody_elses_is_touched(client):
    other, _ = await owner_session(client, "Bravo Transporters", "b@example.com")
    other_id = await business_id_of(client, other)
    await client.post("/depots", headers=bearer(other), json={"name": "Bravo Yard"})
    audit_before = await count(other_id, AuditLog)

    bid = await cancelled_business(client, 4)
    assert await retention.process_cancelled() == {"wound_down": 0, "erased": 0}
    async with inside(bid) as db:
        sub = (await db.execute(select(Subscription))).scalars().one()
        sub.cancelled_at = now() - timedelta(days=settings.financial_retention_days + 1)
        await db.commit()
    assert await retention.process_cancelled() == {"wound_down": 0, "erased": 1}  # straight to erasure: the retention has run out
    async with get_sessionmaker()() as db:
        assert await db.get(Business, bid) is None
        for table in ("vehicles", "trips", "expenses", "photos", "memberships", "audit_logs", "subscriptions"):
            leftover = (await db.execute(text(f"SELECT count(*) FROM {table} WHERE business_id = :b"), {"b": bid})).scalar_one()
            assert leftover == 0, table
        strangers = (await db.execute(select(func.count()).select_from(User).where(User.name == retention.ANONYMOUS_NAME))).scalar_one()
    assert strangers == 0  # nobody anonymous is left over without a business
    assert await count(other_id, AuditLog) == audit_before
    assert len((await client.get("/depots", headers=bearer(other))).json()) == 1


async def test_the_daily_job_runs_the_whole_policy_and_is_registered_with_the_worker(client):
    from app.worker import WorkerSettings

    assert retention.retention_job in WorkerSettings.functions
    assert any(job.coroutine is retention.retention_job for job in WorkerSettings.cron_jobs)
    result = await retention.retention_job({})
    assert set(result) >= {"photos_purged", "photos_kept_for_open_matters", "audit_entries_purged", "people_anonymised", "wound_down", "erased"}
