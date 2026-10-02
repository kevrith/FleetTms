import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.auth_service import (
    is_otp_only,
    issue_session,
    memberships_of,
    now,
    pending_documents,
    requires_mfa,
    session_lifetime,
    split_refresh_token,
)
from app.config import settings
from app.db import get_db
from app.deps import Principal, current_principal, error, principal_unverified
from app.models import (
    AuthSession,
    Business,
    Document,
    Membership,
    OtpChallenge,
    PolicyAcceptance,
    Role,
    RoleAssignment,
    User,
)
from app.permissions import permissions_for
from app.phone import normalize_phone
from app.security import (
    constant_time_equals,
    create_access_token,
    hash_password,
    new_otp_code,
    new_secret_token,
    new_totp_secret,
    sha256,
    totp_uri,
    verify_password,
    verify_totp,
)
from app.sms import get_sms_sender
from app.tenancy import current_business_id

router = APIRouter(prefix="/auth", tags=["auth"])

INVALID_LOGIN = "Incorrect email, phone or password."


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    mfa_setup_required: bool
    business_id: uuid.UUID | None


class SignupIn(BaseModel):
    business_name: str = Field(min_length=2, max_length=200)
    name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    phone: str | None = None
    password: str = Field(min_length=10, max_length=200)
    accept_terms: bool
    accept_privacy: bool
    accept_dpa: bool


class LoginIn(BaseModel):
    identifier: str
    password: str
    totp_code: str | None = None
    business_id: uuid.UUID | None = None
    device_label: str | None = None


class OtpRequestIn(BaseModel):
    phone: str


class OtpVerifyIn(BaseModel):
    phone: str
    code: str = Field(min_length=6, max_length=6)
    business_id: uuid.UUID | None = None
    device_label: str | None = None


class RefreshIn(BaseModel):
    refresh_token: str


class SwitchIn(BaseModel):
    business_id: uuid.UUID


class TotpCodeIn(BaseModel):
    code: str


class AcceptInviteIn(BaseModel):
    token: str
    password: str = Field(min_length=10, max_length=200)


def _bad_phone():
    return error(422, "invalid_phone", "Enter a valid Kenyan phone number.")


def _roles_for(companies: dict, business_id: uuid.UUID | None) -> set[Role]:
    return companies[business_id]["roles"] if business_id in companies else set()


def _choose_business(companies: dict, wanted: uuid.UUID | None) -> uuid.UUID | None:
    if wanted is not None:
        if wanted not in companies:
            raise error(status.HTTP_403_FORBIDDEN, "no_access", "You do not have access to that company.")
        return wanted
    return next(iter(companies), None)


# ---- sign up -----------------------------------------------------------------------------------


@router.post("/signup", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
async def signup(body: SignupIn, db: AsyncSession = Depends(get_db)):
    if not (body.accept_terms and body.accept_privacy and body.accept_dpa):
        raise error(
            422,
            "terms_not_accepted",
            "You must accept the Terms, Privacy Policy and Data Processing Agreement.",
        )
    phone = None
    if body.phone:
        phone = normalize_phone(body.phone)
        if phone is None:
            raise _bad_phone()
    email = body.email.lower()
    clash = await db.execute(
        select(User.id).where(or_(User.email == email, User.phone == phone) if phone else User.email == email)
    )
    if clash.first():
        raise error(
            status.HTTP_409_CONFLICT,
            "account_exists",
            "An account with these details already exists. Sign in instead.",
        )

    business = Business(name=body.business_name.strip())
    user = User(name=body.name.strip(), email=email, phone=phone, password_hash=hash_password(body.password))
    db.add_all([business, user])
    await db.flush()

    current_business_id.set(business.id)
    membership = Membership(user_id=user.id)
    db.add(membership)
    await db.flush()
    db.add(RoleAssignment(membership_id=membership.id, role=Role.OWNER))
    for doc, version in (
        (Document.TERMS, settings.terms_version),
        (Document.PRIVACY, settings.privacy_version),
        (Document.DPA, settings.dpa_version),
    ):
        db.add(PolicyAcceptance(user_id=user.id, document=doc, version=version))
    audit.record(
        db,
        actor_user_id=user.id,
        action="business.created",
        entity_type="business",
        entity_id=business.id,
        after={"name": business.name},
    )
    tokens = await issue_session(db, user, business.id, {Role.OWNER}, mfa_verified=False)
    await db.commit()
    return tokens


# ---- password login + two-step verification ----------------------------------------------------


async def _find_user(db: AsyncSession, identifier: str) -> User | None:
    ident = identifier.strip()
    if "@" in ident:
        stmt = select(User).where(User.email == ident.lower())
    else:
        phone = normalize_phone(ident)
        if phone is None:
            return None
        stmt = select(User).where(User.phone == phone)
    return (await db.execute(stmt)).scalar_one_or_none()


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, db: AsyncSession = Depends(get_db)):
    user = await _find_user(db, body.identifier)
    moment = now()
    if user and user.locked_until and user.locked_until > moment:
        raise error(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "account_locked",
            "Too many failed attempts. Try again in a few minutes.",
        )

    password_ok = verify_password(body.password, user.password_hash if user else None)
    two_factor_ok = True
    if user and password_ok and user.totp_enabled:
        if not body.totp_code:
            raise error(
                status.HTTP_401_UNAUTHORIZED,
                "two_factor_required",
                "Enter the 6-digit code from your authenticator app.",
            )
        two_factor_ok = verify_totp(user.totp_secret, body.totp_code)

    if user is None or not password_ok or not two_factor_ok or not user.is_active:
        if user is not None:
            user.failed_attempts += 1
            if user.failed_attempts >= settings.max_failed_logins:
                user.locked_until = moment + timedelta(minutes=settings.lockout_minutes)
                user.failed_attempts = 0
            await db.commit()
        raise error(status.HTTP_401_UNAUTHORIZED, "invalid_credentials", INVALID_LOGIN)

    user.failed_attempts = 0
    user.locked_until = None
    companies = await memberships_of(db, user.id)
    if not companies and not user.is_platform_admin:
        raise error(status.HTTP_403_FORBIDDEN, "no_access", "Your access to this company has been removed.")
    business_id = _choose_business(companies, body.business_id)
    roles = _roles_for(companies, business_id)
    verified = user.totp_enabled or not requires_mfa(user, roles)
    tokens = await issue_session(db, user, business_id, roles, mfa_verified=verified, device_label=body.device_label)
    if business_id is not None:
        current_business_id.set(business_id)
        audit.record(db, actor_user_id=user.id, action="auth.login", entity_type="user", entity_id=user.id)
    await db.commit()
    return tokens


