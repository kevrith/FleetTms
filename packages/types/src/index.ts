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
  /** Only on the vehicle list. */
  trust_level?: TrustLevel;
}

export type VehicleInput = Omit<Vehicle, "id" | "trust_level">;

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

export type PhotoKind = "odometer" | "cargo" | "defect" | "receipt" | "incident";

export interface PhotoRef {
  id: string;
  kind: PhotoKind;
  source: "camera" | "web";
  captured_at: string;
  lat: number | null;
  lng: number | null;
  /** Relative, short-lived viewing link. Build the full address with api.mediaUrl(). */
  url: string;
}

export interface ChecklistItem {
  id: string;
  label: string;
  critical: boolean;
  photo_on_fault: boolean;
  is_active: boolean;
  sort_order: number;
}

export type InspectionStatus = "passed" | "passed_with_defects" | "blocked" | "overridden";

export interface InspectionResultRow {
  label: string;
  critical: boolean;
  ok: boolean;
  note: string | null;
  photo: PhotoRef | null;
}

export interface Inspection {
  id: string;
  vehicle_id: string;
  performed_at: string;
  status: InspectionStatus;
  notes: string | null;
  override_reason: string | null;
  overridden_at: string | null;
  results: InspectionResultRow[];
}

export interface InspectionAnswer {
  item_id: string;
  ok: boolean;
  note?: string | null;
  photo_id?: string | null;
}

export type TripStatus = "scheduled" | "in_progress" | "delivered" | "completed" | "cancelled";
export type OdometerFlag = "mismatch" | "backward" | "large_jump" | "no_location";

export interface OdometerReadingOut {
  value: number;
  auto_read_value: number | null;
  flags: OdometerFlag[];
  photo: PhotoRef | null;
  recorded_at: string;
}

export interface Trip {
  id: string;
  status: TripStatus;
  vehicle_id: string;
  registration: string | null;
  driver_membership_id: string | null;
  turnboy_membership_id: string | null;
  cargo_description: string | null;
  origin: string | null;
  destination: string | null;
  scheduled_for: string | null;
  started_at: string | null;
  loaded_at: string | null;
  loaded_weight_kg: number | null;
  cargo_photo: PhotoRef | null;
  delivered_at: string | null;
  ended_at: string | null;
  distance_km: number | null;
  start_reading: OdometerReadingOut | null;
  end_reading: OdometerReadingOut | null;
  inspection: { id: string; status: InspectionStatus; performed_at: string } | null;
}

export interface TripInput {
  vehicle_id: string;
  driver_membership_id?: string | null;
  turnboy_membership_id?: string | null;
  cargo_description?: string | null;
  origin?: string | null;
  destination?: string | null;
  scheduled_for?: string | null;
}

export interface ReadingInput {
  photo_id: string;
  value: number;
  auto_read_value?: number | null;
}

export interface PhotoUpload {
  kind: PhotoKind;
  source: "camera" | "web";
  /** ISO time the picture was taken. Required for camera photos; web photos are judged by their own metadata. */
  captured_at?: string;
  lat?: number | null;
  lng?: number | null;
}

export interface FuelEntry {
  id: string;
  vehicle_id: string;
  trip_id: string | null;
  litres: string;
  price_per_litre_cents: number;
  amount_cents: number;
  station: string | null;
  mpesa_code: string | null;
  has_receipt: boolean;
  flags: ("amount_mismatch" | "no_receipt")[];
  captured_at: string;
  client_id: string | null;
}

export interface FuelInput {
  vehicle_id: string;
  trip_id?: string | null;
  litres: string;
  price_per_litre_cents: number;
  amount_cents: number;
  station?: string | null;
  mpesa_code?: string | null;
  receipt_photo_id?: string | null;
  receipt_photo_client_id?: string | null;
  client_id?: string | null;
  captured_at?: string | null;
}

export interface FloatTransfer {
  id: string;
  driver_membership_id: string;
  amount_cents: number;
  mpesa_code: string | null;
  note: string | null;
  sent_at: string;
}

