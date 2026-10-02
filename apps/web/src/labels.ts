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