@router.post("/2fa/setup")
async def two_factor_setup(
    principal: Principal = Depends(principal_unverified), db: AsyncSession = Depends(get_db)
):
    user = principal.user
    if user.totp_enabled:
        raise error(status.HTTP_409_CONFLICT, "already_enabled", "Two-step verification is already on.")
    user.totp_secret = new_totp_secret()
    await db.commit()
    return {"secret": user.totp_secret, "otpauth_uri": totp_uri(user.totp_secret, user.email or user.phone or "user")}


@router.post("/2fa/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def two_factor_confirm(
    body: TotpCodeIn,
    principal: Principal = Depends(principal_unverified),
    db: AsyncSession = Depends(get_db),
):
    user = principal.user
    if user.totp_enabled or not verify_totp(user.totp_secret, body.code):
        raise error(status.HTTP_401_UNAUTHORIZED, "invalid_code", "That code is not correct. Try again.")
    user.totp_enabled = True
    principal.session.mfa_verified = True
    if principal.business_id is not None:
        audit.record(db, actor_user_id=user.id, action="auth.2fa_enabled", entity_type="user", entity_id=user.id)
    await db.commit()


# ---- driver login: phone + one-time code -------------------------------------------------------


@router.post("/otp/request")
async def otp_request(body: OtpRequestIn, db: AsyncSession = Depends(get_db)):
    phone = normalize_phone(body.phone)
    if phone is None:
        raise _bad_phone()
    reply = {"message": "If this number is registered, a code has been sent."}

    user = (await db.execute(select(User).where(User.phone == phone))).scalar_one_or_none()
    if user is None or not user.is_active or not is_otp_only(await memberships_of(db, user.id)):
        return reply  # same answer either way, so numbers cannot be probed

    moment = now()
    recent = (
        await db.execute(
            select(OtpChallenge.id).where(
                OtpChallenge.phone == phone,
                OtpChallenge.created_at > moment - timedelta(seconds=settings.otp_resend_seconds),
            )
        )
    ).first()
    if recent:
        return reply

    code = new_otp_code()
    db.add(
        OtpChallenge(
            phone=phone,
            code_hash=sha256(f"{phone}:{code}"),
            expires_at=moment + timedelta(minutes=settings.otp_ttl_minutes),
        )
    )
    await db.commit()
    await get_sms_sender().send(phone, f"Your FleetTms code is {code}. It expires in {settings.otp_ttl_minutes} minutes.")
    return reply