export interface MyFloat {
  balance_cents: number;
  received_cents: number;
  recent: FloatTransfer[];
}

export type TrustLevel = "high" | "medium" | "low";
export type DeviceFlag = "mock_location" | "rooted" | "clock_changed";

export interface VehicleTrust {
  level: TrustLevel;
  score: number;
  tier: TrackingTier;
  flags: { flag: DeviceFlag; count: number; last_at: string }[];
}

export interface DeviceReport {
  device_id: string;
  mock_location?: boolean;
  rooted?: boolean;
  device_time?: string;
  app_version?: string;
  vehicle_id?: string | null;
}

export interface SyncAction {
  client_id: string;
  type: string;
  payload: Record<string, unknown>;
}

export interface SyncResult {
  client_id: string;
  status: "ok" | "duplicate" | "rejected";
  result?: Record<string, unknown>;
  code?: string;
  message?: string;
  retryable?: boolean;
}

export interface SyncResponse {
  server_time: string;
  device_flags: DeviceFlag[];
  results: SyncResult[];
}

export type ExpenseCategory =
  | "toll"
  | "parking"
  | "food"
  | "loading"
  | "police_county"
  | "repair"
  | "tyres"
  | "insurance"
  | "licence"
  | "permit"
  | "garage"
  | "service"
  | "overhead"
  | "other";
export type ExpenseStatus = "recorded" | "awaiting_approval" | "approved" | "rejected";

export interface Expense {
  id: string;
  vehicle_id: string | null;
  trip_id: string | null;
  driver_membership_id: string | null;
  category: ExpenseCategory;
  amount_cents: number;
  note: string | null;
  mpesa_code: string | null;
  status: ExpenseStatus;
  from_float: boolean;
  flags: ("over_limit" | "unusual_for_route" | "no_receipt")[];
  spent_at: string;
  decision_note: string | null;
  decided_at: string | null;
  client_id: string | null;
  has_receipt: boolean;
  receipt: PhotoRef | null;
}

export interface ExpenseInput {
  category: ExpenseCategory;
  amount_cents: number;
  vehicle_id?: string | null;
  trip_id?: string | null;
  note?: string | null;
  mpesa_code?: string | null;
  receipt_photo_id?: string | null;
  receipt_photo_client_id?: string | null;
  client_id?: string | null;
  captured_at?: string | null;
  driver_membership_id?: string | null;
  from_float?: boolean | null;
}

export interface SpendLimit {
  id?: string;
  category: ExpenseCategory | null;
  role: Role | null;
  limit_cents: number;
}

export interface RouteCost {
  id: string;
  origin: string;
  destination: string;
  category: ExpenseCategory;
  usual_cents: number;
  tolerance_pct: number;
}

export type ReconciliationStatus = "open" | "submitted" | "approved" | "rejected";

export interface Reconciliation {
  id: string;
  driver_membership_id: string;
  driver_name: string | null;
  day: string;
  opening_cents: number;
  floats_cents: number;
  expenses_cents: number;
  closing_cents: number;
  status: ReconciliationStatus;
  balance_action: "carry_forward" | "returned" | null;
  note: string | null;
  submitted_at: string;
  decided_at: string | null;
}

export interface ReconciliationDetail extends Reconciliation {
  expenses: Expense[];
  pending_expenses: number;
}

export interface MySheet {
  day: string;
  opening_cents: number;
  floats_cents: number;
  expenses_cents: number;
  closing_cents: number;
  status: ReconciliationStatus;
  note: string | null;
  reconciliation: Reconciliation | null;
  expenses: Expense[];
}

export type Priority = "urgent" | "high" | "normal" | "low";
export type WorkOrderStatus = "open" | "in_progress" | "waiting_parts" | "done" | "cancelled";

