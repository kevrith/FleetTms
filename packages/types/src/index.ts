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
  /** For a lessor: whose leases the login can see. */
  party_id?: string | null;
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
  tare_kg: number | null;
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
  email?: string | null;
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
    gvw_limit_kg: number | null;
    tare_kg: number | null;
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

export type PhotoKind =
  | "odometer"
  | "cargo"
  | "defect"
  | "receipt"
  | "incident"
  | "pod_cargo"
  | "delivery_note"
  | "damage"
  | "weighbridge";

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

export interface ProofOfDeliveryOut {
  recipient_name: string;
  method: "code" | "signature";
  captured_at: string;
  flags: ("outside_site" | "no_location" | "shortage" | "damage")[];
  has_signature: boolean;
  lat: number | null;
  lng: number | null;
  shortage_qty: number | null;
  shortage_unit: string | null;
  damage_notes: string | null;
  cargo_photo: PhotoRef | null;
  note_photo: PhotoRef | null;
  damage_photos: PhotoRef[];
}

/** What the driver sends to prove a delivery. Photos are named by the id the phone gave them. */
export interface ProofOfDeliveryInput {
  recipient_name: string;
  method: "code" | "signature";
  code?: string | null;
  signature?: number[][][] | null;
  cargo_photo_id?: string | null;
  cargo_photo_client_id?: string | null;
  note_photo_id?: string | null;
  note_photo_client_id?: string | null;
  shortage_qty?: string | null;
  shortage_unit?: string | null;
  damage_notes?: string | null;
  damage_photo_ids?: string[];
  damage_photo_client_ids?: string[];
  lat?: number | null;
  lng?: number | null;
}

/** The job a trip belongs to, as the driver needs to see it. */
export interface TripJob {
  id: string;
  number: string;
  client_name: string;
  instructions: string | null;
  pickup_at: string | null;
  deliver_by: string | null;
  trips_planned: number;
  /** Per-tonne jobs need the weighbridge ticket when the cargo is loaded. */
  billing_method: "per_trip" | "per_tonne" | "per_km" | "monthly_contract";
}

export interface Trip {
  id: string;
  job?: TripJob | null;
  planned_end?: string | null;
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
  /** How far over the legal limit the load was when it was weighed; 0 when within it. */
  overload_kg?: number | null;
  weighbridge_photo?: PhotoRef | null;
  pod?: ProofOfDeliveryOut | null;
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
  /** This month so far; only for those who may see invoices. */
  profit_vs_cash: ProfitVsCash | null;
  /** Last month after every deduction, for those who may see finances. */
  profit_last_month: ProfitLastMonth | null;
}

export interface ProfitLastMonth {
  month: string;
  business: ProfitBusiness;
  vehicles: {
    vehicle_id: string;
    registration: string;
    ownership_type: string;
    revenue_cents: number;
    gross_profit_cents: number;
    lease_payable_cents: number;
    net_profit_cents: number;
    lease_not_paying: boolean;
  }[];
}

