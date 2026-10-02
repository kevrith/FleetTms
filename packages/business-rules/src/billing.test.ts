import { describe, expect, it } from "vitest";
import { invoiceStanding, invoiceTotals, tripAmount, type TripBillingInput } from "./billing";
import cases from "./billing-cases.json";

describe("tripAmount", () => {
  for (const c of cases.trip_amounts) {
    it(c.name, () => {
      expect(tripAmount(c.input as TripBillingInput)).toBe(c.expected);
    });
  }
});

describe("invoiceTotals", () => {
  for (const c of cases.totals) {
    it(c.name, () => {
      expect(invoiceTotals(c.lines, c.vat_pct)).toEqual(c.expected);
    });
  }
});

describe("invoiceStanding", () => {
  for (const c of cases.payments) {
    it(c.name, () => {
      expect(
        invoiceStanding({ total_cents: c.total_cents, paid: c.paid, voided: c.voided, due: c.due, today: c.today }),
      ).toEqual(c.expected);
    });
  }
});
