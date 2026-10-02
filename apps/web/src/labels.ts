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
