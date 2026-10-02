"""Helpers for Sprint 10 tests. Money and trips are seeded straight into the database at chosen dates, so a test about profit does
not need a whole delivery for every trip."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select, update

from app.db import get_sessionmaker
from app.lease_rules import add_months
from app.models import BillingMethod as BM
from app.models import (
    CrewAssignment,
    Expense,
    ExpenseCategory,
    ExpenseStatus,
    FuelEntry,
    Invoice,
    InvoiceLine,
    Job,
    Membership,
    StaffProfile,
    Trip,
    TripStatus,
    User,
)
from app.numbering import create_numbered
from app.reminders import NAIROBI, nairobi_today
from app.tenancy import current_business_id
from tests.fleet import add_vehicle
from tests.helpers import PASSWORD, bearer, login, owner_session
from tests.money import business_id


def month_start(offset: int = 0):
    return add_months(nairobi_today().replace(day=1), offset)


def moment(month_offset: int = 0, day: int = 10, hour: int = 10) -> datetime:
    """A moment on a day of the month `month_offset` months from now (Nairobi time)."""
    first = month_start(month_offset)
    return datetime(first.year, first.month, day, hour, tzinfo=NAIROBI).astimezone(UTC)


async def in_db(fn, business="Kamau Haulage"):
    async with get_sessionmaker()() as db:
        current_business_id.set(await business_id(business))
        try:
            result = await fn(db)
            await db.commit()
            return result
        finally:
            current_business_id.set(None)


async def lease_setup(client, direction="in", party_name="Wanjiku Transporters", registration="KDB 404D", business="Kamau Haulage"):
    """An owner, a lessor (or lessee) and a vehicle of the matching ownership type."""
    owner, _ = await owner_session(client, business, f"owner@{business.split()[0].lower()}.example")
    kind = "lessor" if direction == "in" else "lessee"
    party = (await client.post("/parties", headers=bearer(owner), json={"kind": kind, "name": party_name, "phone": "0711000111", "email": "lessor@example.com"})).json()
    vehicle = await add_vehicle(client, owner, registration, ownership_type="leased_in" if direction == "in" else "leased_out", party_id=party["id"])
    return owner, vehicle, party


def lease_body(vehicle, party, direction="in", **extra):
    return {"direction": direction, "vehicle_id": vehicle["id"], "party_id": party["id"], "start_date": month_start(-3).isoformat(), "revenue_pct": 30, "deposit_cents": 5_000_000, **extra}


async def make_lease(client, owner, vehicle, party, direction="in", **extra):
    res = await client.post("/leases", headers=bearer(owner), json=lease_body(vehicle, party, direction, **extra))
    assert res.status_code == 201, res.text
    return res.json()


async def seed_client(name="Bamburi Cement") -> uuid.UUID:
    from app.models import Client

    async def make(db):
        c = Client(name=name, billing_method=BM.PER_TRIP, rate_cents=1)
        db.add(c)
        await db.flush()
        return c.id

    return await in_db(make)


async def seed_job(client_id, method=BM.PER_TRIP, rate_cents=0) -> uuid.UUID:
    async def make(db):
        job = await create_numbered(db, Job, "J", client_id=client_id, billing_method=method, rate_cents=rate_cents, weight_tonnes=Decimal(10))
        return job.id

    return await in_db(make)


async def seed_trip(vehicle_id, *, revenue_cents=1_000_000, at: datetime | None = None, km=480, client_id=None, job_id=None, driver_membership_id=None, invoice=True, loaded=True, origin="Mombasa", destination="Nairobi") -> uuid.UUID:
    """A delivered trip with its invoice (revenue before VAT)."""
    at = at or moment(0)

    async def make(db):
        trip = Trip(
            vehicle_id=uuid.UUID(str(vehicle_id)), status=TripStatus.COMPLETED, origin=origin, destination=destination, started_at=at - timedelta(hours=10), loaded_at=at - timedelta(hours=9) if loaded else None,
            delivered_at=at, ended_at=at, distance_km=km, job_id=job_id, driver_membership_id=driver_membership_id, scheduled_for=at - timedelta(hours=11),
        )  # fmt: skip
        db.add(trip)
        await db.flush()
        if invoice and revenue_cents:
            cid = client_id or await _any_client(db)
            await create_numbered(
                db, Invoice, "INV", client_id=cid, trip_id=trip.id, job_id=job_id, kind="trip", issue_date=at.astimezone(NAIROBI).date(), due_date=at.astimezone(NAIROBI).date() + timedelta(days=30),
                status="issued", subtotal_cents=revenue_cents, vat_pct=Decimal(0), vat_cents=0, total_cents=revenue_cents, payments=[],
                lines=[InvoiceLine(description="Transport", quantity=Decimal(1), unit_cents=revenue_cents, amount_cents=revenue_cents, sort_order=0, trip_id=trip.id)],
            )  # fmt: skip
        return trip.id

    return await in_db(make)


async def _any_client(db):
    from app.models import Client

    found = (await db.execute(select(Client.id).limit(1))).scalar_one_or_none()
    if found:
        return found
    c = Client(name="Seed Client", billing_method=BM.PER_TRIP, rate_cents=1)
    db.add(c)
    await db.flush()
    return c.id


async def seed_fuel(vehicle_id, cents, at: datetime | None = None, trip_id=None):
    async def make(db):
        db.add(FuelEntry(vehicle_id=uuid.UUID(str(vehicle_id)), trip_id=trip_id, litres=Decimal(100), price_per_litre_cents=1, amount_cents=cents, captured_at=at or moment(0)))

    await in_db(make)


async def seed_expense(vehicle_id, cents, category=ExpenseCategory.TOLL, at: datetime | None = None, trip_id=None, note=None, status=ExpenseStatus.RECORDED) -> uuid.UUID:
    async def make(db):
        e = Expense(vehicle_id=uuid.UUID(str(vehicle_id)) if vehicle_id else None, trip_id=trip_id, category=category, amount_cents=cents, spent_at=at or moment(0), status=status, note=note)
        db.add(e)
        await db.flush()
        return e.id

    return await in_db(make)


async def seed_crew(vehicle_id, membership_id, salary_cents, since_months=-3, role="driver", business="Kamau Haulage"):
    """Crew a vehicle since some months ago (never ended) and give the person a salary."""
    async def make(db):
        db.add(CrewAssignment(vehicle_id=uuid.UUID(str(vehicle_id)), membership_id=uuid.UUID(str(membership_id)), role=role, started_at=moment(since_months, 1)))
        profile = (await db.execute(select(StaffProfile).where(StaffProfile.membership_id == uuid.UUID(str(membership_id))))).scalar_one_or_none()
        if profile is None:
            db.add(StaffProfile(membership_id=uuid.UUID(str(membership_id)), monthly_salary_cents=salary_cents))
        else:
            profile.monthly_salary_cents = salary_cents

    await in_db(make, business)


async def seed_staff(client, owner, name, phone, role="driver", salary_cents=None, business="Kamau Haulage") -> str:
    """A staff member (drivers and turnboys sign in by phone); returns their membership id."""
    from tests.helpers import driver_session

    await driver_session(client, owner, phone, role=role)
    rows = (await client.get("/staff", headers=bearer(owner))).json()
    mid = next(r["membership_id"] for r in rows if r["phone"] == f"+254{phone[1:]}")
    if salary_cents is not None:
        async def make(db):
            profile = (await db.execute(select(StaffProfile).where(StaffProfile.membership_id == uuid.UUID(mid)))).scalar_one_or_none()
            if profile is None:
                db.add(StaffProfile(membership_id=uuid.UUID(mid), monthly_salary_cents=salary_cents))
            else:
                profile.monthly_salary_cents = salary_cents

        await in_db(make, business)
    return mid


async def lessor_login(client, owner, party, email="lessor@portal.example"):
    res = await client.post("/users", headers=bearer(owner), json={"name": "Lessor Person", "email": email, "roles": ["lessor"], "party_id": party["id"]})
    assert res.status_code == 201, res.text
    accepted = await client.post("/auth/accept-invite", json={"token": res.json()["invite_token"], "password": PASSWORD})
    assert accepted.status_code == 204, accepted.text
    login_res = await login(client, email)
    assert login_res.status_code == 200, login_res.text
    return login_res.json()


async def set_phone(email_or_name_like: str, phone: str, business="Kamau Haulage"):
    async def go(db):
        await db.execute(update(User).where(User.email == email_or_name_like).values(phone=phone), execution_options={"skip_tenant": True})

    await in_db(go, business)


__all__ = ["Membership"]
