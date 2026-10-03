import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, subscriptions
from app.auth_service import now
from app.config import settings
from app.db import get_db
from app.deps import Principal, error, require
from app.models import (
    AuthSession,
    Depot,
    Membership,
    MembershipStatus,
    Party,
    PartyKind,
    Role,
    RoleAssignment,
    User,
)
from app.permissions import OTP_ONLY_ROLES
from app.phone import normalize_phone
from app.security import new_secret_token, sha256
from app.tenancy import current_business_id

router = APIRouter(prefix="/users", tags=["users"])


class InviteIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    email: EmailStr | None = None
    phone: str | None = None
    roles: list[Role] = Field(min_length=1)
    depot_id: uuid.UUID | None = None
    vehicle_scope: list[str] | None = None
    party_id: uuid.UUID | None = None  # for a lessor: whose leases they see


class RolesIn(BaseModel):
    roles: list[Role] = Field(min_length=1)
    vehicle_scope: list[str] | None = None


def _out(m: Membership) -> dict:
    return {
        "membership_id": m.id,
        "user_id": m.user_id,
        "name": m.user.name,
        "email": m.user.email,
        "phone": m.user.phone,
        "roles": sorted(r.role.value for r in m.roles),
        "vehicle_scope": next((r.vehicle_scope for r in m.roles if r.role == Role.SUPERVISOR), None),
        "depot_id": m.depot_id,
        "party_id": m.party_id,
        "status": m.status.value,
        "two_factor_enabled": m.user.totp_enabled or m.user.sms_2fa_enabled,
    }


async def _get_membership(db: AsyncSession, membership_id: uuid.UUID) -> Membership:
    m = (await db.execute(select(Membership).where(Membership.id == membership_id))).scalar_one_or_none()
    if m is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That user was not found.")
    return m


async def _other_active_owners(db: AsyncSession, membership_id: uuid.UUID) -> int:
    rows = (
        await db.execute(
            select(Membership.id)
            .join(RoleAssignment, RoleAssignment.membership_id == Membership.id)
            .where(
                RoleAssignment.role == Role.OWNER,
                Membership.status == MembershipStatus.ACTIVE,
                Membership.id != membership_id,
            )
        )
    ).all()
    return len(rows)


@router.get("")
async def list_users(_: Principal = Depends(require("users.view")), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Membership).order_by(Membership.created_at))).scalars().all()
    return [_out(m) for m in rows]


async def _roles_allowed_by_plan(db: AsyncSession, roles: set[Role]) -> None:
    """Starter has two roles, owner and driver; the rest (manager, supervisor, accountant, workshop) come with Standard."""
    if roles - {Role.OWNER, Role.DRIVER, Role.TURNBOY, Role.LESSOR} and current_business_id.get() is not None:
        await subscriptions.require_feature(db, current_business_id.get(), "all_roles")


async def invite_member(
    db: AsyncSession,
    actor: Principal,
    *,
    name: str,
    email: str | None,
    phone: str | None,
    roles: set[Role],
    depot_id: uuid.UUID | None = None,
    vehicle_scope: list[str] | None = None,
    party_id: uuid.UUID | None = None,
) -> tuple[Membership, str | None]:
    """Adds a person to the current business and audits it. The caller commits. Returns (membership, invite token)."""
    await _roles_allowed_by_plan(db, roles)
    if Role.LESSOR in roles:
        if roles != {Role.LESSOR}:
            raise error(422, "lessor_only", "A lessor's login is only for viewing their own leases, so it cannot have other roles.")
        party = (await db.get(Party, party_id)) if party_id else None
        if party is None or party.kind != PartyKind.LESSOR:
            raise error(422, "party_required", "Choose which lessor this login is for.")
    elif party_id is not None:
        raise error(422, "party_not_allowed", "Only a lessor's login is tied to a lessor.")
    otp_only = roles <= OTP_ONLY_ROLES
    if phone:
        phone = normalize_phone(phone)
        if phone is None:
            raise error(422, "invalid_phone", "Enter a valid Kenyan phone number.")
    if otp_only and phone is None:
        raise error(422, "phone_required", "Drivers and turnboys sign in with a phone number.")
    if not otp_only and email is None:
        raise error(422, "email_required", "This role signs in with an email address.")
    if depot_id is not None and await db.get(Depot, depot_id) is None:
        raise error(status.HTTP_404_NOT_FOUND, "depot_not_found", "That depot was not found.")

    email = email.lower() if email else None
    user = None
    if email or phone:
        candidates = []
        if email:
            candidates.append(User.email == email)
        if phone:
            candidates.append(User.phone == phone)
        found = (await db.execute(select(User).where(or_(*candidates)))).scalars().all()
        if len(found) > 1:
            raise error(status.HTTP_409_CONFLICT, "ambiguous_user", "That email and phone belong to different accounts.")
        user = found[0] if found else None

    invite_token = None
    if user is None:
        user = User(name=name.strip(), email=email, phone=phone)
        if not otp_only:
            invite_token = new_secret_token()
            user.invite_token_hash = sha256(invite_token)
            user.invite_expires_at = now() + timedelta(hours=settings.invite_ttl_hours)
        db.add(user)
        await db.flush()
    else:
        existing = (await db.execute(select(Membership).where(Membership.user_id == user.id))).scalar_one_or_none()
        if existing is not None and existing.status == MembershipStatus.ACTIVE:
            raise error(status.HTTP_409_CONFLICT, "already_member", "This person is already in your company.")
        if existing is not None:
            await db.delete(existing)  # re-inviting someone whose access was revoked
            await db.flush()

    membership = Membership(user_id=user.id, depot_id=depot_id, party_id=party_id)
    db.add(membership)
    await db.flush()
    for role in roles:
        scope = vehicle_scope if role == Role.SUPERVISOR else None
        db.add(RoleAssignment(membership_id=membership.id, role=role, vehicle_scope=scope))
    audit.record(
        db,
        actor_user_id=actor.user.id,
        action="user.invited",
        entity_type="membership",
        entity_id=membership.id,
        after={"user_id": str(user.id), "roles": sorted(r.value for r in roles)},
    )
    return membership, invite_token


