import { describe, expect, it } from "vitest";
import { floatDraft } from "./money";

const form = { driverId: "m1", kes: "3,000", mpesaCode: "", note: "" };

describe("floatDraft", () => {
  it("turns what the owner typed into what the server wants", () => {
    expect(floatDraft({ ...form, mpesaCode: " qgh7xyz123 ", note: " Fuel " })).toEqual({
      ok: true,
      input: {
        driver_membership_id: "m1",
        amount_cents: 300000,
        mpesa_code: "QGH7XYZ123",
        note: "Fuel",
      },
    });
  });

  it("does not need an M-Pesa code or a note", () => {
    const draft = floatDraft(form);
    expect(draft.ok && draft.input.mpesa_code).toBeNull();
    expect(draft.ok && draft.input.note).toBeNull();
  });

  it("refuses a missing recipient, a bad amount and a bad code", () => {
    expect(floatDraft({ ...form, driverId: null }).ok).toBe(false);
    for (const kes of ["", "0", "-5", "abc"]) expect(floatDraft({ ...form, kes }).ok).toBe(false);
    expect(floatDraft({ ...form, kes: "1000001" }).ok).toBe(false);
    expect(floatDraft({ ...form, mpesaCode: "SHORT" }).ok).toBe(false);
  });

  it("accepts the largest amount the server allows", () => {
    expect(floatDraft({ ...form, kes: "1000000" }).ok).toBe(true);
  });
});