export interface WorkOrder {
  id: string;
  vehicle_id: string;
  source: "defect" | "service" | "manual" | "incident";
  defect_id: string | null;
  schedule_id: string | null;
  title: string;
  description: string | null;
  priority: Priority;
  status: WorkOrderStatus;
  assignee_kind: "mechanic" | "garage" | null;
  assignee_name: string | null;
  labour_cents: number;
  parts_cents: number;
  total_cents: number;
  parts: {
    id: string;
    name: string;
    quantity: number;
    unit_cost_cents: number;
    part_id: string | null;
    fitted: boolean;
  }[];
  unfitted_parts: number;
  /** Only on the list endpoint. */
  registration?: string | null;
  odometer_km: number | null;
  opened_at: string;
  completed_at: string | null;
}

export interface ServiceSchedule {
  id: string;
  vehicle_id: string;
  registration: string;
  name: string;
  every_km: number | null;
  every_months: number | null;
  last_done_km: number;
  last_done_on: string | null;
  advance_km: number;
  advance_days: number;
  is_active: boolean;
  due_status: "ok" | "due_soon" | "overdue" | "inactive";
  next_km: number | null;
  km_left: number | null;
  next_due_on: string | null;
  days_left: number | null;
}

export interface ServiceInput {
  name: string;
  every_km?: number | null;
  every_months?: number | null;
  last_done_km?: number;
  last_done_on?: string | null;
  advance_km?: number;
  advance_days?: number;
  is_active?: boolean;
}

export interface ServiceHistory {
  schedules: ServiceSchedule[];
  history: {
    id: string;
    schedule_id: string | null;
    done_on: string;
    odometer_km: number;
    cost_cents: number;
    notes: string | null;
  }[];
}

export interface DashboardAlert {
  kind: string;
  severity: "red" | "amber";
  title: string;
  detail: string;
  link: string;
}

export interface Dashboard {
  numbers: {
    mode: "standard" | "owner_driver";
    day: string;
    trips_active?: number;
    trips_completed_today?: number;
    distance_today_km?: number;
    fuel_today?: { litres: number; amount_cents: number };
    expenses_today_cents?: number;
    floats_sent_today_cents?: number;
    income_today_cents: number | null;
    money_owed_cents: number | null;
  };
  alerts: DashboardAlert[];
  open_defects: number | null;
}

export interface ReportSchedule {
  id: string;
  frequency: "daily" | "weekly" | "monthly";
  channel: "email" | "whatsapp";
  recipient: string;
  is_active: boolean;
  last_period_end: string | null;
  last_error: string | null;
}

export interface ReportSummary {
  from: string;
  to: string;
  totals: {
    trips_completed: number;
    distance_km: number;
    fuel_litres: number;
    fuel_cents: number;
    expenses_cents: number;
    floats_sent_cents: number;
  };
  expenses_by_category: { category: ExpenseCategory; cents: number }[];
  by_vehicle: {
    vehicle_id: string;
    registration: string;
    trips: number;
    distance_km: number;
    fuel_litres: number;
    fuel_cents: number;
    expenses_cents: number;
    km_per_litre: number | null;
  }[];
  by_day: {
    day: string;
    trips: number;
    distance_km: number;
    fuel_cents: number;
    expenses_cents: number;
  }[];
}

// ---- Sprint 6: tyres, parts, incidents, SOS ----

export type TyreStatus = "in_store" | "fitted" | "removed" | "scrapped";

export interface Tyre {
  id: string;
  serial: string;
  brand: string;
  size: string;
  cost_cents: number;
  supplier: string | null;
  status: TyreStatus;
  vehicle_id: string | null;
  registration: string | null;
  position: string | null;
  fitted_at: string | null;
  km_run: number;
  retreads: number;
  retread_cost_cents: number;
  last_tread_mm: number | null;
  last_tread_on: string | null;
  cost_per_km_cents: number | null;
  due: ("replace" | "rotate")[];
}

export interface TyreCostGroup {
  name: string;
  tyres: number;
  cost_cents: number;
  km: number;
  cost_per_km_cents: number | null;
}

export interface TyreReport {
  by_brand: TyreCostGroup[];
  by_supplier: TyreCostGroup[];
  due: Tyre[];
}

