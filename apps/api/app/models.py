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
    POD_CARGO = "pod_cargo"  # the cargo offloaded at the client
    DELIVERY_NOTE = "delivery_note"  # the signed delivery note
    DAMAGE = "damage"
    WEIGHBRIDGE = "weighbridge"  # the weighbridge ticket


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
    onboarding_dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # the owner hid the getting-started checklist
    fuel_region: Mapped[str] = mapped_column(String(40), default="Nairobi", server_default=text("'Nairobi'"))  # whose EPRA pump price quotes start from
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
    # A lessor's portal login belongs to the lessor it is for, and sees only that lessor's leases.
    party_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parties.id", ondelete="SET NULL"))
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
    email: Mapped[str | None] = mapped_column(String(255))
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
    tare_kg: Mapped[int | None] = mapped_column(Integer)  # the lorry's own weight, to work out gross weight from the cargo
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
    weighbridge_photo_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("photos.id", ondelete="SET NULL"))
    overload_kg: Mapped[int | None] = mapped_column(Integer)  # how far over the legal limit the loaded lorry was, if it was
    gps_distance_km: Mapped[float | None] = mapped_column(Float)  # what the phone's GPS says the trip came to
    gps_points: Mapped[int | None] = mapped_column(Integer)  # how many good fixes that is worked out from
    distance_check: Mapped[str | None] = mapped_column(String(10))  # ok, mismatch or no_gps: do odometer and GPS agree
    tracker_distance_km: Mapped[float | None] = mapped_column(Float)  # what the vehicle's tracker says the trip came to
    tracker_points: Mapped[int | None] = mapped_column(Integer)
    distance_detail: Mapped[dict | None] = mapped_column(JSONB)  # the three distances and which one disagrees, if one does
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), index=True)
    planned_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # when the booking is expected to finish
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
    deduct_from_payroll: Mapped[bool] = mapped_column(Boolean, default=False)
    payroll_deducted_cents: Mapped[int] = mapped_column(BigInteger, default=0)  # how much of the driver's fine payroll has taken so far
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


# ---- Clients, quotes, jobs (masterplan 5.10 and 5.17) ----------------------------------------------


class BillingMethod(enum.StrEnum):
    PER_TRIP = "per_trip"
    PER_TONNE = "per_tonne"
    PER_KM = "per_km"
    MONTHLY_CONTRACT = "monthly_contract"


class QuoteStatus(enum.StrEnum):
    DRAFT = "draft"
    SENT = "sent"
    ACCEPTED = "accepted"
    DECLINED = "declined"