export interface ProfitVsCash {
  month_start: string;
  billed_cents: number;
  costs_cents: number;
  profit_cents: number;
  received_cents: number;
  cash_cents: number;
  owed_cents: number;
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

// ---- Sprint 7: clients, quotes, jobs, dispatch ----

export type BillingMethod = "per_trip" | "per_tonne" | "per_km" | "monthly_contract";

export interface Client {
  id: string;
  name: string;
  contact_name: string | null;
  phone: string | null;
  email: string | null;
  kra_pin: string | null;
  billing_method: BillingMethod;
  rate_cents: number;
  payment_terms_days: number;
  vat_pct: number;
  notes: string | null;
  is_active: boolean;
  reminders_enabled: boolean;
  routes: number;
  open_jobs: number;
  route_list?: SavedRoute[];
}

export interface SavedRoute {
  id: string;
  client_id: string | null;
  client_name: string | null;
  name: string;
  pickup: string;
  dropoff: string;
  dropoff_lat: number | null;
  dropoff_lng: number | null;
  site_radius_m: number;
  path_notes: string | null;
  distance_km: number;
  expected_hours: number;
  tolls_cents: number;
  crew_cents: number;
  other_cents: number;
  notes: string | null;
  is_active: boolean;
}

export type QuoteStatus = "draft" | "sent" | "accepted" | "declined";

export interface Quote {
  id: string;
  number: string;
  client_id: string;
  client_name: string | null;
  route_id: string | null;
  route_name: string | null;
  vehicle_id: string | null;
  cargo_description: string | null;
  weight_tonnes: number;
  trips: number;
  return_empty: boolean;
  billing_method: BillingMethod;
  rate_cents: number;
  distance_km: number;
  kmpl_loaded: number;
  kmpl_empty: number;
  fuel_price_cents: number;
  tolls_cents: number;
  crew_cents: number;
  other_cents: number;
  price_cents: number;
  fuel_litres: number;
  fuel_cents: number;
  cost_per_trip_cents: number;
  total_cost_cents: number;
  expected_profit_cents: number;
  margin_pct: number | null;
  status: QuoteStatus;
  expired: boolean;
  valid_until: string | null;
  pickup_at: string | null;
  deliver_by: string | null;
  instructions: string | null;
  sent_via: string | null;
  sent_to: string | null;
  sent_at: string | null;
  decided_at: string | null;
  decision_note: string | null;
  job_id: string | null;
  job_number: string | null;
}

export interface QuoteDefaults {
  billing_method: BillingMethod;
  rate_cents: number;
  distance_km: number;
  kmpl_loaded: number;
  kmpl_empty: number;
  fuel_price_cents: number;
  tolls_cents: number;
  crew_cents: number;
  other_cents: number;
}

export type JobStatus = "planned" | "dispatched" | "in_progress" | "completed" | "cancelled";

export interface Job {
  id: string;
  number: string;
  client_id: string;
  client_name: string | null;
  quote_id: string | null;
  repeat_of_id: string | null;
  route_id: string | null;
  route: { id: string; name: string; pickup: string; dropoff: string; distance_km: number } | null;
  cargo_description: string | null;
  weight_tonnes: number;
  trips_planned: number;
  trips_dispatched: number;
  trips_completed: number;
  billing_method: BillingMethod;
  pickup_at: string | null;
  deliver_by: string | null;
  instructions: string | null;
  status: JobStatus;
  created_at: string;
  completed_at: string | null;
  /** Only for people allowed to see money. */
  rate_cents?: number;
  price_cents?: number;
  expected_profit_cents?: number | null;
  trips?: {
    id: string;
    status: TripStatus;
    scheduled_for: string | null;
    planned_end: string | null;
    vehicle_id: string;
    registration: string | null;
    driver_name: string | null;
    distance_km: number | null;
  }[];
}

export interface CalendarBooking {
  trip_id: string;
  job_id: string | null;
  job_number: string | null;
  client_name: string | null;
  from: string;
  to: string;
  status: TripStatus;
  route: string | null;
  driver_name: string | null;
}

export interface CalendarDay {
  date: string;
  status: "free" | "booked" | "in_service";
}

export interface DispatchCalendar {
  from: string;
  to: string;
  vehicles: {
    id: string;
    registration: string;
    in_service: boolean;
    service: { work_order_id: string; title: string; status: string } | null;
    bookings: CalendarBooking[];
    days: CalendarDay[];
  }[];
  crew: {
    membership_id: string;
    name: string;
    role: "driver" | "turnboy";
    bookings: CalendarBooking[];
    days: CalendarDay[];
  }[];
}

export interface Availability {
  vehicles: {
    id: string;
    registration: string;
    free: boolean;
    reason: "in_workshop" | "booked" | null;
  }[];
  crew: {
    membership_id: string;
    name: string;
    role: "driver" | "turnboy";
    free: boolean;
    reason: "booked" | null;
  }[];
}

export type InvoiceStatus = "issued" | "partially_paid" | "paid" | "void";

export interface InvoiceEtims {
  status: EtimsStatus;
  receipt_no: string | null;
  last_error: string | null;
  credit_note_status: EtimsStatus | null;
}

export interface Invoice {
  id: string;
  number: string;
  client_id: string;
  client_name: string | null;
  kind: "trip" | "contract";
  job_id: string | null;
  trip_id: string | null;
  period_start: string | null;
  period_end: string | null;
  issue_date: string;
  due_date: string;
  status: InvoiceStatus;
  overdue: boolean;
  subtotal_cents: number;
  vat_pct: number;
  vat_cents: number;
  total_cents: number;
  paid_cents: number;
  balance_cents: number;
  void_reason: string | null;
  sent_via: string | null;
  sent_at: string | null;
  etims?: InvoiceEtims | null;
  reminders?: {
    id: string;
    channel: "sms" | "email";
    status: "sent" | "failed";
    sent_at: string;
    error: string | null;
    automatic: boolean;
  }[];
  lines?: {
    id: string;
    trip_id: string | null;
    description: string;
    quantity: number;
    unit_cents: number;
    amount_cents: number;
  }[];
  payments?: {
    id: string;
    amount_cents: number;
    method: string;
    reference: string | null;
    received_on: string;
    note: string | null;
  }[];
}

// ---- Sprint 9: payments, debtors, eTIMS ----

export type AgeingBucketKey = "current" | "1_30" | "31_60" | "61_90" | "over_90";
export type AgeingBuckets = Record<AgeingBucketKey, number>;

export type MpesaPaymentStatus = "matched" | "partly_matched" | "unmatched" | "dismissed";

export interface MpesaPayment {
  id: string;
  trans_id: string;
  amount_cents: number;
  allocated_cents: number;
  left_cents: number;
  bill_ref: string | null;
  payer_name: string | null;
  paid_at: string;
  source: "daraja" | "statement" | "simulated";
  status: MpesaPaymentStatus;
  reason: string | null;
  reason_text: string | null;
  dismissed_reason: string | null;
  suggestions?: { id: string; number: string; balance_cents: number }[];
}

export interface PaymentSettings {
  shortcode: string | null;
  shortcode_type: "paybill" | "till";
  urls_registered_at: string | null;
  daraja_live: boolean;
  can_simulate: boolean;
  confirmation_url?: string;
  validation_url?: string;
  reminders_enabled: boolean;
  reminder_offsets: number[];
  reminder_channels: ("sms" | "email")[];
  etims_enabled: boolean;
  etims_live: boolean;
  etims_branch_id: string;
  etims_device_serial: string | null;
  etims_zero_vat_code: "A" | "C" | "D";
  etims_item_code: string;
  etims_item_class_code: string;
  etims_pkg_unit: string;
  etims_qty_unit: string;
  etims_connected_at: string | null;
  kra_pin: string | null;
}

export interface DebtorClient {
  client_id: string;
  name: string;
  phone: string | null;
  email: string | null;
  reminders_enabled: boolean;
  balance_cents: number;
  overdue_cents: number;
  buckets: AgeingBuckets;
  invoices: number;
  oldest_due: string;
  oldest_days_late: number;
  last_payment_on: string | null;
}

export interface Debtors {
  as_of: string;
  balance_cents: number;
  overdue_cents: number;
  buckets: AgeingBuckets;
  clients: DebtorClient[];
}

export interface DebtorDetail {
  client: {
    id: string;
    name: string;
    phone: string | null;
    email: string | null;
    payment_terms_days: number;
    reminders_enabled: boolean;
  };
  as_of: string;
  balance_cents: number;
  buckets: AgeingBuckets;
  invoices: {
    id: string;
    number: string;
    issue_date: string;
    due_date: string;
    total_cents: number;
    balance_cents: number;
    days_late: number;
    bucket: AgeingBucketKey;
  }[];
  payments: {
    invoice_id: string;
    invoice_number: string;
    received_on: string;
    amount_cents: number;
    method: string;
    reference: string | null;
  }[];
  reminders: {
    invoice_number: string;
    channel: string;
    status: string;
    sent_at: string;
    automatic: boolean;
  }[];
}

export type EtimsStatus = "pending" | "submitted" | "needs_review" | "resolved";

export interface EtimsSubmission {
  id: string;
  invoice_id: string;
  invoice_number: string | null;
  client_name: string | null;
  total_cents: number | null;
  kind: "sale" | "credit_note";
  status: EtimsStatus;
  status_text: string;
  invoice_no: number;
  attempts: number;
  next_attempt_at: string | null;
  last_attempt_at: string | null;
  last_error: string | null;
  receipt_no: string | null;
  sdc_id: string | null;
  submitted_at: string | null;
  resolved_note: string | null;
}

export interface EtimsSummary {
  enabled: boolean;
  connected_at: string | null;
  pending: number;
  submitted: number;
  needs_review: number;
  resolved: number;
}

export interface StatementLine {
  id: string;
  receipt: string;
  completed_at: string;
  details: string | null;
  paid_in_cents: number;
  withdrawn_cents: number;
  match_kind: "fuel" | "expense" | "float" | "client_payment" | null;
  match_label: string | null;
  match_id: string | null;
  state: "matched" | "amount_differs" | "unmatched" | "ignored";
  note: string | null;
}

export interface StatementImport {
  id: string;
  filename: string | null;
  rows: number;
  new_rows: number;
  period_start: string | null;
  period_end: string | null;
  created_at: string;
  summary: {
    skipped: number;
    already_known: number;
    matched: number;
    amount_differs: number;
    unmatched: number;
    payments_recovered: number;
    not_on_statement: { kind: string; id: string; mpesa_code: string; amount_cents: number }[];
  };
}

// ---- Sprint 10: leases, loans, ownership costs, profit, payroll, suppliers ----

export type LeaseDirection = "in" | "out";
export type Responsibility = "lessee" | "lessor";

export interface LeaseAgreement {
  id: string;
  direction: LeaseDirection;
  vehicle_id: string;
  registration: string | null;
  party_id: string;
  party_name: string | null;
  status: "active" | "ended";
  start_date: string;
  end_date: string | null;
  notice_days: number;
  deposit_cents: number;
  fixed_cents: number;
  fixed_period: "month" | "week" | "day" | null;
  per_trip_cents: number;
  per_km_cents: number;
  revenue_pct: number;
  profit_pct: number;
  min_guarantee_cents: number;
  responsibilities: Record<string, Responsibility>;
  payment_due_days: number;
  share_trips: boolean;
  share_location: boolean;
  notes: string | null;
  /** On the list and detail views. */
  balance_cents?: number;
  overdue_cents?: number;
  next_due_date?: string | null;
}

export interface LeaseEntry {
  id: string;
  kind: "charge" | "offset" | "payment" | "adjustment";
  period_start: string | null;
  entry_date: string;
  due_date: string | null;
  amount_cents: number;
  description: string;
  basis: Record<string, unknown> | null;
  method: string | null;
  mpesa_code: string | null;
  reference: string | null;
  source_kind: string | null;
}

export interface LeaseDetail extends LeaseAgreement {
  entries: LeaseEntry[];
  this_month: {
    month: string;
    days_active: number;
    charge_cents: number;
    subtotal_cents: number;
    guarantee_cents: number;
    guarantee_applied: boolean;
  } | null;
}

export interface LeaseStatement {
  agreement_id: string;
  direction: LeaseDirection;
  vehicle: string;
  party: string;
  month: string;
  deposit_cents: number;
  opening_balance_cents: number;
  closing_balance_cents: number;
  lines: LeaseEntry[];
  usage: Partial<Record<"trips" | "km" | "revenue_cents" | "profit_cents", number>>;
  trips: { delivered_at: string; route: string; distance_km: number }[];
  trip_count: number | null;
  balance_cents: number;
  overdue_cents: number;
  next_due_date: string | null;
  payable_cents: number;
}

export interface FinanceRow {
  number: number;
  due_date: string;
  amount_cents: number;
  interest_cents: number;
  principal_cents: number;
  paid_cents: number;
  paid_on: string | null;
  method: string | null;
  mpesa_code: string | null;
  reference: string | null;
  overdue: boolean;
}

export interface FinanceAgreement {
  id: string;
  vehicle_id: string;
  registration: string | null;
  party_id: string;
  party_name: string | null;
  principal_cents: number;
  annual_rate_pct: number;
  months: number;
  first_due: string;
  instalment_cents: number;
  reference: string | null;
  status: "active" | "closed";
  notes: string | null;
  principal_balance_cents: number;
  outstanding_cents: number;
  overdue_cents: number;
  next_due_date: string | null;
  total_interest_cents: number;
  schedule?: FinanceRow[];
}

export interface OwnershipCost {
  id: string;
  vehicle_id: string;
  registration: string | null;
  kind: "insurance" | "licence" | "depreciation" | "other";
  name: string;
  amount_cents: number;
  period: "year" | "month";
  salvage_cents: number;
  life_months: number | null;
  start_date: string;
  end_date: string | null;
  notes: string | null;
  monthly_cents: number;
}

export interface ProfitVehicle {
  vehicle_id: string;
  registration: string;
  ownership_type: string;
  revenue: number;
  fuel: number;
  expenses: number;
  crew: number;
  lessor_paid: number;
  operating: number;
  gross: number;
  lease_charges: number;
  lease_offsets: number;
  lease_payable: number;
  lease_income: number;
  finance: number;
  ownership: number;
  net: number;
  trips: number;
  km: number;
  loaded_km: number;
  empty_km: number;
  unbilled: number;
  estimated: number;
  cost_per_km: number | null;
  revenue_per_km: number | null;
  lease_not_paying: boolean;
  provisional: boolean;
}

export interface ProfitBusiness {
  revenue: number;
  operating: number;
  gross: number;
  lease_payable: number;
  lease_income: number;
  finance: number;
  ownership: number;
  net: number;
  trips: number;
  km: number;
  loaded_km: number;
  empty_km: number;
  unbilled: number;
  estimated: number;
  lessor_paid: number;
  overheads: number;
  overhead_expenses: number;
  overhead_payroll: number;
  net_after_overheads: number;
}

export interface ProfitGroupRow {
  name: string;
  trips: number;
  revenue_cents: number;
  direct_cost_cents: number;
  contribution_cents: number;
  distance_km: number;
}

export interface ProfitTripRow {
  trip_id: string;
  registration: string;
  route: string;
  delivered_at: string;
  client_name: string | null;
  driver_name: string | null;
  distance_km: number;
  revenue_cents: number;
  direct_cost_cents: number;
  contribution_cents: number;
  estimated: boolean;
  unbilled: boolean;
}

export interface ProfitReport {
  from_month: string;
  to_month: string;
  months: string[];
  vehicles: ProfitVehicle[];
  depots: {
    name: string;
    vehicles: number;
    revenue: number;
    operating: number;
    gross: number;
    lease_payable: number;
    finance: number;
    ownership: number;
    net: number;
  }[];
  trips: ProfitTripRow[];
  clients: ProfitGroupRow[];
  drivers: ProfitGroupRow[];
  business: ProfitBusiness;
}

export interface PayrollRun {
  id: string;
  month: string;
  status: "draft" | "approved" | "paid";
  approved_at: string | null;
  paid_on: string | null;
  people: number;
  gross_cents: number;
  deductions_cents: number;
  net_cents: number;
  lines?: {
    id: string;
    membership_id: string;
    name: string | null;
    gross_cents: number;
    advances_cents: number;
    fines_cents: number;
    net_cents: number;
    deductions: { kind: "advance" | "fine"; id: string; cents: number; note: string | null }[];
    allocation: { registration: string | null; cents: number }[];
  }[];
}

export interface SalaryAdvance {
  id: string;
  membership_id: string;
  name: string | null;
  amount_cents: number;
  remaining_cents: number;
  given_on: string;
  mpesa_code: string | null;
  note: string | null;
}

export interface Supplier {
  id: string;
  name: string;
  phone: string | null;
  email: string | null;
  category: string | null;
  notes: string | null;
  is_active: boolean;
}

export type OrderStatus = "draft" | "sent" | "confirmed" | "collected" | "paid" | "cancelled";

export interface PartsOrder {
  id: string;
  number: string;
  supplier_id: string;
  supplier_name: string | null;
  status: OrderStatus;
  notes: string | null;
  expected_on: string | null;
  total_cents: number;
  sent_at: string | null;
  paid_reference: string | null;
  lines: {
    id: string;
    part_id: string | null;
    description: string;
    quantity: number;
    unit_cost_cents: number;
    received_quantity: number;
  }[];
  whatsapp_url?: string;
  message?: string;
}

export interface PortalLease extends LeaseAgreement {
  operator?: string;
  entries?: LeaseEntry[];
  service_history?: { done_on: string; odometer_km: number; notes: string | null }[];
  inspections?: { date: string; status: string }[];
}