export interface TyreAlert {
  id: string;
  vehicle_id: string;
  registration: string | null;
  position: string;
  expected_serial: string | null;
  seen_serial: string;
  reason: "mismatch" | "unknown" | "elsewhere";
  status: "open" | "resolved";
  created_at: string;
  resolved_at: string | null;
  resolution_note: string | null;
}

export interface Part {
  id: string;
  name: string;
  sku: string | null;
  unit: string;
  quantity: number;
  unit_cost_cents: number;
  stock_value_cents: number;
  reorder_level: number;
  low_stock: boolean;
  supplier: string | null;
  is_active: boolean;
}

export interface StockMovement {
  id: string;
  part_id: string;
  kind: "received" | "issued" | "returned" | "counted";
  quantity_delta: number;
  balance_after: number;
  unit_cost_cents: number;
  work_order_id: string | null;
  vehicle_id: string | null;
  note: string | null;
  created_at: string;
}

export interface UnfittedPart {
  id: string;
  work_order_id: string;
  work_order_title: string;
  work_order_status: WorkOrderStatus;
  registration: string;
  name: string;
  quantity: number;
  value_cents: number;
  closed: boolean;
}

export interface StockCountResult {
  counted: number;
  variances: {
    part_id: string;
    name: string;
    expected: number;
    counted: number;
    difference: number;
    value_cents: number;
  }[];
  net_value_cents: number;
}

export type IncidentType =
  "breakdown" | "accident" | "police_stop" | "traffic_fine" | "county_cess" | "cargo_theft";

export interface Incident {
  id: string;
  type: IncidentType;
  vehicle_id: string | null;
  registration: string | null;
  driver_membership_id: string | null;
  driver_name: string | null;
  trip_id: string | null;
  occurred_at: string;
  lat: number | null;
  lng: number | null;
  description: string | null;
  status: "open" | "resolved";
  cost_cents: number | null;
  fine_amount_cents: number | null;
  fine_payer: "business" | "driver" | null;
  deduct_from_payroll: boolean;
  reference: string | null;
  work_order_id: string | null;
  resolution_note: string | null;
  resolved_at: string | null;
  created_at: string;
  photos: { id: string; url: string }[];
  claims?: InsuranceClaim[];
}

export type ClaimStatus =
  "filed" | "documents_requested" | "assessed" | "approved" | "paid" | "rejected";

export interface InsuranceClaim {
  id: string;
  incident_id: string;
  insurer: string;
  policy_no: string | null;
  claim_no: string | null;
  status: ClaimStatus;
  amount_claimed_cents: number | null;
  amount_paid_cents: number | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  incident_type?: IncidentType;
  registration?: string | null;
}

export interface FineRow {
  id: string | null;
  name: string;
  fines: number;
  total_cents: number;
  business_cents: number;
  driver_cents: number;
  to_deduct_cents: number;
}

export interface FinesSummary {
  by_driver: FineRow[];
  by_vehicle: FineRow[];
}

export interface SosAlert {
  id: string;
  status: "active" | "acknowledged" | "resolved";
  driver_name: string | null;
  vehicle_id: string | null;
  registration: string | null;
  lat: number | null;
  lng: number | null;
  track: { lat: number; lng: number; at: string }[];
  sent_at: string;
  received_at: string;
  delay_s: number;
  notified: number;
  acknowledged_at: string | null;
  resolved_at: string | null;
  note: string | null;
  map_url: string | null;
}

/** Positions that have a recorded tyre on the driver's vehicle. The serials are deliberately not included. */
export interface MyTyrePositions {
  vehicle_id: string | null;
  positions: string[];
}

/** The driver's own open SOS alert, so the app can say whether anyone has answered. */
export interface MySos {
  id: string;
  status: "active" | "acknowledged";
  acknowledged: boolean;
  sent_at: string;
}

/** The little the workshop needs to know about a vehicle. */
export interface VehicleBrief {
  id: string;
  registration: string;
  make: string | null;
  model: string | null;
  odometer_km: number;
}