class JobStatus(enum.StrEnum):
    PLANNED = "planned"
    DISPATCHED = "dispatched"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class Client(TenantMixin, Base):
    __tablename__ = "clients"
    __table_args__ = (UniqueConstraint("business_id", "name"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160))
    contact_name: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(255))
    kra_pin: Mapped[str | None] = mapped_column(String(11))
    billing_method: Mapped[BillingMethod] = mapped_column(_enum(BillingMethod), default=BillingMethod.PER_TRIP)
    rate_cents: Mapped[int] = mapped_column(BigInteger, default=0)  # per trip, per tonne, per km or the monthly fee
    payment_terms_days: Mapped[int] = mapped_column(Integer, default=30)
    vat_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)  # VAT added to this client's invoices
    reminders_enabled: Mapped[bool] = mapped_column(Boolean, default=True)  # False: never send this client payment reminders
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SavedRoute(TenantMixin, Base):
    """A client's route, stored once and reused on every quote and job."""

    __tablename__ = "saved_routes"
    __table_args__ = (UniqueConstraint("business_id", "client_id", "name"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    client_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    pickup: Mapped[str] = mapped_column(String(160))
    dropoff: Mapped[str] = mapped_column(String(160))
    dropoff_lat: Mapped[float | None] = mapped_column(Float)  # the client's site, so a delivery elsewhere can be flagged
    dropoff_lng: Mapped[float | None] = mapped_column(Float)
    site_radius_m: Mapped[int] = mapped_column(Integer, default=500)
    path_notes: Mapped[str | None] = mapped_column(Text)  # the preferred path
    distance_km: Mapped[int] = mapped_column(Integer, default=0)
    expected_hours: Mapped[float] = mapped_column(Float, default=12)
    tolls_cents: Mapped[int] = mapped_column(BigInteger, default=0)  # per trip
    crew_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    other_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Quote(TenantMixin, Base):
    __tablename__ = "quotes"
    __table_args__ = (UniqueConstraint("business_id", "number"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    number: Mapped[str] = mapped_column(String(20))
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    route_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("saved_routes.id", ondelete="SET NULL"))
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vehicles.id", ondelete="SET NULL"))
    cargo_description: Mapped[str | None] = mapped_column(String(255))
    weight_tonnes: Mapped[Decimal] = mapped_column(Numeric(9, 2), default=0)
    trips: Mapped[int] = mapped_column(Integer, default=1)
    return_empty: Mapped[bool] = mapped_column(Boolean, default=True)
    billing_method: Mapped[BillingMethod] = mapped_column(_enum(BillingMethod))
    rate_cents: Mapped[int] = mapped_column(BigInteger)
    distance_km: Mapped[int] = mapped_column(Integer)
    kmpl_loaded: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    kmpl_empty: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    fuel_price_cents: Mapped[int] = mapped_column(BigInteger)
    tolls_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    crew_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    other_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    price_cents: Mapped[int] = mapped_column(BigInteger)
    total_cost_cents: Mapped[int] = mapped_column(BigInteger)
    expected_profit_cents: Mapped[int] = mapped_column(BigInteger)
    margin_pct: Mapped[float | None] = mapped_column(Float)
    status: Mapped[QuoteStatus] = mapped_column(_enum(QuoteStatus), default=QuoteStatus.DRAFT, index=True)
    valid_until: Mapped[date | None] = mapped_column(Date)
    pickup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deliver_by: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    instructions: Mapped[str | None] = mapped_column(Text)
    sent_via: Mapped[str | None] = mapped_column(String(20))
    sent_to: Mapped[str | None] = mapped_column(String(255))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(String(255))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Job(TenantMixin, Base):
    """Work for a client: from an accepted quote, set up directly, or repeated from an earlier job. One job can need
    several trips (120 tonnes moved over four loads)."""

    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("business_id", "number"), UniqueConstraint("business_id", "quote_id"))
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    number: Mapped[str] = mapped_column(String(20))
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    quote_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("quotes.id", ondelete="SET NULL"))
    route_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("saved_routes.id", ondelete="SET NULL"))
    repeat_of_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    cargo_description: Mapped[str | None] = mapped_column(String(255))
    weight_tonnes: Mapped[Decimal] = mapped_column(Numeric(9, 2), default=0)
    trips_planned: Mapped[int] = mapped_column(Integer, default=1)
    billing_method: Mapped[BillingMethod] = mapped_column(_enum(BillingMethod))
    rate_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    price_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    expected_profit_cents: Mapped[int | None] = mapped_column(BigInteger)
    pickup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deliver_by: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    instructions: Mapped[str | None] = mapped_column(Text)
    status: Mapped[JobStatus] = mapped_column(_enum(JobStatus), default=JobStatus.PLANNED, index=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---- Proof of delivery and invoices (masterplan 5.18 and 5.10) -------------------------------------


class ProofOfDelivery(TenantMixin, Base):
    __tablename__ = "proofs_of_delivery"
    __table_args__ = (UniqueConstraint("business_id", "trip_id"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    trip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    recipient_name: Mapped[str] = mapped_column(String(120))
    method: Mapped[str] = mapped_column(String(12))  # code (one-time code to the client's phone) or signature
    signature: Mapped[list | None] = mapped_column(JSONB)  # pen strokes, drawn into the invoice when it is printed
    cargo_photo_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("photos.id", ondelete="SET NULL"))
    note_photo_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("photos.id", ondelete="SET NULL"))
    damage_photo_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    shortage_qty: Mapped[Decimal | None] = mapped_column(Numeric(9, 2))
    shortage_unit: Mapped[str | None] = mapped_column(String(20))
    damage_notes: Mapped[str | None] = mapped_column(Text)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    flags: Mapped[list[str]] = mapped_column(JSONB, default=list)  # outside_site, no_location, shortage, damage
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PodCode(TenantMixin, Base):
    """A one-time code texted to the client's phone, which the recipient gives the driver as proof they received the load."""

    __tablename__ = "pod_codes"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    trip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    sent_to: Mapped[str] = mapped_column(String(20))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Invoice(TenantMixin, Base):
    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("business_id", "number"),
        UniqueConstraint("business_id", "trip_id"),
        UniqueConstraint("business_id", "job_id", "period_start"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    number: Mapped[str] = mapped_column(String(20))
    client_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    trip_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trips.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(10))  # trip or contract
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    issue_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="issued", index=True)  # issued, partially_paid, paid, void
    subtotal_cents: Mapped[int] = mapped_column(BigInteger)
    vat_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    vat_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    total_cents: Mapped[int] = mapped_column(BigInteger)
    paid_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    void_reason: Mapped[str | None] = mapped_column(String(255))
    sent_via: Mapped[str | None] = mapped_column(String(20))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    lines: Mapped[list["InvoiceLine"]] = relationship(lazy="selectin", cascade="all, delete-orphan", order_by="InvoiceLine.sort_order")
    payments: Mapped[list["InvoicePayment"]] = relationship(lazy="selectin", cascade="all, delete-orphan", order_by="InvoicePayment.created_at")


