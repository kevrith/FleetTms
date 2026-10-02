/** Odometer rules (masterplan 5.4). The API enforces these too; clients use them to catch mistakes early. */

export const MAX_ODOMETER_KM = 9_999_999;
/** More than this since the last known reading is suspicious for one trip. */
export const LARGE_JUMP_KM = 3_000;

export type OdometerFlag = "mismatch" | "backward" | "large_jump" | "no_location";

/** Parses what a person typed. Returns null if it is not a whole number of kilometres in range. */
export function parseOdometer(text: string): number | null {
  const cleaned = text.replace(/[\s,]/g, "");
  if (!/^\d+$/.test(cleaned)) return null;
  const value = Number(cleaned);
  return value <= MAX_ODOMETER_KM ? value : null;
}

/** Reasons a reading deserves a second look. Flags never block a trip. */
export function readingFlags(input: {
  confirmed: number;
  autoRead?: number | null;
  lastKnownKm: number;
  hasLocation: boolean;
}): OdometerFlag[] {
  const flags: OdometerFlag[] = [];
  if (input.autoRead != null && input.autoRead !== input.confirmed) flags.push("mismatch");
  if (input.confirmed < input.lastKnownKm) flags.push("backward");
  else if (input.confirmed - input.lastKnownKm > LARGE_JUMP_KM) flags.push("large_jump");
  if (!input.hasLocation) flags.push("no_location");
  return flags;
}

/** Trip distance from the two readings, or null when the end is below the start. */
export function tripDistanceKm(start: number, end: number): number | null {
  return end >= start ? end - start : null;
}

/** The lowest reading that can be accepted: an odometer never goes backwards. */
export function minimumReading(lastKnownKm: number, tripStartKm?: number): number {
  return Math.max(lastKnownKm, tripStartKm ?? 0);
}

/** True when what was typed is a number below the lowest acceptable reading, which the server refuses. */
export function isBelowMinimum(typed: string, minimumKm: number): boolean {
  const value = parseOdometer(typed);
  return value !== null && value < minimumKm;
}

/** A message for the person about to submit, or null when the number is fine. */
export function odometerProblem(
  typed: string,
  lastKnownKm: number,
  minimumKm?: number,
): string | null {
  const value = parseOdometer(typed);
  if (value === null) return "Enter the odometer as a whole number of kilometres.";
  if (minimumKm !== undefined && value < minimumKm)
    return "The end reading cannot be lower than the start reading.";
  if (value < lastKnownKm)
    return `That is lower than the last reading for this vehicle (${lastKnownKm.toLocaleString("en-KE")} km). A lower reading cannot be accepted. Check the number.`;
  if (value - lastKnownKm > LARGE_JUMP_KM)
    return "That is a long way above the last reading. Check the number.";
  return null;
}