@router.post("", status_code=status.HTTP_201_CREATED)
async def invite_user(
    body: InviteIn,
    principal: Principal = Depends(require("users.manage")),
    db: AsyncSession = Depends(get_db),
):
    membership, invite_token = await invite_member(
        db,
        principal,
        name=body.name,
        email=body.email,
        phone=body.phone,
        roles=set(body.roles),
        depot_id=body.depot_id,
        vehicle_scope=body.vehicle_scope,
        party_id=body.party_id,
    )
    await db.commit()
    membership = await _get_membership(db, membership.id)
    return {**_out(membership), "invite_token": invite_token}


@router.put("/{membership_id}/roles")
async def set_roles(
    membership_id: uuid.UUID,
    body: RolesIn,
    principal: Principal = Depends(require("users.manage")),
    db: AsyncSession = Depends(get_db),
):
    m = await _get_membership(db, membership_id)
    new_roles = set(body.roles)
    await _roles_allowed_by_plan(db, new_roles)
    if (Role.LESSOR in new_roles) != (m.party_id is not None):
        raise error(422, "lessor_login", "A lessor's login is made by inviting them as a lessor. It cannot be turned on or off here.")
    before = {"roles": sorted(r.role.value for r in m.roles)}
    losing_owner = Role.OWNER not in new_roles and any(r.role == Role.OWNER for r in m.roles)
    if losing_owner and await _other_active_owners(db, m.id) == 0:
        raise error(status.HTTP_409_CONFLICT, "last_owner", "A company must keep at least one owner.")

    m.roles.clear()
    await db.flush()
    for role in new_roles:
        scope = body.vehicle_scope if role == Role.SUPERVISOR else None
        m.roles.append(RoleAssignment(role=role, vehicle_scope=scope))
    audit.record(
        db,
        actor_user_id=principal.user.id,
        action="user.roles_changed",
        entity_type="membership",
        entity_id=m.id,
        before=before,
        after={"roles": sorted(r.value for r in new_roles), "vehicle_scope": body.vehicle_scope},
    )
    await db.commit()
    return _out(await _get_membership(db, m.id))


@router.delete("/{membership_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_user(
    membership_id: uuid.UUID,
    principal: Principal = Depends(require("users.manage")),
    db: AsyncSession = Depends(get_db),
):
    m = await _get_membership(db, membership_id)
    if any(r.role == Role.OWNER for r in m.roles) and await _other_active_owners(db, m.id) == 0:
        raise error(status.HTTP_409_CONFLICT, "last_owner", "A company must keep at least one owner.")
    m.status = MembershipStatus.REVOKED
    # Sessions stay valid for other companies; this one is cut off at once because every request
    # re-checks the membership.
    await db.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id == m.user_id,
            AuthSession.business_id == principal.business_id,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=now())
    )
    audit.record(
        db,
        actor_user_id=principal.user.id,
        action="user.removed",
        entity_type="membership",
        entity_id=m.id,
        before={"roles": sorted(r.role.value for r in m.roles), "status": "active"},
        after={"status": "revoked"},
    )
    await db.commit()
