import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import AuthSession, Membership, MembershipStatus, Role, SupportGrant, User
from app.permissions import SUPPORT_PERMISSIONS, permissions_for
from app.security import decode_access_token
from app.tenancy import current_business_id

bearer = HTTPBearer(auto_error=False)


def error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code, detail={"code": code, "message": message})


@dataclass
class Principal:
    user: User
    session: AuthSession
    business_id: uuid.UUID | None
    roles: set[Role] = field(default_factory=set)
    permissions: set[str] = field(default_factory=set)
    membership_id: uuid.UUID | None = None
    # None means "all vehicles"; a set restricts the principal to those vehicle ids.
    vehicle_scope: set[str] | None = None
    support: bool = False

    @property
    def mfa_verified(self) -> bool:
        return self.session.mfa_verified


def unauthenticated() -> HTTPException:
    return error(status.HTTP_401_UNAUTHORIZED, "not_authenticated", "Please sign in again.")


async def load_principal(
    credentials: HTTPAuthorizationCredentials | None, db: AsyncSession
) -> Principal:
    if credentials is None:
        raise unauthenticated()
    claims = decode_access_token(credentials.credentials)
    if claims is None:
        raise unauthenticated()
    try:
        session_id = uuid.UUID(claims["sid"])
    except ValueError:
        raise unauthenticated() from None

    # The session row is checked on every request, so revoking it takes effect immediately.
    session = await db.get(AuthSession, session_id)
    now = datetime.now(UTC)
    if session is None or session.revoked_at is not None or session.expires_at <= now:
        raise unauthenticated()
    user = await db.get(User, session.user_id)
    if user is None or not user.is_active or str(user.id) != claims["sub"]:
        raise unauthenticated()

    principal = Principal(user=user, session=session, business_id=session.business_id)
    if session.business_id is None:
        return principal

    current_business_id.set(session.business_id)

    if session.support_access:
        grant = (
            await db.execute(
                select(SupportGrant).where(
                    SupportGrant.revoked_at.is_(None), SupportGrant.expires_at > now
                )
            )
        ).first()
        if not user.is_platform_admin or grant is None:
            raise error(status.HTTP_403_FORBIDDEN, "support_access_ended", "Support access has ended.")
        principal.support = True
        principal.permissions = set(SUPPORT_PERMISSIONS)
        return principal

    membership = (
        await db.execute(
            select(Membership).where(
                Membership.user_id == user.id, Membership.status == MembershipStatus.ACTIVE
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        raise error(status.HTTP_403_FORBIDDEN, "access_revoked", "You no longer have access to this company.")

    principal.membership_id = membership.id
    principal.roles = {r.role for r in membership.roles}
    principal.permissions = permissions_for(principal.roles)
    scopes = [r.vehicle_scope for r in membership.roles if r.role == Role.SUPERVISOR]
    if scopes and Role.OWNER not in principal.roles and Role.MANAGER not in principal.roles:
        principal.vehicle_scope = {v for s in scopes for v in (s or [])}
    return principal


async def principal_unverified(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> Principal:
    """Signed in, but two-step verification may still be pending. Only for 2FA setup endpoints."""
    return await load_principal(credentials, db)


async def current_principal(principal: Principal = Depends(principal_unverified)) -> Principal:
    if not principal.mfa_verified:
        raise error(
            status.HTTP_403_FORBIDDEN,
            "mfa_setup_required",
            "Set up two-step verification to continue.",
        )
    return principal


def require(*permissions: str) -> Callable[..., Principal]:
    async def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        missing = [p for p in permissions if p not in principal.permissions]
        if missing:
            raise error(
                status.HTTP_403_FORBIDDEN,
                "forbidden",
                "You do not have permission to do this.",
            )
        return principal

    return dependency


def require_any(*permissions: str) -> Callable[..., Principal]:
    """Allows the request if the caller holds at least one of the permissions."""

    async def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        if not any(p in principal.permissions for p in permissions):
            raise error(status.HTTP_403_FORBIDDEN, "forbidden", "You do not have permission to do this.")
        return principal

    return dependency


async def platform_admin(principal: Principal = Depends(current_principal)) -> Principal:
    if not principal.user.is_platform_admin:
        raise error(status.HTTP_403_FORBIDDEN, "forbidden", "You do not have permission to do this.")
    return principal
