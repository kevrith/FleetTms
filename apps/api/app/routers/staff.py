import uuid

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.db import get_db
from app.deps import Principal, error, require
from app.models import CrewAssignment, Membership, MembershipStatus, StaffProfile
from app.phone import normalize_phone

router = APIRouter(prefix="/staff", tags=["staff"])
PROFILE_FIELDS = [
    "licence_number", "licence_class", "emergency_contact_name", "emergency_contact_phone",
]  # fmt: skip


class ProfileIn(BaseModel):
    licence_number: str | None = Field(default=None, max_length=40)
    licence_class: str | None = Field(default=None, max_length=20)
    emergency_contact_name: str | None = Field(default=None, max_length=200)
    emergency_contact_phone: str | None = None
    # Only people with payroll access may set or see this; managers and supervisors cannot.
    monthly_salary_cents: int | None = Field(default=None, ge=0, le=100_000_000_00)


def _out(m: Membership, profile: StaffProfile | None, crew: CrewAssignment | None, principal: Principal) -> dict:
    out = {
        "membership_id": m.id,
        "name": m.user.name,
        "phone": m.user.phone,
        "email": m.user.email,
        "roles": sorted(r.role.value for r in m.roles),
        "status": m.status.value,
        "depot_id": m.depot_id,
        "licence_number": profile.licence_number if profile else None,
        "licence_class": profile.licence_class if profile else None,
        "emergency_contact_name": profile.emergency_contact_name if profile else None,
        "emergency_contact_phone": profile.emergency_contact_phone if profile else None,
        "vehicle_id": crew.vehicle_id if crew else None,
        "crew_role": crew.role.value if crew else None,
    }
    if "payroll.view" in principal.permissions:
        out["monthly_salary_cents"] = profile.monthly_salary_cents if profile else None
    return out


async def _profiles_and_crews(db: AsyncSession) -> tuple[dict, dict]:
    profiles = {p.membership_id: p for p in (await db.execute(select(StaffProfile))).scalars()}
    crews = {
        c.membership_id: c
        for c in (await db.execute(select(CrewAssignment).where(CrewAssignment.ended_at.is_(None)))).scalars()
    }
    return profiles, crews


async def _get_member(db: AsyncSession, membership_id: uuid.UUID) -> Membership:
    m = (await db.execute(select(Membership).where(Membership.id == membership_id))).scalar_one_or_none()
    if m is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That staff member was not found.")
    return m


@router.get("")
async def list_staff(principal: Principal = Depends(require("staff.view")), db: AsyncSession = Depends(get_db)):
    members = (
        await db.execute(
            select(Membership).where(Membership.status == MembershipStatus.ACTIVE).order_by(Membership.created_at)
        )
    ).scalars().all()
    profiles, crews = await _profiles_and_crews(db)
    return [_out(m, profiles.get(m.id), crews.get(m.id), principal) for m in members]


@router.get("/{membership_id}")
async def read_staff(
    membership_id: uuid.UUID, principal: Principal = Depends(require("staff.view")), db: AsyncSession = Depends(get_db)
):
    m = await _get_member(db, membership_id)
    profiles, crews = await _profiles_and_crews(db)
    return _out(m, profiles.get(m.id), crews.get(m.id), principal)


@router.put("/{membership_id}/profile")
async def update_profile(
    membership_id: uuid.UUID,
    body: ProfileIn,
    principal: Principal = Depends(require("staff.manage")),
    db: AsyncSession = Depends(get_db),
):
    m = await _get_member(db, membership_id)
    can_see_pay = "payroll.view" in principal.permissions
    if body.monthly_salary_cents is not None and not can_see_pay:
        raise error(status.HTTP_403_FORBIDDEN, "forbidden", "You do not have permission to set salaries.")
    contact = None
    if body.emergency_contact_phone:
        contact = normalize_phone(body.emergency_contact_phone)
        if contact is None:
            raise error(422, "invalid_phone", "Enter a valid Kenyan phone number.")

    profile = (
        await db.execute(select(StaffProfile).where(StaffProfile.membership_id == m.id))
    ).scalar_one_or_none()
    before = audit.snapshot(profile, PROFILE_FIELDS) if profile else None
    if profile is None:
        profile = StaffProfile(membership_id=m.id)
        db.add(profile)
    profile.licence_number = body.licence_number
    profile.licence_class = body.licence_class
    profile.emergency_contact_name = body.emergency_contact_name
    profile.emergency_contact_phone = contact
    after = audit.snapshot(profile, PROFILE_FIELDS)
    if can_see_pay:
        # Salary is only touched by people allowed to see it; others leave it as it was.
        old_salary = profile.monthly_salary_cents
        profile.monthly_salary_cents = body.monthly_salary_cents
        if old_salary != body.monthly_salary_cents:
            if before is not None:
                before["monthly_salary_cents"] = old_salary
            after["monthly_salary_cents"] = body.monthly_salary_cents
    audit.record(
        db, actor_user_id=principal.user.id, action="staff.profile_updated", entity_type="membership",
        entity_id=m.id, before=before, after=after,
    )  # fmt: skip
    await db.commit()
    _, crews = await _profiles_and_crews(db)
    return _out(m, profile, crews.get(m.id), principal)
