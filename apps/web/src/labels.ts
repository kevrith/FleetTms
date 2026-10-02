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
};
export const FUEL_FLAG: Record<string, string> = {
  amount_mismatch: "Litres times price does not match the amount",
  no_receipt: "No receipt photo",
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
