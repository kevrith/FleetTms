import enum
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
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


class FuelType(enum.StrEnum):
    DIESEL = "diesel"
    PETROL = "petrol"


class TrackingTier(enum.StrEnum):
    BASIC = "basic"  # driver phone GPS + odometer photos
    STANDARD = "standard"  # hardware GPS tracker
    PREMIUM = "premium"  # tracker + fuel level sensor


class OwnershipType(enum.StrEnum):
    OWNED = "owned"
    ASSET_FINANCED = "asset_financed"
    LEASED_IN = "leased_in"
    LEASED_OUT = "leased_out"


class PartyKind(enum.StrEnum):
    LESSOR = "lessor"  # owns a lorry we hire in
    LENDER = "lender"  # bank or asset finance company
    LESSEE = "lessee"  # hires one of our lorries


class CrewRole(enum.StrEnum):
    DRIVER = "driver"
    TURNBOY = "turnboy"


class ComplianceDocType(enum.StrEnum):
    INSURANCE = "insurance"
    INSPECTION = "inspection"
    NTSA_LICENCE = "ntsa_licence"
    TLB_LICENCE = "tlb_licence"
    PERMIT = "permit"
    DRIVING_LICENCE = "driving_licence"
    OTHER = "other"


class PhotoKind(enum.StrEnum):
    ODOMETER = "odometer"
    CARGO = "cargo"
    DEFECT = "defect"
    RECEIPT = "receipt"
    INCIDENT = "incident"


class PhotoSource(enum.StrEnum):
    CAMERA = "camera"  # live capture in the mobile app
    WEB = "web"  # uploaded from the web dashboard; EXIF freshness is checked


class InspectionStatus(enum.StrEnum):
    PASSED = "passed"
    PASSED_WITH_DEFECTS = "passed_with_defects"
    BLOCKED = "blocked"  # a critical fault: no trip until a manager overrides
    OVERRIDDEN = "overridden"


class TripStatus(enum.StrEnum):
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    DELIVERED = "delivered"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ReadingPhase(enum.StrEnum):
    START = "start"
    END = "end"


class ExpenseCategory(enum.StrEnum):
    # Daily trip expenses: drivers record these.
    TOLL = "toll"
    PARKING = "parking"
    FOOD = "food"
    LOADING = "loading"
    POLICE_COUNTY = "police_county"
    # Other expenses and overheads: managers and accountants record these.
    REPAIR = "repair"
    TYRES = "tyres"
    INSURANCE = "insurance"
    LICENCE = "licence"
    PERMIT = "permit"
    GARAGE = "garage"
    SERVICE = "service"
    OVERHEAD = "overhead"
    OTHER = "other"


TRIP_CATEGORIES = {
    ExpenseCategory.TOLL,
    ExpenseCategory.PARKING,
    ExpenseCategory.FOOD,
    ExpenseCategory.LOADING,
    ExpenseCategory.POLICE_COUNTY,
}


class ExpenseStatus(enum.StrEnum):
    RECORDED = "recorded"  # counts straight away
    AWAITING_APPROVAL = "awaiting_approval"  # over a spend limit: does not count until the owner approves
    APPROVED = "approved"
    REJECTED = "rejected"


COUNTED = (ExpenseStatus.RECORDED, ExpenseStatus.APPROVED)


class ReconciliationStatus(enum.StrEnum):
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"


