"""Demo data: a realistic Kenyan fleet for local development. Usage: python -m app.cli seed-demo

Needs DEMO_OWNER_EMAIL and DEMO_OWNER_PASSWORD in the environment (see .env.example). Staff phone numbers are
fake (0712 000 xxx). Safe to run once; it refuses if the demo business already exists.
"""

import os
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db import get_sessionmaker
from app.models import (
    Business,
    ComplianceDocType,
    ComplianceDocument,
    CrewAssignment,
    CrewRole,
    Depot,
    Membership,
    OwnershipType,
    Party,
    PartyKind,
    Role,
    RoleAssignment,
    StaffProfile,
    User,
    Vehicle,
)
from app.reminders import nairobi_today
from app.security import hash_password
from app.tenancy import current_business_id

DEMO_NAME = "Kamau Haulage (demo)"

# registration, make, model, tonnes, tank, kmpl loaded, kmpl empty, odometer, tier, depot, ownership, party, gvw, axles
VEHICLES = [
    ("KCA 101A", "Isuzu", "FVZ", 14, 300, 3.8, 5.2, 214_500, "standard", 0, "owned", None, 24000, "3"),
    ("KCB 202B", "Mitsubishi", "Fuso FP", 10, 200, 4.5, 6.0, 98_200, "basic", 0, "owned", None, 16000, "2"),
    ("KDA 303C", "Scania", "R450", 30, 600, 2.4, 3.4, 410_000, "premium", 1, "asset_financed", "Equity Bank", 48000, "2+3"),
    ("KDB 404D", "Isuzu", "FTR", 12, 250, 4.0, 5.5, 156_300, "basic", 1, "leased_in", "Wanjiku Transporters", 18000, "2"),
    ("KDC 505E", "Mercedes-Benz", "Actros", 28, 550, 2.6, 3.6, 330_800, "standard", 0, "leased_out", "Rift Valley Quarries", 44000, "2+3"),
    ("KDD 606F", "Hino", "500", 9, 200, 4.6, 6.2, 72_900, "basic", 0, "owned", None, 15000, "2"),
]  # fmt: skip
PARTIES = [
    (PartyKind.LESSOR, "Wanjiku Transporters", "0711000111"),
    (PartyKind.LENDER, "Equity Bank", None),
    (PartyKind.LESSEE, "Rift Valley Quarries", "0711000222"),
]
# name, phone, roles, licence number, class, vehicle index (None = unassigned)
STAFF = [
    ("Peter Otieno", "0712000001", Role.DRIVER, "DL-4471230", "CE", 0),
    ("James Mwangi", "0712000002", Role.DRIVER, "DL-3392281", "CE", 1),
    ("Hassan Omar", "0712000003", Role.DRIVER, "DL-5510926", "CE", 2),
    ("Joseph Kiprop", "0712000004", Role.DRIVER, "DL-2284417", "CE", None),
    ("Brian Odhiambo", "0712000005", Role.TURNBOY, None, None, 0),
    ("Samuel Njoroge", "0712000006", Role.TURNBOY, None, None, 1),
]  # fmt: skip


async def seed_demo() -> None:
    email = os.getenv("DEMO_OWNER_EMAIL", "").strip().lower()
    password = os.getenv("DEMO_OWNER_PASSWORD", "")
    if not email or len(password) < 10:
        sys.exit("Set DEMO_OWNER_EMAIL and DEMO_OWNER_PASSWORD (10+ characters) in .env")

    async with get_sessionmaker()() as db:
        if (await db.execute(select(Business.id).where(Business.name == DEMO_NAME))).first():
            sys.exit("The demo business already exists.")
        if (await db.execute(select(User.id).where(User.email == email))).first():
            sys.exit("An account with that email already exists. Use a different DEMO_OWNER_EMAIL.")

        business = Business(name=DEMO_NAME)
        db.add(business)
        await db.flush()
        current_business_id.set(business.id)
        try:
            owner = User(name="Demo Owner", email=email, password_hash=hash_password(password), email_verified_at=datetime.now(UTC))
            db.add(owner)
            await db.flush()
            owner_member = Membership(user_id=owner.id)
            db.add(owner_member)
            await db.flush()
            db.add(RoleAssignment(membership_id=owner_member.id, role=Role.OWNER))

            depots = [Depot(name="Nairobi Yard", location="Embakasi"), Depot(name="Mombasa Yard", location="Changamwe")]
            db.add_all(depots)
            parties = {name: Party(kind=kind, name=name, phone=phone) for kind, name, phone in PARTIES}
            db.add_all(parties.values())
            await db.flush()

            vehicles = []
            for reg, make, model, tonnes, tank, kl, ke, odo, tier, depot, own, party, gvw, axles in VEHICLES:
                vehicles.append(
                    Vehicle(
                        registration=reg, make=make, model=model, capacity_tonnes=tonnes, tank_litres=tank,
                        expected_kmpl_loaded=kl, expected_kmpl_empty=ke, odometer_km=odo, tracking_tier=tier,
                        depot_id=depots[depot].id, ownership_type=OwnershipType(own),
                        party_id=parties[party].id if party else None, gvw_limit_kg=gvw, axle_config=axles,
                    )
                )  # fmt: skip
            db.add_all(vehicles)
            await db.flush()

            today = nairobi_today()
            for i, v in enumerate(vehicles):
                # Spread expiry dates so the reminders and the "needs attention" card have something to show.
                for doc_type, days in (
                    (ComplianceDocType.INSURANCE, (7, 200, 25, 300, 120, 90)[i]),
                    (ComplianceDocType.INSPECTION, (150, 60, 220, 14, 180, 45)[i]),
                    (ComplianceDocType.NTSA_LICENCE, 330 - i * 20),
                ):
                    db.add(ComplianceDocument(doc_type=doc_type, vehicle_id=v.id, expires_on=today + timedelta(days=days)))

            for n, (name, phone, role, licence, klass, vehicle) in enumerate(STAFF):
                user = User(name=name, phone="+254" + phone[1:])
                db.add(user)
                await db.flush()
                member = Membership(user_id=user.id, depot_id=depots[0].id)
                db.add(member)
                await db.flush()
                db.add(RoleAssignment(membership_id=member.id, role=role))
                db.add(StaffProfile(membership_id=member.id, licence_number=licence, licence_class=klass))
                if licence:
                    db.add(
                        ComplianceDocument(
                            doc_type=ComplianceDocType.DRIVING_LICENCE, membership_id=member.id,
                            expires_on=today + timedelta(days=(400, 21, 500, 90)[n % 4]),
                        )
                    )  # fmt: skip
                if vehicle is not None:
                    db.add(
                        CrewAssignment(
                            vehicle_id=vehicles[vehicle].id, membership_id=member.id,
                            role=CrewRole.DRIVER if role == Role.DRIVER else CrewRole.TURNBOY,
                        )
                    )  # fmt: skip
            await db.commit()
        finally:
            current_business_id.set(None)
    print(f"Demo business created. Sign in as {email}. Password: set via DEMO_OWNER_PASSWORD in .env")
