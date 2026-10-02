/** Rules the phone applies while offline. The server applies the same rules again when the queue syncs. */

export type InspectionOutcome = "passed" | "passed_with_defects" | "blocked" | "overridden";

/** What an inspection amounts to: any failed critical item blocks the trip. */
export function inspectionOutcome(
  answers: { ok: boolean; critical: boolean }[],
): InspectionOutcome {
  if (answers.some((a) => !a.ok && a.critical)) return "blocked";
  if (answers.some((a) => !a.ok)) return "passed_with_defects";
  return "passed";
}

/** An inspection clears a trip unless it is blocked and nobody has overridden it. */
export function inspectionClearsTrip(outcome: InspectionOutcome | null | undefined): boolean {
  return outcome != null && outcome !== "blocked";
}

const NAIROBI_OFFSET_MS = 3 * 60 * 60 * 1000; // Kenya is UTC+3 all year

/** The Africa/Nairobi calendar day (YYYY-MM-DD) of a moment. An inspection counts for the day it was done. */
export function nairobiDay(iso: string | number | Date): string {
  return new Date(new Date(iso).getTime() + NAIROBI_OFFSET_MS).toISOString().slice(0, 10);
}