class WorkOrderStatus(enum.StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    WAITING_PARTS = "waiting_parts"
    DONE = "done"
    CANCELLED = "cancelled"


class WorkOrderSource(enum.StrEnum):
    DEFECT = "defect"
    SERVICE = "service"
    MANUAL = "manual"
    INCIDENT = "incident"


class Priority(enum.StrEnum):
    URGENT = "urgent"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


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
    # SMS code as the second step, instead of an authenticator app. Never both.
    sms_2fa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
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


class DeviceLogin(Base):
    """Quick sign-in on one phone: a secret only that phone holds, plus a PIN the person types."""

    __tablename__ = "device_logins"
    __table_args__ = (UniqueConstraint("user_id", "device_id"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    device_id: Mapped[str] = mapped_column(String(80))
    label: Mapped[str | None] = mapped_column(String(120))
    secret_hash: Mapped[str] = mapped_column(String(64))
    pin_hash: Mapped[str] = mapped_column(String(255))
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OtpChallenge(Base):
    __tablename__ = "otp_challenges"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    phone: Mapped[str] = mapped_column(String(20), index=True)
    # login: driver sign-in. sms_setup / second_step: SMS two-step verification. Codes never cross purposes.
    purpose: Mapped[str] = mapped_column(String(20), default="login", server_default="login")
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


class Party(TenantMixin, Base):
    """A lessor, lender or lessee. The full lease engine arrives in Sprint 10."""

    __tablename__ = "parties"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    kind: Mapped[PartyKind] = mapped_column(_enum(PartyKind))
    name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(20))
    kra_pin: Mapped[str | None] = mapped_column(String(20))
    payment_details: Mapped[str | None] = mapped_column(Text)  # M-Pesa or bank details
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Vehicle(TenantMixin, Base):
    __tablename__ = "vehicles"
    __table_args__ = (UniqueConstraint("business_id", "registration"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    registration: Mapped[str] = mapped_column(String(20))
    make: Mapped[str | None] = mapped_column(String(80))
    model: Mapped[str | None] = mapped_column(String(80))
    capacity_tonnes: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    fuel_type: Mapped[FuelType] = mapped_column(_enum(FuelType), default=FuelType.DIESEL)
    tank_litres: Mapped[int | None] = mapped_column(Integer)
    expected_kmpl_loaded: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    expected_kmpl_empty: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    odometer_km: Mapped[int] = mapped_column(Integer, default=0)
    tracking_tier: Mapped[TrackingTier] = mapped_column(_enum(TrackingTier), default=TrackingTier.BASIC)
    depot_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("depots.id", ondelete="SET NULL"))
    ownership_type: Mapped[OwnershipType] = mapped_column(_enum(OwnershipType), default=OwnershipType.OWNED)
    party_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parties.id", ondelete="RESTRICT"))
    # Legal limits for overload checks (masterplan 5.22).
    gvw_limit_kg: Mapped[int | None] = mapped_column(Integer)
    axle_config: Mapped[str | None] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StaffProfile(TenantMixin, Base):
    __tablename__ = "staff_profiles"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    membership_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("memberships.id", ondelete="CASCADE"), unique=True
    )
    licence_number: Mapped[str | None] = mapped_column(String(40))
    licence_class: Mapped[str | None] = mapped_column(String(20))
    emergency_contact_name: Mapped[str | None] = mapped_column(String(200))
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(20))
    monthly_salary_cents: Mapped[int | None] = mapped_column(BigInteger)


class CrewAssignment(TenantMixin, Base):
    """Who crews which vehicle. Rows are closed, never deleted, so history is kept."""

    __tablename__ = "crew_assignments"
    __table_args__ = (
        Index(
            "uq_crew_active_slot", "vehicle_id", "role", unique=True, postgresql_where=text("ended_at IS NULL")
        ),
        Index("uq_crew_active_person", "membership_id", unique=True, postgresql_where=text("ended_at IS NULL")),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    membership_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("memberships.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[CrewRole] = mapped_column(_enum(CrewRole))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ComplianceDocument(TenantMixin, Base):
    """Insurance, inspection and licence records. Belongs to a vehicle or to a staff member."""

    __tablename__ = "compliance_documents"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    doc_type: Mapped[ComplianceDocType] = mapped_column(_enum(ComplianceDocType))
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), index=True
    )
    membership_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("memberships.id", ondelete="CASCADE"), index=True
    )
    reference: Mapped[str | None] = mapped_column(String(80))
    issued_on: Mapped[date | None] = mapped_column(Date)
    expires_on: Mapped[date] = mapped_column(Date, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DocumentReminder(TenantMixin, Base):
    """One row per reminder sent, so a reminder never goes out twice."""

    __tablename__ = "document_reminders"
    __table_args__ = (UniqueConstraint("document_id", "expires_on", "days_before"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("compliance_documents.id", ondelete="CASCADE"), index=True
    )
    expires_on: Mapped[date] = mapped_column(Date)  # renewing the document starts a fresh set
    days_before: Mapped[int] = mapped_column(Integer)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Photo(TenantMixin, Base):
    """A photo in private storage. Viewed only through short-lived signed links."""

    __tablename__ = "photos"
    __table_args__ = (
        UniqueConstraint("business_id", "sha256"),
        UniqueConstraint("business_id", "client_id", name="uq_photos_business_client"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    kind: Mapped[PhotoKind] = mapped_column(_enum(PhotoKind))
    source: Mapped[PhotoSource] = mapped_column(_enum(PhotoSource))
    storage_key: Mapped[str] = mapped_column(String(200), unique=True)
    content_type: Mapped[str] = mapped_column(String(40))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # a photo backs one record only
    # Chosen by the phone, so a photo queued offline and re-sent after a lost reply is stored once.
    client_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    late: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))  # synced after the fresh window
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ChecklistItem(TenantMixin, Base):
    """One line of the pre-trip checklist. Each business can reword, add, and mark items critical."""

    __tablename__ = "checklist_items"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    label: Mapped[str] = mapped_column(String(120))
    critical: Mapped[bool] = mapped_column(Boolean, default=False)
    photo_on_fault: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Inspection(TenantMixin, Base):
    __tablename__ = "inspections"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    inspector_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    performed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    local_date: Mapped[date] = mapped_column(Date, index=True)  # Africa/Nairobi day the inspection counts for
    status: Mapped[InspectionStatus] = mapped_column(_enum(InspectionStatus))
    notes: Mapped[str | None] = mapped_column(Text)
    override_reason: Mapped[str | None] = mapped_column(Text)
    overridden_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    overridden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    results: Mapped[list["InspectionResult"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", order_by="InspectionResult.sort_order"
    )


class InspectionResult(TenantMixin, Base):
    __tablename__ = "inspection_results"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    inspection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inspections.id", ondelete="CASCADE"), index=True
    )
    item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("checklist_items.id", ondelete="SET NULL"))
    # Label and criticality are copied, so later checklist edits never rewrite history.
    label: Mapped[str] = mapped_column(String(120))
    critical: Mapped[bool] = mapped_column(Boolean)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(Boolean)
    note: Mapped[str | None] = mapped_column(Text)
    photo_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("photos.id", ondelete="SET NULL"))


