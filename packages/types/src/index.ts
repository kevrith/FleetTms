export interface HealthResponse {
  status: "ok";
  service: string;
  version: string;
  database: "up" | "down";
  redis: "up" | "down";
}

/** Money is always stored in cents (KES). */
export type Cents = number;

export type Role =
  "owner" | "manager" | "supervisor" | "accountant" | "driver" | "turnboy" | "workshop" | "lessor";

export type DocumentKind = "terms" | "privacy" | "dpa" | "monitoring_notice";

export interface Tokens {
  access_token: string;
  refresh_token: string;
}

export interface TokenResponse extends Tokens {
  token_type: "bearer";
  mfa_setup_required: boolean;
  business_id: string | null;
}

export interface Company {
  business_id: string;
  name: string;
  roles: Role[];
}

export interface PendingDocument {
  document: DocumentKind;
  version: string;
}

export interface Me {
  user: { id: string; name: string; email: string | null; phone: string | null };
  business: { id: string; name: string | null } | null;
  roles: Role[];
  permissions: string[];
  companies: Company[];
  is_platform_admin: boolean;
  support_access: boolean;
  mfa_setup_required: boolean;
  two_factor_enabled: boolean;
  two_factor_method: "totp" | "sms" | null;
  pending_documents: PendingDocument[];
}

export interface StaffMember {
  membership_id: string;
  user_id: string;
  name: string;
  email: string | null;
  phone: string | null;
  roles: Role[];
  vehicle_scope: string[] | null;
  depot_id: string | null;
  status: "active" | "revoked";
  two_factor_enabled: boolean;
  invite_token?: string | null;
}

export interface Depot {
  id: string;
  name: string;
  location: string | null;
}

export interface AuditEntry {
  id: string;
  actor_user_id: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  note: string | null;
  created_at: string;
}

export interface SupportGrant {
  id: string;
  reason: string;
  expires_at: string;
  revoked_at: string | null;
}

export interface SignupInput {
  business_name: string;
  name: string;
  email: string;
  phone?: string | null;
  password: string;
  accept_terms: boolean;
  accept_privacy: boolean;
  accept_dpa: boolean;
}

export interface InviteInput {
  name: string;
  email?: string | null;
  phone?: string | null;
  roles: Role[];
  depot_id?: string | null;
  vehicle_scope?: string[] | null;
}

export type FuelType = "diesel" | "petrol";
export type TrackingTier = "basic" | "standard" | "premium";
export type OwnershipType = "owned" | "asset_financed" | "leased_in" | "leased_out";
export type PartyKind = "lessor" | "lender" | "lessee";
export type CrewRole = "driver" | "turnboy";
export type ComplianceDocType =
  | "insurance"
  | "inspection"
  | "ntsa_licence"
  | "tlb_licence"
  | "permit"
  | "driving_licence"
  | "other";

export interface Vehicle {
  id: string;
  registration: string;
  make: string | null;
  model: string | null;
  capacity_tonnes: string | null;
  fuel_type: FuelType;
  tank_litres: number | null;
  expected_kmpl_loaded: string | null;
  expected_kmpl_empty: string | null;
  odometer_km: number;
  tracking_tier: TrackingTier;
  depot_id: string | null;
  ownership_type: OwnershipType;
  party_id: string | null;
  gvw_limit_kg: number | null;
  axle_config: string | null;
  is_active: boolean;
}

export type VehicleInput = Omit<Vehicle, "id">;

export interface Party {
  id: string;
  kind: PartyKind;
  name: string;
  phone: string | null;
  kra_pin: string | null;
  payment_details: string | null;
}

export type PartyInput = Omit<Party, "id">;

export interface CrewAssignment {
  id: string;
  vehicle_id: string;
  membership_id: string;
  role: CrewRole;
  started_at: string;
  ended_at: string | null;
}

export interface StaffProfile {
  membership_id: string;
  name: string;
  phone: string | null;
  email: string | null;
  roles: Role[];
  status: "active" | "revoked";
  depot_id: string | null;
  licence_number: string | null;
  licence_class: string | null;
  emergency_contact_name: string | null;
  emergency_contact_phone: string | null;
  vehicle_id: string | null;
  crew_role: CrewRole | null;
  /** Present only for people with payroll access. */
  monthly_salary_cents?: number | null;
}

export interface ProfileInput {
  licence_number: string | null;
  licence_class: string | null;
  emergency_contact_name: string | null;
  emergency_contact_phone: string | null;
  monthly_salary_cents?: number | null;
}

export interface ComplianceDocument {
  id: string;
  doc_type: ComplianceDocType;
  vehicle_id: string | null;
  membership_id: string | null;
  reference: string | null;
  issued_on: string | null;
  expires_on: string;
}

export type DocumentInput = Omit<ComplianceDocument, "id">;

export interface MyVehicle {
  vehicle: {
    id: string;
    registration: string;
    make: string | null;
    model: string | null;
    capacity_tonnes: string | null;
    fuel_type: FuelType;
    tank_litres: number | null;
    odometer_km: number;
  };
  my_role: CrewRole;
  crew: { role: CrewRole; name: string; phone: string | null }[];
}

export interface ImportResult {
  dry_run: boolean;
  rows: number;
  imported: number;
  errors: { row: number; column: string | null; message: string }[];
  invite_tokens: { row: number; name: string; invite_token: string }[];
}
