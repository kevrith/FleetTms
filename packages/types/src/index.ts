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
