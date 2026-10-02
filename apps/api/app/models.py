import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.tenancy import TenantMixin


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> uuid.UUID:
    return uuid.uuid4()


class Base(DeclarativeBase):
    pass


class Role(enum.StrEnum):
    OWNER = "owner"
    MANAGER = "manager"
    SUPERVISOR = "supervisor"
    ACCOUNTANT = "accountant"
    DRIVER = "driver"
    TURNBOY = "turnboy"
    WORKSHOP = "workshop"
    LESSOR = "lessor"  # placeholder, built out in Sprint 10


class MembershipStatus(enum.StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class Document(enum.StrEnum):
    TERMS = "terms"
    PRIVACY = "privacy"
    DPA = "dpa"
    MONITORING_NOTICE = "monitoring_notice"


def _enum(e: type[enum.Enum]) -> Enum:
    return Enum(e, native_enum=False, length=30, values_callable=lambda x: [m.value for m in x])


# ---- Global (not tenant-scoped) -------------------------------------------------------------


class Business(Base):
    __tablename__ = "businesses"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    kra_pin: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320), unique=True)
    phone: Mapped[str | None] = mapped_column(String(20), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    totp_secret: Mapped[str | None] = mapped_column(String(64))
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invite_token_hash: Mapped[str | None] = mapped_column(String(64))
    invite_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuthSession(Base):
    __tablename__ = "sessions"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    business_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"))
    refresh_hash: Mapped[str] = mapped_column(String(64))
    previous_refresh_hash: Mapped[str | None] = mapped_column(String(64))
    device_label: Mapped[str | None] = mapped_column(String(120))
    mfa_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    support_access: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OtpChallenge(Base):
    __tablename__ = "otp_challenges"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    phone: Mapped[str] = mapped_column(String(20), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---- Tenant-scoped ---------------------------------------------------------------------------


class Depot(TenantMixin, Base):
    __tablename__ = "depots"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    location: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Membership(TenantMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("business_id", "user_id"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    depot_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("depots.id", ondelete="SET NULL"))
    status: Mapped[MembershipStatus] = mapped_column(
        _enum(MembershipStatus), default=MembershipStatus.ACTIVE
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(lazy="joined")
    roles: Mapped[list["RoleAssignment"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan"
    )


class RoleAssignment(TenantMixin, Base):
    __tablename__ = "role_assignments"
    __table_args__ = (UniqueConstraint("membership_id", "role"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    membership_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("memberships.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[Role] = mapped_column(_enum(Role))
    # Supervisors see assigned vehicles only. Vehicle ids; the vehicles table arrives in Sprint 2.
    vehicle_scope: Mapped[list[str] | None] = mapped_column(JSONB)


class AuditLog(TenantMixin, Base):
    __tablename__ = "audit_logs"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class PolicyAcceptance(TenantMixin, Base):
    __tablename__ = "policy_acceptances"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    document: Mapped[Document] = mapped_column(_enum(Document))
    version: Mapped[str] = mapped_column(String(40))
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SupportGrant(TenantMixin, Base):
    """Tenant owner grants Kastra support time-limited, read-only access (masterplan Section 3)."""

    __tablename__ = "support_grants"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    granted_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    reason: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
