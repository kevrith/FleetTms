import { describe, expect, it } from "vitest";
import { fuelFlags, normalizeMpesaCode } from "./fuel";
import { inspectionClearsTrip, inspectionOutcome, nairobiDay } from "./trips";

describe("inspectionOutcome", () => {
  it("passes when everything is fine", () =>
    expect(inspectionOutcome([{ ok: true, critical: true }])).toBe("passed"));
  it("passes with defects when only minor items fail", () =>
    expect(
      inspectionOutcome([
        { ok: true, critical: true },
        { ok: false, critical: false },
      ]),
    ).toBe("passed_with_defects"));
  it("blocks when a critical item fails", () =>
    expect(inspectionOutcome([{ ok: false, critical: true }])).toBe("blocked"));
});

describe("inspectionClearsTrip", () => {
  it("clears passed, defects and overridden, not blocked or missing", () => {
    expect(inspectionClearsTrip("passed")).toBe(true);
    expect(inspectionClearsTrip("passed_with_defects")).toBe(true);
    expect(inspectionClearsTrip("overridden")).toBe(true);
    expect(inspectionClearsTrip("blocked")).toBe(false);
    expect(inspectionClearsTrip(null)).toBe(false);
  });
});

describe("nairobiDay", () => {
  it("uses the Nairobi day, which is ahead of UTC by three hours", () => {
    expect(nairobiDay("2026-10-02T20:59:59Z")).toBe("2026-10-02");
    expect(nairobiDay("2026-10-02T21:00:00Z")).toBe("2026-10-03");
    expect(nairobiDay("2026-10-02T00:30:00Z")).toBe("2026-10-02");
  });
});

describe("fuel rules", () => {
  it("accepts an amount that matches litres times price", () =>
    expect(
      fuelFlags({ litres: 120, priceCents: 18500, amountCents: 2220000, hasReceipt: true }),
    ).toEqual([]));
  it("allows a rounding difference of about one percent", () =>
    expect(
      fuelFlags({ litres: 120, priceCents: 18500, amountCents: 2230000, hasReceipt: true }),
    ).toEqual([]));
  it("flags an amount that does not match, and a missing receipt", () =>
    expect(
      fuelFlags({ litres: 120, priceCents: 18500, amountCents: 3000000, hasReceipt: false }),
    ).toEqual(["amount_mismatch", "no_receipt"]));
  it("tidies M-Pesa codes and rejects bad ones", () => {
    expect(normalizeMpesaCode(" qgh7xyz123 ")).toBe("QGH7XYZ123");
    expect(normalizeMpesaCode("12345")).toBeNull();
  });
});
