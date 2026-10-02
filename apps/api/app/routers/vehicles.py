import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.db import get_db
from app.deps import Principal, error, require
from app.models import (
    CrewAssignment,
    CrewRole,
    Depot,
    FuelType,
    Membership,
    MembershipStatus,
    OwnershipType,
    Party,
    PartyKind,
    Role,
    TrackingTier,
    Vehicle,
)
from app.phone import normalize_phone
from app.trust import flag_summary, trust_out
from app.vehicle_scope import require_vehicle_in_scope, scope_vehicles

router = APIRouter(tags=["vehicles"])

VEHICLE_FIELDS = [
    "registration", "make", "model", "capacity_tonnes", "fuel_type", "tank_litres",
    "expected_kmpl_loaded", "expected_kmpl_empty", "odometer_km", "tracking_tier", "depot_id",
    "ownership_type", "party_id", "gvw_limit_kg", "tare_kg", "axle_config", "is_active",
]  # fmt: skip
CREW_FIELDS = ["vehicle_id", "membership_id", "role", "started_at", "ended_at"]
PARTY_FIELDS = ["kind", "name", "phone", "kra_pin", "payment_details"]

# Which kind of party each ownership type needs (None means no party).
PARTY_FOR_OWNERSHIP = {
    OwnershipType.OWNED: None,
    OwnershipType.ASSET_FINANCED: PartyKind.LENDER,
    OwnershipType.LEASED_IN: PartyKind.LESSOR,
    OwnershipType.LEASED_OUT: PartyKind.LESSEE,
}
CREW_ROLE_TO_ROLE = {CrewRole.DRIVER: Role.DRIVER, CrewRole.TURNBOY: Role.TURNBOY}


class VehicleIn(BaseModel):
    registration: str = Field(min_length=3, max_length=20)
    make: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=80)
    capacity_tonnes: Decimal | None = Field(default=None, gt=0, le=200)
    fuel_type: FuelType = FuelType.DIESEL
    tank_litres: int | None = Field(default=None, gt=0, le=5000)
    expected_kmpl_loaded: Decimal | None = Field(default=None, gt=0, le=50)
    expected_kmpl_empty: Decimal | None = Field(default=None, gt=0, le=50)
    odometer_km: int = Field(default=0, ge=0, le=5_000_000)
    tracking_tier: TrackingTier = TrackingTier.BASIC
    depot_id: uuid.UUID | None = None
    ownership_type: OwnershipType = OwnershipType.OWNED
    party_id: uuid.UUID | None = None
    gvw_limit_kg: int | None = Field(default=None, gt=0, le=100_000)
    tare_kg: int | None = Field(default=None, gt=0, le=60_000)
    axle_config: str | None = Field(default=None, max_length=20)
    is_active: bool = True

    @model_validator(mode="after")
    def _owned_has_no_party(self):
        if self.ownership_type == OwnershipType.OWNED and self.party_id is not None:
            raise ValueError("An owned vehicle has no lessor or lender.")
        return self


class PartyIn(BaseModel):
    kind: PartyKind
    name: str = Field(min_length=2, max_length=200)
    phone: str | None = None
    kra_pin: str | None = Field(default=None, max_length=20)
    payment_details: str | None = Field(default=None, max_length=1000)


class CrewIn(BaseModel):
    membership_id: uuid.UUID
    role: CrewRole


def normalize_registration(raw: str) -> str:
    return " ".join(raw.upper().split())


def vehicle_out(v: Vehicle) -> dict:
    return {
        "id": v.id,
        **{f: getattr(v, f) for f in VEHICLE_FIELDS},
        "fuel_type": v.fuel_type.value,
        "tracking_tier": v.tracking_tier.value,
        "ownership_type": v.ownership_type.value,
    }


def party_out(p: Party) -> dict:
    return {"id": p.id, **{f: getattr(p, f) for f in PARTY_FIELDS}, "kind": p.kind.value}


