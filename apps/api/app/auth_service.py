import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import (
    AuthSession,
    Business,
    Document,
    Membership,
    MembershipStatus,
    OtpChallenge,
    PolicyAcceptance,
    Role,
    RoleAssignment,
    User,
)
from app.permissions import MFA_REQUIRED_ROLES, OTP_ONLY_ROLES
from app.security import (
    constant_time_equals,
    create_access_token,
    new_otp_code,
    new_secret_token,
    sha256,
)
from app.sms import get_sms_sender


def now() -> datetime:
    return datetime.now(UTC)


async def memberships_of(db: AsyncSession, user_id: uuid.UUID) -> dict[uuid.UUID, dict]:
    """Every active company a user belongs to, with roles. Deliberately crosses tenants."""
    rows = (
        await db.execute(
            select(Membership.business_id, Business.name, RoleAssignment.role)
            .join(Business, Business.id == Membership.business_id)
            .outerjoin(RoleAssignment, RoleAssignment.membership_id == Membership.id)
            .where(Membership.user_id == user_id, Membership.status == MembershipStatus.ACTIVE)
            .order_by(Membership.created_at)
            .execution_options(skip_tenant=True)
        )
    ).all()
    companies: dict[uuid.UUID, dict] = {}
    for business_id, name, role in rows:
        entry = companies.setdefault(business_id, {"business_id": business_id, "name": name, "roles": set()})
        if role is not None:
            entry["roles"].add(role)
    return companies


def has_two_factor(user: User) -> bool:
    return user.totp_enabled or user.sms_2fa_enabled


async def send_sms_challenge(db: AsyncSession, phone: str, purpose: str) -> None:
    """Texts a one-time code, unless one was sent within the resend window. The caller commits."""
    moment = now()
    recent = (
        await db.execute(
            select(OtpChallenge.id).where(
                OtpChallenge.phone == phone,
                OtpChallenge.purpose == purpose,
                OtpChallenge.created_at > moment - timedelta(seconds=settings.otp_resend_seconds),
            )
        )
    ).first()
    if recent:
        return
    code = new_otp_code()
    db.add(
        OtpChallenge(
            phone=phone,
            purpose=purpose,
            code_hash=sha256(f"{phone}:{code}"),
            expires_at=moment + timedelta(minutes=settings.otp_ttl_minutes),
        )
    )
    await db.flush()
    await get_sms_sender().send(phone, f"Your FleetTms code is {code}. It expires in {settings.otp_ttl_minutes} minutes.")


async def check_sms_challenge(db: AsyncSession, phone: str, purpose: str, code: str) -> bool:
    """True if the code matches the latest unused challenge for this purpose. The caller commits."""
    challenge = (
        await db.execute(
            select(OtpChallenge)
            .where(OtpChallenge.phone == phone, OtpChallenge.purpose == purpose, OtpChallenge.consumed_at.is_(None))
            .order_by(OtpChallenge.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if challenge is None or challenge.expires_at <= now() or challenge.attempts >= settings.otp_max_attempts:
        return False
    challenge.attempts += 1
    if not constant_time_equals(challenge.code_hash, sha256(f"{phone}:{code}")):
        return False
    challenge.consumed_at = now()
    return True


def requires_mfa(user: User, roles: set[Role]) -> bool:
    return user.is_platform_admin or bool(roles & MFA_REQUIRED_ROLES)


def is_otp_only(companies: dict[uuid.UUID, dict]) -> bool:
    """True when a user may sign in with a phone code: every role they hold is driver/turnboy."""
    all_roles = {r for c in companies.values() for r in c["roles"]}
    return bool(all_roles) and all_roles <= OTP_ONLY_ROLES


def session_lifetime(roles: set[Role]) -> timedelta:
    if roles and roles <= OTP_ONLY_ROLES:
        return timedelta(days=settings.driver_session_days)
    return timedelta(hours=settings.staff_session_hours)


def split_refresh_token(token: str) -> tuple[uuid.UUID, str] | None:
    sid, _, secret = token.partition(".")
    try:
        return uuid.UUID(sid), secret
    except ValueError:
        return None


async def issue_session(
    db: AsyncSession,
    user: User,
    business_id: uuid.UUID | None,
    roles: set[Role],
    *,
    mfa_verified: bool,
    device_label: str | None = None,
) -> dict:
    secret = new_secret_token()
    session = AuthSession(
        user_id=user.id,
        business_id=business_id,
        refresh_hash=sha256(secret),
        device_label=(device_label or None) and device_label[:120],
        mfa_verified=mfa_verified,
        expires_at=now() + session_lifetime(roles),
    )
    db.add(session)
    await db.flush()
    return {
        "access_token": create_access_token(user.id, session.id),
        "refresh_token": f"{session.id}.{secret}",
        "token_type": "bearer",
        "mfa_setup_required": not mfa_verified,
        "business_id": business_id,
    }


def required_documents(roles: set[Role]) -> dict[Document, str]:
    docs = {Document.TERMS: settings.terms_version, Document.PRIVACY: settings.privacy_version}
    if Role.OWNER in roles:
        docs[Document.DPA] = settings.dpa_version
    if roles & OTP_ONLY_ROLES:
        docs[Document.MONITORING_NOTICE] = settings.monitoring_notice_version
    return docs


async def pending_documents(db: AsyncSession, user_id: uuid.UUID, roles: set[Role]) -> list[dict]:
    """Documents this user still has to accept in the current company (tenant context required)."""
    accepted = {
        (a.document, a.version)
        for a in (
            await db.execute(select(PolicyAcceptance).where(PolicyAcceptance.user_id == user_id))
        ).scalars()
    }
    return [
        {"document": doc.value, "version": version}
        for doc, version in required_documents(roles).items()
        if (doc, version) not in accepted
    ]