@router.post("/otp/verify", response_model=TokenOut)
async def otp_verify(body: OtpVerifyIn, db: AsyncSession = Depends(get_db)):
    phone = normalize_phone(body.phone)
    if phone is None:
        raise _bad_phone()
    invalid = error(status.HTTP_401_UNAUTHORIZED, "invalid_code", "That code is wrong or has expired.")

    challenge = (
        await db.execute(
            select(OtpChallenge)
            .where(OtpChallenge.phone == phone, OtpChallenge.consumed_at.is_(None))
            .order_by(OtpChallenge.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if challenge is None or challenge.expires_at <= now() or challenge.attempts >= settings.otp_max_attempts:
        raise invalid
    challenge.attempts += 1
    if not constant_time_equals(challenge.code_hash, sha256(f"{phone}:{body.code}")):
        await db.commit()
        raise invalid
    challenge.consumed_at = now()

    user = (await db.execute(select(User).where(User.phone == phone))).scalar_one_or_none()
    companies = await memberships_of(db, user.id) if user else {}
    if user is None or not user.is_active or not is_otp_only(companies):
        await db.commit()
        raise invalid
    business_id = _choose_business(companies, body.business_id)
    roles = _roles_for(companies, business_id)
    tokens = await issue_session(db, user, business_id, roles, mfa_verified=True, device_label=body.device_label)
    current_business_id.set(business_id)
    audit.record(db, actor_user_id=user.id, action="auth.login", entity_type="user", entity_id=user.id)
    await db.commit()
    return tokens


# ---- sessions ----------------------------------------------------------------------------------


@router.post("/refresh", response_model=TokenOut)
async def refresh(body: RefreshIn, db: AsyncSession = Depends(get_db)):
    expired = error(status.HTTP_401_UNAUTHORIZED, "not_authenticated", "Please sign in again.")
    parts = split_refresh_token(body.refresh_token)
    if parts is None:
        raise expired
    session = await db.get(AuthSession, parts[0])
    if session is None or session.revoked_at is not None or session.expires_at <= now():
        raise expired
    presented = sha256(parts[1])
    if session.previous_refresh_hash and constant_time_equals(session.previous_refresh_hash, presented):
        # An old token was replayed: assume it was stolen and end the session.
        session.revoked_at = now()
        await db.commit()
        raise expired
    if not constant_time_equals(session.refresh_hash, presented):
        raise expired
    user = await db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise expired

    companies = await memberships_of(db, user.id)
    roles = _roles_for(companies, session.business_id)
    secret = new_secret_token()
    session.previous_refresh_hash = session.refresh_hash
    session.refresh_hash = sha256(secret)
    session.expires_at = now() + session_lifetime(roles)
    await db.commit()
    return {
        "access_token": create_access_token(user.id, session.id),
        "refresh_token": f"{session.id}.{secret}",
        "token_type": "bearer",
        "mfa_setup_required": not session.mfa_verified,
        "business_id": session.business_id,
    }


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(principal: Principal = Depends(principal_unverified), db: AsyncSession = Depends(get_db)):
    principal.session.revoked_at = now()
    await db.commit()


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(principal: Principal = Depends(principal_unverified), db: AsyncSession = Depends(get_db)):
    await db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == principal.user.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now())
    )
    if principal.business_id is not None:
        audit.record(
            db, actor_user_id=principal.user.id, action="auth.logout_all", entity_type="user", entity_id=principal.user.id
        )
    await db.commit()


@router.post("/switch-company")
async def switch_company(
    body: SwitchIn, principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)
):
    companies = await memberships_of(db, principal.user.id)
    if body.business_id not in companies:
        raise error(status.HTTP_403_FORBIDDEN, "no_access", "You do not have access to that company.")
    roles = companies[body.business_id]["roles"]
    session = principal.session
    session.business_id = body.business_id
    session.support_access = False
    session.mfa_verified = principal.user.totp_enabled or not requires_mfa(principal.user, roles)
    await db.commit()
    return {"business_id": body.business_id, "mfa_setup_required": not session.mfa_verified}


@router.get("/me")
async def me(principal: Principal = Depends(principal_unverified), db: AsyncSession = Depends(get_db)):
    user = principal.user
    companies = await memberships_of(db, user.id)
    pending = []
    business_name = None
    if principal.business_id is not None:
        business = await db.get(Business, principal.business_id)
        business_name = business.name if business else None
        if principal.roles:
            pending = await pending_documents(db, user.id, principal.roles)
    return {
        "user": {"id": user.id, "name": user.name, "email": user.email, "phone": user.phone},
        "business": {"id": principal.business_id, "name": business_name} if principal.business_id else None,
        "roles": sorted(r.value for r in principal.roles),
        "permissions": sorted(principal.permissions or permissions_for(principal.roles)),
        "companies": [
            {"business_id": c["business_id"], "name": c["name"], "roles": sorted(r.value for r in c["roles"])}
            for c in companies.values()
        ],
        "is_platform_admin": user.is_platform_admin,
        "support_access": principal.support,
        "mfa_setup_required": not principal.mfa_verified,
        "two_factor_enabled": user.totp_enabled,
        "pending_documents": pending,
    }


@router.post("/accept-invite", status_code=status.HTTP_204_NO_CONTENT)
async def accept_invite(body: AcceptInviteIn, db: AsyncSession = Depends(get_db)):
    user = (
        await db.execute(select(User).where(User.invite_token_hash == sha256(body.token)))
    ).scalar_one_or_none()
    if user is None or user.invite_expires_at is None or user.invite_expires_at <= now():
        raise error(status.HTTP_400_BAD_REQUEST, "invalid_invite", "This invitation is invalid or has expired.")
    user.password_hash = hash_password(body.password)
    user.invite_token_hash = None
    user.invite_expires_at = None
    await db.commit()
