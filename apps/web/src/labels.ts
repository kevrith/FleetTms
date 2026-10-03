import type {
  ComplianceDocType,
  CrewRole,
  FuelType,
  OwnershipType,
  PartyKind,
  TrackingTier,
} from "@fleettms/types";

export const OWNERSHIP: Record<OwnershipType, string> = {
  owned: "Owned",
  asset_financed: "Asset-financed",
  leased_in: "Leased-in",
  leased_out: "Leased-out",
};
export const PARTY_FOR_OWNERSHIP: Record<OwnershipType, PartyKind | null> = {
  owned: null,
  asset_financed: "lender",
  leased_in: "lessor",
  leased_out: "lessee",
};
export const PARTY_KIND: Record<PartyKind, string> = {
  lessor: "Lessor",
  lender: "Lender",
  lessee: "Lessee",
};
export const TIER: Record<TrackingTier, string> = {
  basic: "Basic (phone GPS)",
  standard: "Standard (GPS tracker)",
  premium: "Premium (tracker + fuel sensor)",
};
export const FUEL: Record<FuelType, string> = { diesel: "Diesel", petrol: "Petrol" };
export const CREW: Record<CrewRole, string> = { driver: "Driver", turnboy: "Turnboy" };
export const DOC_TYPE: Record<ComplianceDocType, string> = {
  insurance: "Insurance",
  inspection: "Inspection",
  ntsa_licence: "NTSA licence",
  tlb_licence: "TLB licence",
  permit: "Permit",
  driving_licence: "Driving licence",
  other: "Other",
};
export const VEHICLE_DOC_TYPES: ComplianceDocType[] = [
  "insurance",
  "inspection",
  "ntsa_licence",
  "tlb_licence",
  "permit",
  "other",
];
export const STAFF_DOC_TYPES: ComplianceDocType[] = ["driving_licence", "permit", "other"];

/** Days from today until an ISO date (negative once expired). */
export function daysUntil(iso: string): number {
  const today = new Date();
  const start = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
  const [y = 0, m = 1, d = 1] = iso.split("-").map(Number);
  return Math.round((Date.UTC(y, m - 1, d) - start) / 86_400_000);
}

export const TRIP_STATUS: Record<string, string> = {
  scheduled: "Scheduled",
  in_progress: "In progress",
  delivered: "Delivered",
  completed: "Completed",
  cancelled: "Cancelled",
};
export const INSPECTION_STATUS: Record<string, string> = {
  passed: "Passed",
  passed_with_defects: "Passed with defects",
  blocked: "Blocked: critical fault",
  overridden: "Overridden by manager",
};
export const FLAG_TEXT: Record<string, string> = {
  mismatch: "Typed number differs from the number read from the photo",
  backward: "Lower than the vehicle's last reading",
  large_jump: "Far above the vehicle's last reading",
  no_location: "No GPS location on the photo",
};
export const fmtTime = (iso: string | null) => (iso ? new Date(iso).toLocaleString("en-KE") : "");

export const TRUST: Record<string, string> = { high: "High", medium: "Medium", low: "Low" };
export const DEVICE_FLAG: Record<string, string> = {
  mock_location: "A fake-GPS app was running",
  rooted: "The phone is rooted",
  clock_changed: "The phone's clock was wrong",
  tracker_power_cut: "The tracker lost its power supply",
  tracker_gps_jamming: "The tracker reported GPS jamming",
  tracker_tamper: "The tracker was tampered with",
};
export const FUEL_FLAG: Record<string, string> = {
  amount_mismatch: "Litres times price does not match the amount",
  no_receipt: "No receipt photo",
  statement_amount_differs: "The M-Pesa statement shows a different amount",
  not_on_statement: "This M-Pesa code is not on the statement",
};