async def validate_vehicle_refs(db: AsyncSession, body: VehicleIn) -> None:
    """Depot and party must exist in this business, and the party kind must fit the ownership type."""
    if body.depot_id is not None and await db.get(Depot, body.depot_id) is None:
        raise error(status.HTTP_404_NOT_FOUND, "depot_not_found", "That depot was not found.")
    needed = PARTY_FOR_OWNERSHIP[body.ownership_type]
    if needed is None:
        return
    if body.party_id is None:
        raise error(422, "party_required", f"Choose the {needed.value} for this vehicle.")
    party = await db.get(Party, body.party_id)
    if party is None:
        raise error(status.HTTP_404_NOT_FOUND, "party_not_found", "That lessor or lender was not found.")
    if party.kind != needed:
        raise error(422, "party_kind_mismatch", f"This ownership type needs a {needed.value}.")


async def get_vehicle(db: AsyncSession, principal: Principal, vehicle_id: uuid.UUID) -> Vehicle:
    require_vehicle_in_scope(principal, vehicle_id)
    v = (await db.execute(select(Vehicle).where(Vehicle.id == vehicle_id))).scalar_one_or_none()
    if v is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That vehicle was not found.")
    return v


def duplicate_registration() -> Exception:
    return error(status.HTTP_409_CONFLICT, "duplicate_registration", "A vehicle with that registration already exists.")


# ---- Vehicles ------------------------------------------------------------------------------------


@router.get("/vehicles")
async def list_vehicles(principal: Principal = Depends(require("vehicles.view")), db: AsyncSession = Depends(get_db)):
    query = scope_vehicles(select(Vehicle).order_by(Vehicle.registration), principal)
    vehicles = (await db.execute(query)).scalars().all()
    flags = await flag_summary(db, [v.id for v in vehicles])
    return [vehicle_out(v) | {"trust_level": trust_out(v, flags.get(v.id, {}))["level"]} for v in vehicles]


@router.post("/vehicles", status_code=status.HTTP_201_CREATED)
async def create_vehicle(
    body: VehicleIn, principal: Principal = Depends(require("vehicles.manage")), db: AsyncSession = Depends(get_db)
):
    await validate_vehicle_refs(db, body)
    vehicle = Vehicle(**{**body.model_dump(), "registration": normalize_registration(body.registration)})
    db.add(vehicle)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise duplicate_registration() from None
    audit.record(
        db, actor_user_id=principal.user.id, action="vehicle.created", entity_type="vehicle",
        entity_id=vehicle.id, after=audit.snapshot(vehicle, VEHICLE_FIELDS),
    )  # fmt: skip
    await db.commit()
    return vehicle_out(vehicle)


@router.get("/vehicles/{vehicle_id}")
async def read_vehicle(
    vehicle_id: uuid.UUID, principal: Principal = Depends(require("vehicles.view")), db: AsyncSession = Depends(get_db)
):
    return vehicle_out(await get_vehicle(db, principal, vehicle_id))


@router.put("/vehicles/{vehicle_id}")
async def update_vehicle(
    vehicle_id: uuid.UUID,
    body: VehicleIn,
    principal: Principal = Depends(require("vehicles.manage")),
    db: AsyncSession = Depends(get_db),
):
    vehicle = await get_vehicle(db, principal, vehicle_id)
    await validate_vehicle_refs(db, body)
    before = audit.snapshot(vehicle, VEHICLE_FIELDS)
    for field, value in {**body.model_dump(), "registration": normalize_registration(body.registration)}.items():
        setattr(vehicle, field, value)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise duplicate_registration() from None
    audit.record(
        db, actor_user_id=principal.user.id, action="vehicle.updated", entity_type="vehicle",
        entity_id=vehicle.id, before=before, after=audit.snapshot(vehicle, VEHICLE_FIELDS),
    )  # fmt: skip
    await db.commit()
    return vehicle_out(vehicle)


# ---- Lessors, lenders and lessees ----------------------------------------------------------------


@router.get("/parties")
async def list_parties(_: Principal = Depends(require("vehicles.view")), db: AsyncSession = Depends(get_db)):
    return [party_out(p) for p in (await db.execute(select(Party).order_by(Party.name))).scalars()]