class InvoiceLine(TenantMixin, Base):
    __tablename__ = "invoice_lines"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    trip_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trips.id", ondelete="SET NULL"))
    description: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=1)
    unit_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    amount_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class InvoicePayment(TenantMixin, Base):
    """Money received against an invoice: entered by hand, or matched from an M-Pesa payment."""

    __tablename__ = "invoice_payments"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    method: Mapped[str] = mapped_column(String(20))  # cash, mpesa, bank or cheque
    reference: Mapped[str | None] = mapped_column(String(60))
    received_on: Mapped[date] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(String(255))
    mpesa_transaction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("mpesa_transactions.id", ondelete="SET NULL"), index=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PaymentSettings(TenantMixin, Base):
    """One row per business: where clients pay by M-Pesa, when they are reminded, and how invoices go to KRA eTIMS."""

    __tablename__ = "payment_settings"
    __table_args__ = (UniqueConstraint("business_id"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    shortcode: Mapped[str | None] = mapped_column(String(10))  # the Paybill or Till number clients pay to
    shortcode_type: Mapped[str] = mapped_column(String(8), default="paybill")
    urls_registered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reminders_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    reminder_offsets: Mapped[list[int]] = mapped_column(JSONB, default=lambda: [-3, 1, 7, 14, 30])  # days from the due date
    reminder_channels: Mapped[list[str]] = mapped_column(JSONB, default=lambda: ["sms", "email"])
    etims_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    etims_branch_id: Mapped[str] = mapped_column(String(2), default="00")
    etims_device_serial: Mapped[str | None] = mapped_column(String(100))
    etims_zero_vat_code: Mapped[str] = mapped_column(String(1), default="A")  # eTIMS tax code for invoices with no VAT
    etims_item_code: Mapped[str] = mapped_column(String(20), default="KE3NTXU0000001")
    etims_item_class_code: Mapped[str] = mapped_column(String(10), default="78101800")  # UNSPSC: road cargo transport
    etims_pkg_unit: Mapped[str] = mapped_column(String(5), default="NT")
    etims_qty_unit: Mapped[str] = mapped_column(String(5), default="U")
    etims_connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class MpesaTransaction(TenantMixin, Base):
    """Money a client paid in by M-Pesa, as Safaricom reported it (or as the statement showed it). One row per M-Pesa
    code, so Safaricom sending the same payment twice changes nothing. Matched to invoices through InvoicePayment."""

    __tablename__ = "mpesa_transactions"
    __table_args__ = (UniqueConstraint("business_id", "trans_id"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    trans_id: Mapped[str] = mapped_column(String(12))
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    allocated_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    bill_ref: Mapped[str | None] = mapped_column(String(60))  # what the client typed as the account number
    payer_name: Mapped[str | None] = mapped_column(String(160))
    payer_phone: Mapped[str | None] = mapped_column(String(80))  # Safaricom may send this hashed
    shortcode: Mapped[str | None] = mapped_column(String(10))
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(12), default="daraja")  # daraja, statement or simulated
    status: Mapped[str] = mapped_column(String(14), default="unmatched", index=True)  # matched, partly_matched, unmatched, dismissed
    reason: Mapped[str | None] = mapped_column(String(30))  # why it is not fully matched
    dismissed_reason: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MpesaStatementImport(TenantMixin, Base):
    __tablename__ = "mpesa_statement_imports"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    filename: Mapped[str | None] = mapped_column(String(200))
    rows: Mapped[int] = mapped_column(Integer, default=0)
    new_rows: Mapped[int] = mapped_column(Integer, default=0)
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MpesaStatementLine(TenantMixin, Base):
    """One line of an M-Pesa statement. Money that left the account is matched to a fuel entry, an expense or a float
    transfer by its M-Pesa code; money that came in is matched to a client payment."""

    __tablename__ = "mpesa_statement_lines"
    __table_args__ = (UniqueConstraint("business_id", "receipt"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    import_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("mpesa_statement_imports.id", ondelete="SET NULL"), index=True)
    receipt: Mapped[str] = mapped_column(String(12))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    details: Mapped[str | None] = mapped_column(String(255))
    paid_in_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    withdrawn_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    match_kind: Mapped[str | None] = mapped_column(String(16))  # fuel, expense, float, client_payment
    match_id: Mapped[uuid.UUID | None] = mapped_column()
    state: Mapped[str] = mapped_column(String(14), default="unmatched", index=True)  # matched, amount_differs, unmatched, ignored
    note: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PaymentReminder(TenantMixin, Base):
    """A reminder sent to a client about an unpaid invoice. An automatic one is sent once per invoice, step and channel."""

    __tablename__ = "payment_reminders"
    __table_args__ = (UniqueConstraint("business_id", "invoice_id", "offset_days", "channel"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    offset_days: Mapped[int | None] = mapped_column(Integer)  # days from the due date; empty for one sent by hand
    channel: Mapped[str] = mapped_column(String(10))
    recipient: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(8), default="sent")  # sent or failed
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    error: Mapped[str | None] = mapped_column(String(255))
    sent_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EtimsSubmission(TenantMixin, Base):
    """An invoice (or the credit note that cancels a voided one) on its way to KRA eTIMS."""

    __tablename__ = "etims_submissions"
    __table_args__ = (UniqueConstraint("business_id", "invoice_id", "kind"), UniqueConstraint("business_id", "invoice_no"))
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    invoice_no: Mapped[int] = mapped_column(Integer)  # the number eTIMS knows it by: one sequence per business, credit notes included
    kind: Mapped[str] = mapped_column(String(12), default="sale")  # sale or credit_note
    status: Mapped[str] = mapped_column(String(12), default="pending", index=True)  # pending, submitted, needs_review, resolved
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))
    receipt_no: Mapped[str | None] = mapped_column(String(40))
    sdc_id: Mapped[str | None] = mapped_column(String(40))
    sdc_time: Mapped[str | None] = mapped_column(String(20))
    receipt_signature: Mapped[str | None] = mapped_column(String(200))
    internal_data: Mapped[str | None] = mapped_column(String(200))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_note: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---- Leasing, asset finance, ownership costs (masterplan 5.23) -------------------------------------------------


class LeaseAgreement(TenantMixin, Base):
    """A lorry hired in from a lessor, or hired out to a lessee. One running agreement per vehicle."""

    __tablename__ = "lease_agreements"
    __table_args__ = (Index("uq_lease_active_vehicle", "vehicle_id", unique=True, postgresql_where=text("status = 'active'")),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    direction: Mapped[str] = mapped_column(String(3))  # in (we pay a lessor) or out (a lessee pays us)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    party_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parties.id", ondelete="RESTRICT"), index=True)
    status: Mapped[str] = mapped_column(String(8), default="active")  # active or ended
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    notice_days: Mapped[int] = mapped_column(Integer, default=30)
    deposit_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    fixed_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    fixed_period: Mapped[str | None] = mapped_column(String(5))  # month, week or day
    per_trip_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    per_km_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    revenue_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    profit_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    min_guarantee_cents: Mapped[int] = mapped_column(BigInteger, default=0)  # per month
    responsibilities: Mapped[dict] = mapped_column(JSONB, default=dict)  # cost responsibility matrix: item -> lessee or lessor
    payment_due_days: Mapped[int] = mapped_column(Integer, default=7)  # days after a month ends that its charge is due
    share_trips: Mapped[bool] = mapped_column(Boolean, default=False)  # the lessor may see this lorry's trips
    share_location: Mapped[bool] = mapped_column(Boolean, default=False)  # the lessor may see its location (live map arrives in Sprint 11)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LeaseEntry(TenantMixin, Base):
    """One line of a lease account. A charge or adjustment adds to what is owed; an offset or a payment takes away."""

    __tablename__ = "lease_entries"
    __table_args__ = (
        Index("uq_lease_charge_period", "agreement_id", "period_start", unique=True, postgresql_where=text("kind = 'charge'")),
        UniqueConstraint("business_id", "source_kind", "source_id"),
        UniqueConstraint("business_id", "mpesa_code"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    agreement_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lease_agreements.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # charge, offset, payment or adjustment
    period_start: Mapped[date | None] = mapped_column(Date)  # the month a charge or offset belongs to
    entry_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    amount_cents: Mapped[int] = mapped_column(BigInteger)  # signed: charges and adjustments up, offsets and payments down
    description: Mapped[str] = mapped_column(String(255))
    basis: Mapped[dict | None] = mapped_column(JSONB)  # the workings behind a charge
    source_kind: Mapped[str | None] = mapped_column(String(10))  # expense or fuel: what an offset is for
    source_id: Mapped[uuid.UUID | None] = mapped_column()
    method: Mapped[str | None] = mapped_column(String(10))  # for a payment: mpesa, bank, cash or cheque
    mpesa_code: Mapped[str | None] = mapped_column(String(12))
    reference: Mapped[str | None] = mapped_column(String(60))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LeaseNotice(TenantMixin, Base):
    """A due-date or overdue message already sent for a lease, so it is sent once."""

    __tablename__ = "lease_notices"
    __table_args__ = (UniqueConstraint("business_id", "agreement_id", "period_start", "kind"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    agreement_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lease_agreements.id", ondelete="CASCADE"), index=True)
    period_start: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(8))  # due or overdue
    sent_to: Mapped[int] = mapped_column(Integer, default=0)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FinanceAgreement(TenantMixin, Base):
    """A loan on a lorry: the schedule is worked out once, then repayments are ticked off against it."""

    __tablename__ = "finance_agreements"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    party_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parties.id", ondelete="RESTRICT"))
    principal_cents: Mapped[int] = mapped_column(BigInteger)
    annual_rate_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    months: Mapped[int] = mapped_column(Integer)
    first_due: Mapped[date] = mapped_column(Date)
    instalment_cents: Mapped[int] = mapped_column(BigInteger)
    reference: Mapped[str | None] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(8), default="active")  # active or closed
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    instalments: Mapped[list["FinanceInstalment"]] = relationship(lazy="selectin", cascade="all, delete-orphan", order_by="FinanceInstalment.number")


class FinanceInstalment(TenantMixin, Base):
    __tablename__ = "finance_instalments"
    __table_args__ = (UniqueConstraint("agreement_id", "number"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    agreement_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("finance_agreements.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    due_date: Mapped[date] = mapped_column(Date, index=True)
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    interest_cents: Mapped[int] = mapped_column(BigInteger)
    principal_cents: Mapped[int] = mapped_column(BigInteger)
    paid_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    paid_on: Mapped[date | None] = mapped_column(Date)
    method: Mapped[str | None] = mapped_column(String(10))
    mpesa_code: Mapped[str | None] = mapped_column(String(12))
    reference: Mapped[str | None] = mapped_column(String(60))


class OwnershipCost(TenantMixin, Base):
    """A fixed cost of owning a lorry, spread evenly across months: insurance, licences, depreciation."""

    __tablename__ = "ownership_costs"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(12))  # insurance, licence, depreciation or other
    name: Mapped[str] = mapped_column(String(120))
    amount_cents: Mapped[int] = mapped_column(BigInteger)  # per year or per month, or the purchase cost for depreciation
    period: Mapped[str] = mapped_column(String(5), default="year")
    salvage_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    life_months: Mapped[int | None] = mapped_column(Integer)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---- Payroll (masterplan 5.11) -------------------------------------------------------------------------------------


class SalaryAdvance(TenantMixin, Base):
    __tablename__ = "salary_advances"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    membership_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("memberships.id", ondelete="CASCADE"), index=True)
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    remaining_cents: Mapped[int] = mapped_column(BigInteger)  # still to be taken from salary
    given_on: Mapped[date] = mapped_column(Date)
    mpesa_code: Mapped[str | None] = mapped_column(String(12))
    note: Mapped[str | None] = mapped_column(String(255))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PayrollRun(TenantMixin, Base):
    __tablename__ = "payroll_runs"
    __table_args__ = (UniqueConstraint("business_id", "month"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    month: Mapped[date] = mapped_column(Date)  # the first day of the month
    status: Mapped[str] = mapped_column(String(10), default="draft")  # draft, approved or paid
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_on: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    lines: Mapped[list["PayrollLine"]] = relationship(lazy="selectin", cascade="all, delete-orphan")


class PayrollLine(TenantMixin, Base):
    __tablename__ = "payroll_lines"
    __table_args__ = (UniqueConstraint("run_id", "membership_id"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("payroll_runs.id", ondelete="CASCADE"), index=True)
    membership_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("memberships.id", ondelete="CASCADE"), index=True)
    gross_cents: Mapped[int] = mapped_column(BigInteger)
    advances_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    fines_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    net_cents: Mapped[int] = mapped_column(BigInteger)
    deductions: Mapped[list[dict]] = mapped_column(JSONB, default=list)  # what was taken and from what: advance or fine, id, cents
    allocation: Mapped[list[dict]] = mapped_column(JSONB, default=list)  # the salary cost spread over vehicles by days crewed


# ---- Suppliers and parts orders (masterplan 5.9) ---------------------------------------------------------------------


class Supplier(TenantMixin, Base):
    __tablename__ = "suppliers"
    __table_args__ = (UniqueConstraint("business_id", "name"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160))
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(255))
    category: Mapped[str | None] = mapped_column(String(60))  # for example spares, tyres, fuel
    notes: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PartsOrder(TenantMixin, Base):
    __tablename__ = "parts_orders"
    __table_args__ = (UniqueConstraint("business_id", "number"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    number: Mapped[str] = mapped_column(String(20))
    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("suppliers.id", ondelete="RESTRICT"), index=True)
    status: Mapped[str] = mapped_column(String(10), default="draft", index=True)  # draft, sent, confirmed, collected, paid, cancelled
    notes: Mapped[str | None] = mapped_column(String(500))
    expected_on: Mapped[date | None] = mapped_column(Date)
    total_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_reference: Mapped[str | None] = mapped_column(String(60))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    lines: Mapped[list["PartsOrderLine"]] = relationship(lazy="selectin", cascade="all, delete-orphan", order_by="PartsOrderLine.sort_order")


class PartsOrderLine(TenantMixin, Base):
    __tablename__ = "parts_order_lines"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parts_orders.id", ondelete="CASCADE"), index=True)
    part_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parts.id", ondelete="SET NULL"))
    description: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_cost_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    received_quantity: Mapped[int] = mapped_column(Integer, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


# ---- Phone GPS, live map and client tracking links (masterplan 5.3 and 5.26) ---------------------------------------


class LocationPoint(TenantMixin, Base):
    """Where a lorry was, as its crew's phone reported it during a trip. A TimescaleDB hypertable on recorded_at; raw points are
    kept 12 months, after which the trip totals are all that remain."""

    __tablename__ = "location_points"
    __table_args__ = (
        UniqueConstraint("business_id", "vehicle_id", "recorded_at"),
        Index("ix_location_points_vehicle_time", "vehicle_id", "recorded_at"),
        Index("ix_location_points_trip_time", "trip_id", "recorded_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)  # when the phone took the fix
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"))
    trip_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trips.id", ondelete="SET NULL"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    speed_kmh: Mapped[float | None] = mapped_column(Float)
    heading: Mapped[float | None] = mapped_column(Float)
    accuracy_m: Mapped[float | None] = mapped_column(Float)
    ignition: Mapped[bool | None] = mapped_column(Boolean)  # engine on, from a tracker
    source: Mapped[str] = mapped_column(String(8), default="phone")  # phone or tracker
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TrackingGap(TenantMixin, Base):
    """A lorry on a trip stopped reporting its position. Opened by the watcher, closed when the next fix arrives."""

    __tablename__ = "tracking_gaps"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    trip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # the last fix before it went quiet, if any
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    notified: Mapped[int] = mapped_column(Integer, default=0)  # how many people were texted


class TrackingLink(TenantMixin, Base):
    """A secret link a client can open to follow one delivery. Only a hash of the secret is kept."""

    __tablename__ = "tracking_links"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    trip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_to: Mapped[str | None] = mapped_column(String(20))
    views: Mapped[int] = mapped_column(Integer, default=0)
    last_viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---- GPS trackers, mapped areas, tamper alerts, driving behaviour, immobiliser (masterplan 5.3, 5.12, 5.25, 5.28) -------


class TrackerDevice(TenantMixin, Base):
    """A GPS tracker fitted to a vehicle. Its IMEI is how Traccar names it, so an IMEI belongs to one business on the platform."""

    __tablename__ = "tracker_devices"
    __table_args__ = (UniqueConstraint("imei"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    imei: Mapped[str] = mapped_column(String(20))
    name: Mapped[str | None] = mapped_column(String(120))
    brand: Mapped[str | None] = mapped_column(String(40))
    model: Mapped[str | None] = mapped_column(String(60))
    sim_phone: Mapped[str | None] = mapped_column(String(20))
    supports_immobiliser: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # anything heard from the device
    last_position_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    battery_pct: Mapped[float | None] = mapped_column(Float)
    power_v: Mapped[float | None] = mapped_column(Float)  # the vehicle's supply to the tracker
    power_ok: Mapped[bool | None] = mapped_column(Boolean)
    ignition: Mapped[bool | None] = mapped_column(Boolean)
    gps_ok: Mapped[bool | None] = mapped_column(Boolean)
    online_state: Mapped[str] = mapped_column(String(8), default="unknown")  # online, offline or unknown
    immobilised: Mapped[bool] = mapped_column(Boolean, default=False)
    traccar_id: Mapped[int | None] = mapped_column(Integer)  # Traccar's own number for it, found when a command is sent
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Geofence(TenantMixin, Base):
    """A mapped area: a depot, a client's site, a fuel station or a place lorries must not go."""

    __tablename__ = "geofences"
    __table_args__ = (UniqueConstraint("business_id", "name"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(14), default="client_site")  # depot, client_site, fuel_station or restricted
    shape: Mapped[dict] = mapped_column(JSONB)  # {"type": "circle", lat, lng, radius_m} or {"type": "polygon", points: [[lat, lng]]}
    alert_on: Mapped[list[str]] = mapped_column(JSONB, default=list)  # which of enter and exit raise an alert
    vehicle_ids: Mapped[list[str] | None] = mapped_column(JSONB)  # only these vehicles; none means every vehicle
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GeofencePresence(TenantMixin, Base):
    """Which side of an area a vehicle is on, remembered so an entry or exit is noticed once and not on every fix."""

    __tablename__ = "geofence_presence"
    __table_args__ = (UniqueConstraint("vehicle_id", "geofence_id"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    geofence_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("geofences.id", ondelete="CASCADE"), index=True)
    inside: Mapped[bool | None] = mapped_column(Boolean)
    pending: Mapped[int] = mapped_column(Integer, default=0)
    changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GeofenceEvent(TenantMixin, Base):
    __tablename__ = "geofence_events"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    geofence_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("geofences.id", ondelete="CASCADE"), index=True)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    trip_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trips.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(5))  # enter or exit
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)


class TrackerAlert(TenantMixin, Base):
    """Something wrong with a tracker or what it reported: power cut, jamming, offline, tamper, and the like."""

    __tablename__ = "tracker_alerts"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    device_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tracker_devices.id", ondelete="SET NULL"))
    trip_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trips.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(20), index=True)  # power_cut, low_battery, gps_jamming, device_offline, tamper, sos, geofence
    severity: Mapped[str] = mapped_column(String(5))  # red or amber
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(12), default="open", index=True)  # open, explained, confirmed or resolved
    note: Mapped[str | None] = mapped_column(String(500))
    handled_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notified: Mapped[int] = mapped_column(Integer, default=0)  # how many people were texted


class BehaviourEvent(TenantMixin, Base):
    """Speeding, harsh braking and the rest, with the driver who was on the trip when it happened."""

    __tablename__ = "behaviour_events"
    __table_args__ = (UniqueConstraint("business_id", "vehicle_id", "kind", "at"), Index("ix_behaviour_vehicle_time", "vehicle_id", "at"))
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"))
    driver_membership_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("memberships.id", ondelete="SET NULL"), index=True)
    trip_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trips.id", ondelete="SET NULL"), index=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    value: Mapped[float | None] = mapped_column(Float)  # top speed, braking strength, minutes idle, and so on
    limit_value: Mapped[float | None] = mapped_column(Float)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(8), default="tracker")  # tracker or phone
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BehaviourState(TenantMixin, Base):
    """What the behaviour rules remember about a vehicle between batches of fixes."""

    __tablename__ = "behaviour_state"
    __table_args__ = (UniqueConstraint("vehicle_id"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"))
    state: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ImmobiliserCommand(TenantMixin, Base):
    """A request to stop (or release) a vehicle's engine. Two steps, owner only, checked for safety at both."""

    __tablename__ = "immobiliser_commands"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tracker_devices.id", ondelete="CASCADE"))
    action: Mapped[str] = mapped_column(String(10))  # immobilise or release
    status: Mapped[str] = mapped_column(String(22), default="awaiting_confirmation", index=True)  # awaiting_confirmation, sent, acknowledged, failed, refused, expired, cancelled
    reason: Mapped[str | None] = mapped_column(String(255))  # why the owner did it, or why it was refused
    speed_kmh: Mapped[float | None] = mapped_column(Float)  # what the vehicle was doing when the request was made
    position_age_s: Mapped[int | None] = mapped_column(Integer)
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_note: Mapped[str | None] = mapped_column(String(255))


# ---- Fraud engine, scorecards, fuel prices, beta feedback (masterplan 5.13, 5.25, 5.28) -------------------------------


class FraudAlert(TenantMixin, Base):
    """One thing the fraud engine found, with the numbers behind it. The same finding is never raised twice (dedupe_key)."""

    __tablename__ = "fraud_alerts"
    __table_args__ = (UniqueConstraint("business_id", "dedupe_key"), Index("ix_fraud_alerts_status_created", "status", "created_at"))
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(40), index=True)  # fuel_variance, odometer_mismatch, side_trip, long_stop, tamper_then_stop, ...
    severity: Mapped[str] = mapped_column(String(5))  # red or amber
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    trip_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trips.id", ondelete="SET NULL"), index=True)
    driver_membership_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("memberships.id", ondelete="SET NULL"), index=True)
    subject_type: Mapped[str | None] = mapped_column(String(30))  # the record it came from: tracker_alert, tyre_swap_alert, expense, ...
    subject_id: Mapped[str | None] = mapped_column(String(64))
    dedupe_key: Mapped[str] = mapped_column(String(160))
    title: Mapped[str] = mapped_column(String(200))
    detail: Mapped[str | None] = mapped_column(String(500))
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)  # the numbers, times and places behind the finding
    trust_level: Mapped[str | None] = mapped_column(String(6))  # the vehicle's trust level when it was raised
    status: Mapped[str] = mapped_column(String(12), default="open", index=True)  # open, explained or confirmed
    note: Mapped[str | None] = mapped_column(String(500))
    handled_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notified: Mapped[int] = mapped_column(Integer, default=0)  # how many people were told by text or email
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)  # when it happened, not when we noticed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AlertSettings(TenantMixin, Base):
    """A business's own alert thresholds and who is told how. Anything not set here uses the built-in default."""

    __tablename__ = "alert_settings"
    __table_args__ = (UniqueConstraint("business_id"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    thresholds: Mapped[dict] = mapped_column(JSONB, default=dict)
    channels: Mapped[dict] = mapped_column(JSONB, default=dict)  # {"red": {"roles": [...], "channels": [...]}, "amber": {...}}
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FuelPrice(TenantMixin, Base):
    """The monthly pump price (EPRA publishes one per town). Quotes start from the newest one."""

    __tablename__ = "fuel_prices"
    __table_args__ = (UniqueConstraint("business_id", "month", "region"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    month: Mapped[date] = mapped_column(Date, index=True)  # the first day of the month it applies to
    region: Mapped[str] = mapped_column(String(40))  # Nairobi, Mombasa, Kisumu, Nakuru, Eldoret
    diesel_cents: Mapped[int] = mapped_column(Integer)  # per litre
    petrol_cents: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(10), default="manual")  # epra (fetched) or manual (typed in)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Feedback(TenantMixin, Base):
    """What a beta tester typed into the feedback button."""

    __tablename__ = "feedback"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(10), default="idea")  # problem, idea or praise
    message: Mapped[str] = mapped_column(String(2000))
    page: Mapped[str | None] = mapped_column(String(200))  # where in the app they were
    app: Mapped[str | None] = mapped_column(String(10))  # web or mobile
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