export const EXPENSE_CATEGORY: Record<string, string> = {
  toll: "Toll",
  parking: "Parking",
  food: "Food",
  loading: "Loading and offloading",
  police_county: "Police and county fees",
  repair: "Repair",
  tyres: "Tyres",
  insurance: "Insurance",
  licence: "Licence",
  permit: "Permit",
  garage: "Garage fees",
  service: "Service",
  overhead: "Overhead",
  other: "Other",
};
export const EXPENSE_STATUS: Record<string, string> = {
  recorded: "Counted",
  awaiting_approval: "Waiting for owner",
  approved: "Approved",
  rejected: "Rejected",
};
export const EXPENSE_FLAG: Record<string, string> = {
  over_limit: "Over the spend limit",
  unusual_for_route: "Unusual for this route",
  statement_amount_differs: "The M-Pesa statement shows a different amount",
  not_on_statement: "This M-Pesa code is not on the statement",
  no_receipt: "No receipt or M-Pesa code",
};
export const PRIORITY: Record<string, string> = {
  urgent: "Urgent",
  high: "High",
  normal: "Normal",
  low: "Low",
};
export const WO_STATUS: Record<string, string> = {
  open: "Open",
  in_progress: "In progress",
  waiting_parts: "Waiting for parts",
  done: "Done",
  cancelled: "Cancelled",
};
export const DUE_STATUS: Record<string, string> = {
  ok: "On track",
  due_soon: "Due soon",
  overdue: "Overdue",
  inactive: "Not in use",
};
export const RECON_STATUS: Record<string, string> = {
  open: "Not submitted",
  submitted: "Waiting for approval",
  approved: "Approved",
  rejected: "Sent back",
};
export const ROLE_NAMES: Record<string, string> = {
  driver: "Driver",
  turnboy: "Turnboy",
  supervisor: "Supervisor",
  manager: "Manager",
  accountant: "Accountant",
  workshop: "Workshop",
};
export const kes = (cents: number) =>
  `KES ${(cents / 100).toLocaleString("en-KE", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
export const todayIso = () =>
  new Date().toLocaleDateString("en-CA", { timeZone: "Africa/Nairobi" });

export const TYRE_STATUS: Record<string, string> = {
  in_store: "In the store",
  fitted: "On a vehicle",
  removed: "Taken off",
  scrapped: "Scrapped",
};
export const TYRE_REASON: Record<string, string> = {
  mismatch: "A tyre of this vehicle, but at a different position",
  unknown: "A serial that is not recorded anywhere",
  elsewhere: "A tyre recorded in the store or on another vehicle",
};
export const INCIDENT_TYPE: Record<string, string> = {
  breakdown: "Breakdown",
  accident: "Accident",
  police_stop: "Police stop",
  traffic_fine: "Traffic fine",
  county_cess: "County cess",
  cargo_theft: "Cargo theft",
};
export const CLAIM_STATUS: Record<string, string> = {
  filed: "Filed",
  documents_requested: "Documents requested",
  assessed: "Assessed",
  approved: "Approved",
  paid: "Paid",
  rejected: "Rejected",
};
export { positionLabel } from "@fleettms/business-rules";

export const BILLING_METHOD: Record<string, string> = {
  per_trip: "Per trip",
  per_tonne: "Per tonne",
  per_km: "Per kilometre",
  monthly_contract: "Monthly contract",
};
export const BILLING_RATE_LABEL: Record<string, string> = {
  per_trip: "Amount per trip (KES)",
  per_tonne: "Rate per tonne (KES)",
  per_km: "Rate per km (KES)",
  monthly_contract: "Monthly fee (KES)",
};
export const QUOTE_STATUS: Record<string, string> = {
  draft: "Draft",
  sent: "Sent",
  accepted: "Accepted",
  declined: "Declined",
};
export const JOB_STATUS: Record<string, string> = {
  planned: "Needs a lorry",
  dispatched: "Dispatched",
  in_progress: "On the road",
  completed: "Completed",
  cancelled: "Cancelled",
};
/** Shows a moment in Nairobi time. */
export const nairobiTime = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleString("en-KE", {
        timeZone: "Africa/Nairobi",
        weekday: "short",
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "";

export const POD_FLAG: Record<string, string> = {
  outside_site: "Delivered away from the client's site",
  no_location: "No GPS location was recorded",
  shortage: "A shortage was reported",
  damage: "Damage was reported",
};
export const INVOICE_STATUS: Record<string, string> = {
  issued: "Unpaid",
  partially_paid: "Part paid",
  paid: "Paid",
  void: "Void",
};

export const AGEING: Record<string, string> = {
  current: "Not yet due",
  "1_30": "1 to 30 days late",
  "31_60": "31 to 60 days late",
  "61_90": "61 to 90 days late",
  over_90: "Over 90 days late",
};
export const MPESA_STATUS: Record<string, string> = {
  matched: "Matched",
  partly_matched: "Part matched",
  unmatched: "Waiting for a match",
  dismissed: "Set aside",
};
export const ETIMS_STATUS: Record<string, string> = {
  pending: "Waiting to send",
  submitted: "Sent to KRA",
  needs_review: "Needs a person",
  resolved: "Handled by hand",
};
export const STATEMENT_STATE: Record<string, string> = {
  matched: "Matched",
  amount_differs: "Amount differs",
  unmatched: "Not matched",
  ignored: "Looked at, fine",
};
/** "3 days before the due date", "1 day after". */
export function reminderStep(offset: number): string {
  const n = Math.abs(offset);
  const days = `${n} day${n === 1 ? "" : "s"}`;
  return offset < 0
    ? `${days} before the due date`
    : offset === 0
      ? "On the due date"
      : `${days} after`;
}

export const ALERT_KIND: Record<string, string> = {
  power_cut: "Tracker lost power",
  gps_jamming: "GPS jamming",
  tamper: "Tracker tampered with",
  low_battery: "Tracker battery low",
  device_offline: "Tracker not reporting",
  geofence: "Mapped area",
};
export const ALERT_STATUS: Record<string, string> = {
  open: "Open",
  explained: "Explained",
  confirmed: "Confirmed as real",
  resolved: "Resolved",
};
export const BEHAVIOUR_KIND: Record<string, string> = {
  speeding: "Speeding",
  harsh_braking: "Harsh braking",
  harsh_acceleration: "Harsh acceleration",
  harsh_cornering: "Sharp cornering",
  idling: "Idling",
  night_driving: "Night driving",
  long_driving: "Long driving without rest",
};
export const GEOFENCE_KIND: Record<string, string> = {
  depot: "Depot",
  client_site: "Client site",
  fuel_station: "Fuel station",
  restricted: "Restricted (must not enter)",
};
export const GEOFENCE_COLOUR: Record<string, string> = {
  depot: "#2563eb",
  client_site: "#16a34a",
  fuel_station: "#d97706",
  restricted: "#dc2626",
};
export const IMMOBILISER_STATUS: Record<string, string> = {
  awaiting_confirmation: "Waiting for confirmation",
  sent: "Sent to the tracker",
  acknowledged: "Tracker confirmed",
  failed: "Could not be sent",
  refused: "Refused for safety",
  cancelled: "Cancelled",
  expired: "Expired",
};
export const ONLINE_STATE: Record<string, string> = {
  online: "Reporting",
  offline: "Not reporting",
  unknown: "Never heard from",
};
/** How long ago, in plain words, from a number of seconds. */
export function quietFor(seconds: number | null): string {
  if (seconds === null) return "never";
  if (seconds < 90) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} days ago`;
}
