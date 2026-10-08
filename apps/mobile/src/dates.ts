/**
 * A date as a person types it, turned into 2026-12-31. Accepts 31/12/2026, 31-12-2026, 31.12.2026, 31/12/26 and 2026-12-31. Returns null
 * for anything that is not a real calendar date, so a typo is caught before it is sent (31/02/2026 is not accepted).
 */
export function parseDateInput(text: string): string | null {
  const t = text.trim();
  let year: number, month: number, day: number;
  const iso = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(t);
  const local = /^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2}|\d{4})$/.exec(t);
  if (iso) {
    [year, month, day] = [Number(iso[1]), Number(iso[2]), Number(iso[3])];
  } else if (local) {
    [day, month] = [Number(local[1]), Number(local[2])];
    year = local[3]!.length === 2 ? 2000 + Number(local[3]) : Number(local[3]);
  } else {
    return null;
  }
  const real = new Date(Date.UTC(year, month - 1, day));
  if (
    real.getUTCFullYear() !== year ||
    real.getUTCMonth() !== month - 1 ||
    real.getUTCDate() !== day
  ) {
    return null;
  }
  return `${String(year).padStart(4, "0")}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

/** "In 23 days", "Expired 3 days ago", "Expires today" for a count of days until a date (negative once past). */
export function daysPhrase(daysLeft: number): string {
  if (daysLeft === 0) return "Expires today";
  const n = Math.abs(daysLeft);
  const unit = `${n} day${n === 1 ? "" : "s"}`;
  return daysLeft < 0 ? `Expired ${unit} ago` : `In ${unit}`;
}
