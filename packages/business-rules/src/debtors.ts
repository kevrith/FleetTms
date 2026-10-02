/**
 * Debtors (masterplan 5.10): how late an invoice is, which account reference a payment was made against, and when a
 * reminder is due. Mirrored by apps/api/app/debtor_rules.py and tested against debtor-cases.json on both sides.
 */

export type AgeingBucket = "current" | "1_30" | "31_60" | "61_90" | "over_90";

export const AGEING_BUCKETS: AgeingBucket[] = ["current", "1_30", "31_60", "61_90", "over_90"];

const DAY_MS = 86_400_000;

/** Whole days from one ISO date (YYYY-MM-DD) to another. */
export const daysBetween = (from: string, to: string) =>
  Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / DAY_MS);

/** Ageing counts from the due date: an invoice that is not yet due is "current". */
export function ageingBucket(due: string, today: string): AgeingBucket {
  const late = daysBetween(due, today);
  if (late <= 0) return "current";
  if (late <= 30) return "1_30";
  if (late <= 60) return "31_60";
  if (late <= 90) return "61_90";
  return "over_90";
}

const REFERENCE = /^INV[\s\-_.#:]*0*(\d{1,6})$/i;

/** The invoice number a customer meant by what they typed as the M-Pesa account number, or null if it is not one. */
export function invoiceNumberFrom(text: string | null | undefined): string | null {
  const found = REFERENCE.exec((text ?? "").trim());
  if (!found) return null;
  const n = String(Number(found[1]));
  return `INV-${n.padStart(4, "0")}`;
}

export const DEFAULT_REMINDER_OFFSETS = [-3, 1, 7, 14, 30];

/**
 * Which reminder to send today for an unpaid invoice, as days from the due date (negative is before it), or null.
 * Only the latest one that has come round is sent, so a backlog never means several messages in one day.
 */
export function reminderOffsetDue(input: {
  due: string;
  today: string;
  offsets: number[];
  sent: number[];
}): number | null {
  const late = daysBetween(input.due, input.today);
  const reached = input.offsets.filter((o) => o <= late);
  if (reached.length === 0) return null;
  const latest = Math.max(...reached);
  return input.sent.includes(latest) ? null : latest;
}
