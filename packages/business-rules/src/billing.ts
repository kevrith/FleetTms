/**
 * Billing (masterplan 5.10): what a delivered trip is worth, VAT, invoice totals and where an invoice stands. Money is
 * always whole cents. Mirrored by apps/api/app/billing_rules.py and tested against billing-cases.json on both sides.
 */

import type { BillingMethod } from "./quotes";

const half = (x: number) => Math.floor(x + 0.5);

export interface TripBillingInput {
  method: BillingMethod;
  /** Per trip, per tonne or per km, in cents. */
  rate_cents: number;
  /** Net weight from the weighbridge ticket. */
  weight_kg: number | null;
  /** Loaded distance. */
  distance_km: number | null;
}

/**
 * What one delivered trip is billed at, or null when it cannot be billed yet: a per-tonne trip with no weighbridge weight,
 * a per-km trip with no distance, or a monthly contract (billed once a month, not per trip).
 */
export function tripAmount(input: TripBillingInput): number | null {
  switch (input.method) {
    case "per_trip":
      return input.rate_cents;
    case "per_tonne":
      return input.weight_kg && input.weight_kg > 0 ? half((input.rate_cents * input.weight_kg) / 1000) : null;
    case "per_km":
      return input.distance_km !== null ? half(input.rate_cents * input.distance_km) : null;
    case "monthly_contract":
      return null;
  }
}

export const vatCents = (subtotal_cents: number, vat_pct: number) => half((subtotal_cents * vat_pct) / 100);

export function invoiceTotals(lines_cents: number[], vat_pct: number) {
  const subtotal_cents = lines_cents.reduce((a, b) => a + b, 0);
  const vat_cents = vatCents(subtotal_cents, vat_pct);
  return { subtotal_cents, vat_cents, total_cents: subtotal_cents + vat_cents };
}

export type InvoiceStatus = "issued" | "partially_paid" | "paid" | "void";

/** Where an invoice stands. `due` and `today` are ISO dates (YYYY-MM-DD). */
export function invoiceStanding(input: {
  total_cents: number;
  paid: number[];
  voided: boolean;
  due: string;
  today: string;
}) {
  const paid_cents = input.paid.reduce((a, b) => a + b, 0);
  if (input.voided) return { paid_cents, balance_cents: 0, status: "void" as InvoiceStatus, overdue: false };
  const balance_cents = input.total_cents - paid_cents;
  const status: InvoiceStatus = balance_cents <= 0 ? "paid" : paid_cents > 0 ? "partially_paid" : "issued";
  return { paid_cents, balance_cents, status, overdue: balance_cents > 0 && input.due < input.today };
}
