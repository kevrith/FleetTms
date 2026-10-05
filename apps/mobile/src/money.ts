import { kesToCents, normalizeMpesaCode } from "@fleettms/business-rules";

const MAX_FLOAT_CENTS = 100_000_000; // the server's limit: KES 1,000,000

export interface FloatForm {
  driverId: string | null;
  kes: string;
  mpesaCode: string;
  note: string;
}

export type FloatDraft =
  | {
      ok: true;
      input: {
        driver_membership_id: string;
        amount_cents: number;
        mpesa_code: string | null;
        note: string | null;
      };
    }
  | { ok: false; error: string };

/** Checks a float the owner is about to record, with the same rules the server applies, so a typo is caught before it is sent. */
export function floatDraft(form: FloatForm): FloatDraft {
  if (!form.driverId) return { ok: false, error: "Choose who the money went to." };
  const kes = Number(form.kes.replace(/,/g, "").trim());
  if (!Number.isFinite(kes) || kes <= 0) return { ok: false, error: "Enter the amount sent." };
  const cents = kesToCents(kes);
  if (cents > MAX_FLOAT_CENTS) return { ok: false, error: "That is more than KES 1,000,000." };
  let code: string | null = null;
  if (form.mpesaCode.trim()) {
    code = normalizeMpesaCode(form.mpesaCode);
    if (!code) {
      return {
        ok: false,
        error: "An M-Pesa code is 10 letters and numbers, like QGH7XYZ123.",
      };
    }
  }
  return {
    ok: true,
    input: {
      driver_membership_id: form.driverId,
      amount_cents: cents,
      mpesa_code: code,
      note: form.note.trim() || null,
    },
  };
}