@router.post("/parties", status_code=status.HTTP_201_CREATED)
async def create_party(
    body: PartyIn, principal: Principal = Depends(require("vehicles.manage")), db: AsyncSession = Depends(get_db)
):
    party = Party(**_party_values(body))
    db.add(party)
    await db.flush()
    audit.record(
        db, actor_user_id=principal.user.id, action="party.created", entity_type="party",
        entity_id=party.id, after=audit.snapshot(party, PARTY_FIELDS),
    )  # fmt: skip
    await db.commit()
    return party_out(party)


@router.put("/parties/{party_id}")
async def update_party(
    party_id: uuid.UUID,
    body: PartyIn,
    principal: Principal = Depends(require("vehicles.manage")),
    db: AsyncSession = Depends(get_db),
):
    party = (await db.execute(select(Party).where(Party.id == party_id))).scalar_one_or_none()
    if party is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That lessor or lender was not found.")
    before = audit.snapshot(party, PARTY_FIELDS)
    for field, value in _party_values(body).items():
        setattr(party, field, value)
    audit.record(
        db, actor_user_id=principal.user.id, action="party.updated", entity_type="party",
        entity_id=party.id, before=before, after=audit.snapshot(party, PARTY_FIELDS),
    )  # fmt: skip
    await db.commit()
    return party_out(party)


def _party_values(body: PartyIn) -> dict:
    phone = None
    if body.phone:
        phone = normalize_phone(body.phone)
        if phone is None:
            raise error(422, "invalid_phone", "Enter a valid Kenyan phone number.")
    return {**body.model_dump(), "name": body.name.strip(), "phone": phone}


# ---- Crew ----------------------------------------------------------------------------------------


def crew_out(c: CrewAssignment) -> dict:
    return {
        "id": c.id,
        "vehicle_id": c.vehicle_id,
        "membership_id": c.membership_id,
        "role": c.role.value,
        "started_at": c.started_at,
        "ended_at": c.ended_at,
    }


@router.get("/vehicles/{vehicle_id}/crew")
async def crew_history(
    vehicle_id: uuid.UUID, principal: Principal = Depends(require("vehicles.view")), db: AsyncSession = Depends(get_db)
):
    """Everyone who has crewed this vehicle, newest first. Open rows (no ended_at) are the current crew."""
    await get_vehicle(db, principal, vehicle_id)
    rows = (
        await db.execute(
            select(CrewAssignment)
            .where(CrewAssignment.vehicle_id == vehicle_id)
            .order_by(CrewAssignment.started_at.desc())
        )
    ).scalars()
    return [crew_out(c) for c in rows]


@router.post("/vehicles/{vehicle_id}/crew", status_code=status.HTTP_201_CREATED)
async def assign_crew(
    vehicle_id: uuid.UUID,
    body: CrewIn,
    principal: Principal = Depends(require("vehicles.manage")),
    db: AsyncSession = Depends(get_db),
):
    """Puts a person in a crew slot. Whoever held the slot, and any vehicle this person was on, is closed."""
    vehicle = await get_vehicle(db, principal, vehicle_id)
    if not vehicle.is_active:
        raise error(status.HTTP_409_CONFLICT, "vehicle_inactive", "This vehicle is not active.")
    member = (await db.execute(select(Membership).where(Membership.id == body.membership_id))).scalar_one_or_none()
    if member is None or member.status != MembershipStatus.ACTIVE:
        raise error(status.HTTP_404_NOT_FOUND, "staff_not_found", "That staff member was not found.")
    if CREW_ROLE_TO_ROLE[body.role] not in {r.role for r in member.roles}:
        raise error(422, "wrong_role", f"That person does not have the {body.role.value} role.")

    now = datetime.now(UTC)
    open_rows = (
        await db.execute(
            select(CrewAssignment).where(
                CrewAssignment.ended_at.is_(None),
                (CrewAssignment.membership_id == member.id)
                | ((CrewAssignment.vehicle_id == vehicle.id) & (CrewAssignment.role == body.role)),
            )
        )
    ).scalars().all()
    if any(c.vehicle_id == vehicle.id and c.membership_id == member.id and c.role == body.role for c in open_rows):
        raise error(status.HTTP_409_CONFLICT, "already_assigned", "That person already holds this slot.")
    for old in open_rows:
        audit.record(
            db, actor_user_id=principal.user.id, action="crew.ended", entity_type="crew_assignment",
            entity_id=old.id, before=audit.snapshot(old, CREW_FIELDS), after={"ended_at": now.isoformat()},
        )  # fmt: skip
    if open_rows:
        await db.execute(
            update(CrewAssignment)
            .where(CrewAssignment.id.in_([c.id for c in open_rows]))
            .values(ended_at=now)
        )
        await db.flush()

    assignment = CrewAssignment(vehicle_id=vehicle.id, membership_id=member.id, role=body.role, started_at=now)
    db.add(assignment)
    await db.flush()
    audit.record(
        db, actor_user_id=principal.user.id, action="crew.assigned", entity_type="crew_assignment",
        entity_id=assignment.id, after={"vehicle_id": str(vehicle.id), "membership_id": str(member.id), "role": body.role.value},
    )  # fmt: skip
    await db.commit()
    return crew_out(assignment)


