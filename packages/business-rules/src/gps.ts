/**
 * Phone GPS rules (masterplan 5.3): which fixes to trust, how far a trip really went, what state a lorry is in, and whether
 * the odometer and the GPS agree. Mirrored by apps/api/app/gps_rules.py and tested against gps-cases.json on both sides.
 */

const EARTH_KM = 6371;
export const MAX_ACCURACY_M = 100;
export const MAX_SPEED_KMH = 200;
export const MIN_STEP_M = 15;
export const FRESH_SECONDS = 5 * 60;
export const MOVING_KMH = 5;
export const DEFAULT_SPEED_KMH = 40;
export const MIN_POINTS_FOR_CHECK = 3;
const TOLERANCE_PCT = 15;
const TOLERANCE_KM = 10;

const rad = (d: number) => (d * Math.PI) / 180;

export function haversineKm(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const p1 = rad(lat1);
  const p2 = rad(lat2);
  const a =
    Math.sin((p2 - p1) / 2) ** 2 +
    Math.cos(p1) * Math.cos(p2) * Math.sin(rad(lng2 - lng1) / 2) ** 2;
  return 2 * EARTH_KM * Math.asin(Math.min(1, Math.sqrt(a)));
}

/** A fix the phone should keep: on the globe, and not too vague to trust. */
export function goodFix(lat: number, lng: number, accuracyM: number | null | undefined): boolean {
  return (
    lat >= -90 &&
    lat <= 90 &&
    lng >= -180 &&
    lng <= 180 &&
    (accuracyM == null || accuracyM <= MAX_ACCURACY_M)
  );
}

export interface TrackPoint {
  /** ISO time. */
  at: string;
  lat: number;
  lng: number;
  accuracy_m?: number | null;
}

/** Kilometres driven and fixes used. Poor fixes are dropped, a step implying over 200 km/h is a jump, steps under 15 m are jitter. */
export function pathDistanceKm(points: TrackPoint[]): { km: number; used: number } {
  const kept = points
    .filter((p) => goodFix(p.lat, p.lng, p.accuracy_m))
    .sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
  let total = 0;
  let last: TrackPoint | null = null;
  for (const p of kept) {
    if (last === null) {
      last = p;
      continue;
    }
    const step = haversineKm(last.lat, last.lng, p.lat, p.lng);
    if (step * 1000 < MIN_STEP_M) continue;
    const hours = (Date.parse(p.at) - Date.parse(last.at)) / 3_600_000;
    if (hours > 0 && step / hours <= MAX_SPEED_KMH) total += step;
    last = p;
  }
  return { km: Math.round(total * 1000) / 1000, used: kept.length };
}

export type VehicleState = "moving" | "idle" | "offline" | "parked" | "unknown";

/** moving, idle (on a trip but standing), offline (on a trip but not reporting), parked (no trip), or unknown (never seen). */
export function vehicleState(input: {
  on_trip: boolean;
  last_at: string | null;
  now: string;
  speed_kmh: number | null;
}): VehicleState {
  if (input.last_at === null) return "unknown";
  if (!input.on_trip) return "parked";
  if ((Date.parse(input.now) - Date.parse(input.last_at)) / 1000 > FRESH_SECONDS) return "offline";
  return (input.speed_kmh ?? 0) >= MOVING_KMH ? "moving" : "idle";
}

export type DistanceCheck = "ok" | "mismatch" | "no_gps";

/** Does the odometer agree with the phone's GPS? They may differ by 15 percent or 10 km, whichever is more. */
export function distanceCheck(
  odometerKm: number | null,
  gpsKm: number | null,
  points: number,
): DistanceCheck {
  if (gpsKm === null || points < MIN_POINTS_FOR_CHECK || odometerKm === null) return "no_gps";
  return Math.abs(odometerKm - gpsKm) >
    Math.max(TOLERANCE_KM, (TOLERANCE_PCT / 100) * Math.max(odometerKm, gpsKm))
    ? "mismatch"
    : "ok";
}

/** Minutes to go, rounded up to 5, from the speed the lorry has been making (moving speeds only), else 40 km/h. */
export function etaMinutes(remainingKm: number, recentSpeedsKmh: number[]): number | null {
  if (remainingKm < 0) return null;
  const moving = recentSpeedsKmh.filter((s) => s >= 10);
  const speed = moving.length
    ? moving.reduce((a, b) => a + b, 0) / moving.length
    : DEFAULT_SPEED_KMH;
  return Math.ceil(((remainingKm / speed) * 60) / 5) * 5;
}

export interface ThreeWay {
  check: DistanceCheck;
  /** The one source that disagrees with both of the others, when those two agree. */
  suspect: "odometer" | "phone" | "tracker" | null;
  sources: Partial<Record<"odometer" | "phone" | "tracker", number>>;
}

const agree = (a: number, b: number) =>
  Math.abs(a - b) <= Math.max(TOLERANCE_KM, (TOLERANCE_PCT / 100) * Math.max(a, b));

/** Compares the odometer, the phone's GPS and the tracker. Fixes too few to trust leave a source out. */
export function threeWay(input: {
  odometer_km: number | null;
  phone_km: number | null;
  phone_points: number;
  tracker_km: number | null;
  tracker_points: number;
}): ThreeWay {
  const sources: ThreeWay["sources"] = {};
  if (input.odometer_km !== null) sources.odometer = input.odometer_km;
  if (input.phone_km !== null && input.phone_points >= MIN_POINTS_FOR_CHECK)
    sources.phone = input.phone_km;
  if (input.tracker_km !== null && input.tracker_points >= MIN_POINTS_FOR_CHECK)
    sources.tracker = input.tracker_km;
  const names = Object.keys(sources) as ("odometer" | "phone" | "tracker")[];
  if (names.length < 2) return { check: "no_gps", suspect: null, sources };
  const pairs = names.flatMap((a, i) => names.slice(i + 1).map((b) => [a, b] as const));
  if (pairs.every(([a, b]) => agree(sources[a]!, sources[b]!)))
    return { check: "ok", suspect: null, sources };
  let suspect: ThreeWay["suspect"] = null;
  if (names.length === 3) {
    for (const name of names) {
      const [x, y] = names.filter((n) => n !== name) as [
        (typeof names)[number],
        (typeof names)[number],
      ];
      if (
        agree(sources[x]!, sources[y]!) &&
        !agree(sources[name]!, sources[x]!) &&
        !agree(sources[name]!, sources[y]!)
      )
        suspect = name;
    }
  }
  return { check: "mismatch", suspect, sources };
}