class Defect(TenantMixin, Base):
    """A fault found in an inspection. Sprint 5 turns these into work orders."""

    __tablename__ = "defects"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    inspection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inspections.id", ondelete="CASCADE"), index=True)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(120))
    critical: Mapped[bool] = mapped_column(Boolean)
    note: Mapped[str | None] = mapped_column(Text)
    photo_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("photos.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(20), default="open")
    work_order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("work_orders.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Trip(TenantMixin, Base):
    __tablename__ = "trips"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    driver_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("memberships.id", ondelete="SET NULL"), index=True
    )
    turnboy_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("memberships.id", ondelete="SET NULL")
    )
    status: Mapped[TripStatus] = mapped_column(_enum(TripStatus), default=TripStatus.SCHEDULED, index=True)
    cargo_description: Mapped[str | None] = mapped_column(String(255))
    origin: Mapped[str | None] = mapped_column(String(160))
    destination: Mapped[str | None] = mapped_column(String(160))
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    inspection_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("inspections.id", ondelete="SET NULL"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    loaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cargo_photo_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("photos.id", ondelete="SET NULL"))
    loaded_weight_kg: Mapped[int | None] = mapped_column(Integer)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    distance_km: Mapped[int | None] = mapped_column(Integer)  # end odometer minus start odometer
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OdometerReading(TenantMixin, Base):
    __tablename__ = "odometer_readings"
    __table_args__ = (UniqueConstraint("trip_id", "phase"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    trip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    phase: Mapped[ReadingPhase] = mapped_column(_enum(ReadingPhase))
    photo_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("photos.id", ondelete="RESTRICT"))
    auto_read_value: Mapped[int | None] = mapped_column(Integer)  # what the number reader saw, if it ran
    confirmed_value: Mapped[int] = mapped_column(Integer)  # what the person confirmed
    flags: Mapped[list[str]] = mapped_column(JSONB, default=list)
    recorded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FuelEntry(TenantMixin, Base):
    __tablename__ = "fuel_entries"
    __table_args__ = (
        UniqueConstraint("business_id", "client_id"),
        UniqueConstraint("business_id", "mpesa_code"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    trip_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trips.id", ondelete="SET NULL"), index=True)
    litres: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    price_per_litre_cents: Mapped[int] = mapped_column(Integer)
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    station: Mapped[str | None] = mapped_column(String(120))
    mpesa_code: Mapped[str | None] = mapped_column(String(12))
    receipt_photo_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("photos.id", ondelete="SET NULL"))
    flags: Mapped[list[str]] = mapped_column(JSONB, default=list)
    client_id: Mapped[uuid.UUID | None] = mapped_column()
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # when the driver recorded it
    recorded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)  # when the server got it


class FloatTransfer(TenantMixin, Base):
    """Money the owner sends a driver for tolls, parking, food. Recording only; expenses arrive in Sprint 5."""

    __tablename__ = "float_transfers"
    __table_args__ = (UniqueConstraint("business_id", "mpesa_code"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    driver_membership_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("memberships.id", ondelete="CASCADE"), index=True
    )
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    mpesa_code: Mapped[str | None] = mapped_column(String(12))
    note: Mapped[str | None] = mapped_column(String(255))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SyncReceipt(TenantMixin, Base):
    """One row per offline action the server has applied, so a retried batch never applies anything twice."""

    __tablename__ = "sync_receipts"
    __table_args__ = (UniqueConstraint("business_id", "client_id"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    client_id: Mapped[uuid.UUID] = mapped_column()
    action_type: Mapped[str] = mapped_column(String(40))
    result: Mapped[dict] = mapped_column(JSONB, default=dict)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DeviceCheck(TenantMixin, Base):
    """A phone reported something suspicious: a mock-location app, root access, or a clock that is off."""

    __tablename__ = "device_checks"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    device_id: Mapped[str] = mapped_column(String(80))
    flags: Mapped[list[str]] = mapped_column(JSONB)
    clock_offset_s: Mapped[int | None] = mapped_column(Integer)
    app_version: Mapped[str | None] = mapped_column(String(40))
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Expense(TenantMixin, Base):
    __tablename__ = "expenses"
    __table_args__ = (
        UniqueConstraint("business_id", "client_id"),
        UniqueConstraint("business_id", "mpesa_code"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vehicles.id", ondelete="SET NULL"), index=True)
    trip_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trips.id", ondelete="SET NULL"), index=True)
    # Whose float it came out of (the person who spent it). Overheads have no one.
    driver_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("memberships.id", ondelete="SET NULL"), index=True
    )
    category: Mapped[ExpenseCategory] = mapped_column(_enum(ExpenseCategory))
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    note: Mapped[str | None] = mapped_column(String(255))
    mpesa_code: Mapped[str | None] = mapped_column(String(12))
    receipt_photo_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("photos.id", ondelete="SET NULL"))
    status: Mapped[ExpenseStatus] = mapped_column(_enum(ExpenseStatus), default=ExpenseStatus.RECORDED, index=True)
    from_float: Mapped[bool] = mapped_column(Boolean, default=False)  # paid out of the driver's float
    flags: Mapped[list[str]] = mapped_column(JSONB, default=list)
    work_order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("work_orders.id", ondelete="SET NULL"))
    client_id: Mapped[uuid.UUID | None] = mapped_column()
    spent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)  # when it happened
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SpendLimit(TenantMixin, Base):
    """An amount above which an expense waits for the owner. Blank category or role means "any"."""

    __tablename__ = "spend_limits"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    category: Mapped[ExpenseCategory | None] = mapped_column(_enum(ExpenseCategory))
    role: Mapped[Role | None] = mapped_column(_enum(Role))
    limit_cents: Mapped[int] = mapped_column(BigInteger)


class RouteCost(TenantMixin, Base):
    """What a category usually costs on a route (the tolls from Mombasa to Nairobi). A claim well above it is flagged."""

    __tablename__ = "route_costs"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    origin: Mapped[str] = mapped_column(String(160))
    destination: Mapped[str] = mapped_column(String(160))
    category: Mapped[ExpenseCategory] = mapped_column(_enum(ExpenseCategory))
    usual_cents: Mapped[int] = mapped_column(BigInteger)
    tolerance_pct: Mapped[int] = mapped_column(Integer, default=50)


class Reconciliation(TenantMixin, Base):
    """One driver's float for one Nairobi day: opening + floats - expenses = closing, approved by someone senior."""

    __tablename__ = "reconciliations"
    __table_args__ = (UniqueConstraint("business_id", "driver_membership_id", "day"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    driver_membership_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("memberships.id", ondelete="CASCADE"), index=True
    )
    day: Mapped[date] = mapped_column(Date, index=True)
    opening_cents: Mapped[int] = mapped_column(BigInteger)
    floats_cents: Mapped[int] = mapped_column(BigInteger)
    expenses_cents: Mapped[int] = mapped_column(BigInteger)
    closing_cents: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[ReconciliationStatus] = mapped_column(_enum(ReconciliationStatus))
    balance_action: Mapped[str | None] = mapped_column(String(20))  # carry_forward or returned
    note: Mapped[str | None] = mapped_column(String(255))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ServiceSchedule(TenantMixin, Base):
    """A repeating service: every so many kilometres, every so many months, whichever comes first."""

    __tablename__ = "service_schedules"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    every_km: Mapped[int | None] = mapped_column(Integer)
    every_months: Mapped[int | None] = mapped_column(Integer)
    last_done_km: Mapped[int] = mapped_column(Integer, default=0)
    last_done_on: Mapped[date | None] = mapped_column(Date)
    advance_km: Mapped[int] = mapped_column(Integer, default=500)
    advance_days: Mapped[int] = mapped_column(Integer, default=14)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ServiceRecord(TenantMixin, Base):
    """Service history: what was done to a vehicle, when, at what reading, and what it cost."""

    __tablename__ = "service_records"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    schedule_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("service_schedules.id", ondelete="SET NULL"))
    work_order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("work_orders.id", ondelete="SET NULL"))
    done_on: Mapped[date] = mapped_column(Date)
    odometer_km: Mapped[int] = mapped_column(Integer)
    cost_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    notes: Mapped[str | None] = mapped_column(Text)


class ServiceReminder(TenantMixin, Base):
    """One row per service reminder sent, so a due service is announced once, not every day."""

    __tablename__ = "service_reminders"
    __table_args__ = (UniqueConstraint("schedule_id", "due_key"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    schedule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("service_schedules.id", ondelete="CASCADE"))
    due_key: Mapped[str] = mapped_column(String(60))  # the km and date this service falls due at
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WorkOrder(TenantMixin, Base):
    """Preventive and corrective work share one system: from a defect, a service reminder, or raised by hand."""

    __tablename__ = "work_orders"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    source: Mapped[WorkOrderSource] = mapped_column(_enum(WorkOrderSource))
    defect_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("defects.id", ondelete="SET NULL"))
    schedule_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("service_schedules.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[Priority] = mapped_column(_enum(Priority), default=Priority.NORMAL)
    status: Mapped[WorkOrderStatus] = mapped_column(_enum(WorkOrderStatus), default=WorkOrderStatus.OPEN, index=True)
    assignee_kind: Mapped[str | None] = mapped_column(String(20))  # mechanic or garage
    assignee_name: Mapped[str | None] = mapped_column(String(160))
    labour_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    odometer_km: Mapped[int | None] = mapped_column(Integer)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    parts: Mapped[list["WorkOrderPart"]] = relationship(lazy="selectin", cascade="all, delete-orphan")


class WorkOrderPart(TenantMixin, Base):
    __tablename__ = "work_order_parts"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    work_order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("work_orders.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_cost_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    # Parts issued from the store point at it; the workshop later confirms the part was actually fitted.
    part_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parts.id", ondelete="SET NULL"))
    fitted: Mapped[bool] = mapped_column(Boolean, default=True)
    expense_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("expenses.id", ondelete="SET NULL"))


class ReportFrequency(enum.StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class ReportChannel(enum.StrEnum):
    EMAIL = "email"
    WHATSAPP = "whatsapp"


class ReportSchedule(TenantMixin, Base):
    """A report that is sent as a PDF on a schedule: yesterday, last week (Monday to Sunday) or last month."""

    __tablename__ = "report_schedules"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    frequency: Mapped[ReportFrequency] = mapped_column(Enum(ReportFrequency, native_enum=False, length=20, values_callable=lambda e: [m.value for m in e]))
    channel: Mapped[ReportChannel] = mapped_column(Enum(ReportChannel, native_enum=False, length=20, values_callable=lambda e: [m.value for m in e]))
    recipient: Mapped[str] = mapped_column(String(255))  # an email address, or a phone number for WhatsApp
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_period_end: Mapped[date | None] = mapped_column(Date)  # the last day covered by the report most recently sent
    last_error: Mapped[str | None] = mapped_column(String(255))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---- Tyres (masterplan 5.20) -----------------------------------------------------------------------


class TyreStatus(enum.StrEnum):
    IN_STORE = "in_store"
    FITTED = "fitted"
    REMOVED = "removed"  # taken off a vehicle, not yet back in the store or scrapped
    SCRAPPED = "scrapped"


class TyreEventKind(enum.StrEnum):
    FITTED = "fitted"
    REMOVED = "removed"
    ROTATED = "rotated"
    TREAD = "tread"
    RETREADED = "retreaded"
    SCRAPPED = "scrapped"


class Tyre(TenantMixin, Base):
    __tablename__ = "tyres"
    __table_args__ = (
        UniqueConstraint("business_id", "serial"),
        Index("uq_tyres_position", "vehicle_id", "position", unique=True, postgresql_where=text("status = 'fitted'")),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    serial: Mapped[str] = mapped_column(String(60))  # upper case, no spaces
    brand: Mapped[str] = mapped_column(String(80))
    size: Mapped[str] = mapped_column(String(40))
    cost_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    supplier: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[TyreStatus] = mapped_column(_enum(TyreStatus), default=TyreStatus.IN_STORE, index=True)
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vehicles.id", ondelete="SET NULL"), index=True)
    last_vehicle_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vehicles.id", ondelete="SET NULL"))
    position: Mapped[str | None] = mapped_column(String(40))
    fitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fitted_odometer_km: Mapped[int | None] = mapped_column(Integer)  # vehicle odometer when it went on
    moved_odometer_km: Mapped[int | None] = mapped_column(Integer)  # odometer at the last fitting or rotation
    km_before: Mapped[int] = mapped_column(Integer, default=0)  # kilometres run on earlier fittings
    retreads: Mapped[int] = mapped_column(Integer, default=0)
    retread_cost_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    last_tread_mm: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    last_tread_on: Mapped[date | None] = mapped_column(Date)
    cost_booked: Mapped[bool] = mapped_column(Boolean, default=False)  # the purchase cost is on a vehicle already
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TyreEvent(TenantMixin, Base):
    __tablename__ = "tyre_events"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    tyre_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tyres.id", ondelete="CASCADE"), index=True)
    kind: Mapped[TyreEventKind] = mapped_column(_enum(TyreEventKind))
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vehicles.id", ondelete="SET NULL"))
    position: Mapped[str | None] = mapped_column(String(40))
    odometer_km: Mapped[int | None] = mapped_column(Integer)
    tread_mm: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    cost_cents: Mapped[int | None] = mapped_column(BigInteger)
    note: Mapped[str | None] = mapped_column(String(255))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TyreSwapAlert(TenantMixin, Base):
    """A serial read at inspection that is not the tyre recorded at that position: a possible swap."""

    __tablename__ = "tyre_swap_alerts"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    inspection_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("inspections.id", ondelete="SET NULL"))
    position: Mapped[str] = mapped_column(String(40))
    expected_serial: Mapped[str | None] = mapped_column(String(60))
    seen_serial: Mapped[str] = mapped_column(String(60))
    reason: Mapped[str] = mapped_column(String(30))  # mismatch, unknown or elsewhere
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_note: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---- Spare parts store (masterplan 5.24) -----------------------------------------------------------


class StockKind(enum.StrEnum):
    RECEIVED = "received"
    ISSUED = "issued"
    RETURNED = "returned"
    COUNTED = "counted"  # a stock count corrected the quantity


class Part(TenantMixin, Base):
    __tablename__ = "parts"
    __table_args__ = (UniqueConstraint("business_id", "name"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160))
    sku: Mapped[str | None] = mapped_column(String(60))
    unit: Mapped[str] = mapped_column(String(20), default="pcs")
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    unit_cost_cents: Mapped[int] = mapped_column(BigInteger, default=0)  # weighted average of what was received
    reorder_level: Mapped[int] = mapped_column(Integer, default=0)
    supplier: Mapped[str | None] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StockMovement(TenantMixin, Base):
    __tablename__ = "stock_movements"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    part_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parts.id", ondelete="CASCADE"), index=True)
    kind: Mapped[StockKind] = mapped_column(_enum(StockKind))
    quantity_delta: Mapped[int] = mapped_column(Integer)
    balance_after: Mapped[int] = mapped_column(Integer)
    unit_cost_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    work_order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("work_orders.id", ondelete="SET NULL"))
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vehicles.id", ondelete="SET NULL"))
    note: Mapped[str | None] = mapped_column(String(255))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---- Incidents, fines and claims (masterplan 5.21) ---------------------------------------------------


class IncidentType(enum.StrEnum):
    BREAKDOWN = "breakdown"
    ACCIDENT = "accident"
    POLICE_STOP = "police_stop"
    TRAFFIC_FINE = "traffic_fine"
    COUNTY_CESS = "county_cess"
    CARGO_THEFT = "cargo_theft"


class FinePayer(enum.StrEnum):
    BUSINESS = "business"
    DRIVER = "driver"


class ClaimStatus(enum.StrEnum):
    FILED = "filed"
    DOCUMENTS_REQUESTED = "documents_requested"
    ASSESSED = "assessed"
    APPROVED = "approved"
    PAID = "paid"
    REJECTED = "rejected"


class Incident(TenantMixin, Base):
    __tablename__ = "incidents"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    type: Mapped[IncidentType] = mapped_column(_enum(IncidentType), index=True)
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vehicles.id", ondelete="SET NULL"), index=True)
    driver_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("memberships.id", ondelete="SET NULL"), index=True
    )
    trip_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trips.id", ondelete="SET NULL"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    description: Mapped[str | None] = mapped_column(Text)
    photo_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)  # open or resolved
    cost_cents: Mapped[int | None] = mapped_column(BigInteger)  # what it cost the business, once known
    fine_amount_cents: Mapped[int | None] = mapped_column(BigInteger)
    fine_payer: Mapped[FinePayer | None] = mapped_column(_enum(FinePayer))
    deduct_from_payroll: Mapped[bool] = mapped_column(Boolean, default=False)  # payroll arrives in a later sprint
    reference: Mapped[str | None] = mapped_column(String(60))  # ticket or receipt number
    work_order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("work_orders.id", ondelete="SET NULL"))
    expense_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("expenses.id", ondelete="SET NULL"))
    resolution_note: Mapped[str | None] = mapped_column(String(500))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class InsuranceClaim(TenantMixin, Base):
    __tablename__ = "insurance_claims"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    incident_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    insurer: Mapped[str] = mapped_column(String(120))
    policy_no: Mapped[str | None] = mapped_column(String(60))
    claim_no: Mapped[str | None] = mapped_column(String(60))
    status: Mapped[ClaimStatus] = mapped_column(_enum(ClaimStatus), default=ClaimStatus.FILED, index=True)
    amount_claimed_cents: Mapped[int | None] = mapped_column(BigInteger)
    amount_paid_cents: Mapped[int | None] = mapped_column(BigInteger)
    notes: Mapped[str | None] = mapped_column(Text)
    document_photo_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---- SOS (masterplan 5.21) ---------------------------------------------------------------------------


class SosAlert(TenantMixin, Base):
    __tablename__ = "sos_alerts"
    __table_args__ = (UniqueConstraint("business_id", "client_id"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    driver_membership_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("memberships.id", ondelete="SET NULL"))
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vehicles.id", ondelete="SET NULL"))
    trip_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trips.id", ondelete="SET NULL"))
    client_id: Mapped[uuid.UUID | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)  # active, acknowledged, resolved
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    track: Mapped[list[dict]] = mapped_column(JSONB, default=list)  # live position updates after the first
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # when the driver pressed it
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    notified: Mapped[int] = mapped_column(Integer, default=0)  # how many people were texted
    acknowledged_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(String(500))