@router.delete("/vehicles/{vehicle_id}/crew/{role}", status_code=status.HTTP_204_NO_CONTENT)
async def unassign_crew(
    vehicle_id: uuid.UUID,
    role: CrewRole,
    principal: Principal = Depends(require("vehicles.manage")),
    db: AsyncSession = Depends(get_db),
):
    await get_vehicle(db, principal, vehicle_id)
    current = (
        await db.execute(
            select(CrewAssignment).where(
                CrewAssignment.vehicle_id == vehicle_id,
                CrewAssignment.role == role,
                CrewAssignment.ended_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if current is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "Nobody holds that slot.")
    now = datetime.now(UTC)
    current.ended_at = now
    audit.record(
        db, actor_user_id=principal.user.id, action="crew.ended", entity_type="crew_assignment",
        entity_id=current.id, before=audit.snapshot(current, CREW_FIELDS), after={"ended_at": now.isoformat()},
    )  # fmt: skip
    await db.commit()


# ---- Driver "My vehicle" -------------------------------------------------------------------------


@router.get("/me/vehicle")
async def my_vehicle(principal: Principal = Depends(require("trips.own")), db: AsyncSession = Depends(get_db)):
    """The vehicle the signed-in driver or turnboy is currently crewing, with the rest of the crew."""
    if principal.membership_id is None:
        return None
    mine = (
        await db.execute(
            select(CrewAssignment).where(
                CrewAssignment.membership_id == principal.membership_id, CrewAssignment.ended_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if mine is None:
        return None
    vehicle = (await db.execute(select(Vehicle).where(Vehicle.id == mine.vehicle_id))).scalar_one()
    mates = (
        await db.execute(
            select(CrewAssignment).where(CrewAssignment.vehicle_id == vehicle.id, CrewAssignment.ended_at.is_(None))
        )
    ).scalars().all()
    members = {
        m.id: m
        for m in (
            await db.execute(select(Membership).where(Membership.id.in_([c.membership_id for c in mates])))
        ).scalars()
    }
    return {
        "vehicle": {
            "id": vehicle.id, "registration": vehicle.registration, "make": vehicle.make, "model": vehicle.model,
            "capacity_tonnes": vehicle.capacity_tonnes, "fuel_type": vehicle.fuel_type.value,
            "tank_litres": vehicle.tank_litres, "odometer_km": vehicle.odometer_km,
            "gvw_limit_kg": vehicle.gvw_limit_kg, "tare_kg": vehicle.tare_kg,
        },
        "my_role": mine.role.value,
        "crew": [
            {"role": c.role.value, "name": members[c.membership_id].user.name, "phone": members[c.membership_id].user.phone}
            for c in mates
        ],
    }
