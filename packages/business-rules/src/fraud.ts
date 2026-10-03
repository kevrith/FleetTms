/**
 * Fraud and anomaly rules (masterplan 5.13): what counts as too much fuel, a side trip, a stop nobody can explain, too much idling.
 * Mirrored by apps/api/app/fraud_rules.py and tested against fraud-cases.json on both sides.
 */
import { insideShape, type Shape } from "./geofence";
import { haversineKm } from "./gps";

export interface FraudThresholds {
  fuel_variance_pct: number;
  idle_litres_per_hour: number;
  min_baseline_trips: number;
  min_fuel_km: number;
  long_stop_minutes: number;
  stop_radius_m: number;
  side_trip_pct: number;
  side_trip_min_km: number;
  tamper_window_hours: number;
  excess_idle_pct: number;
  excess_idle_minutes: number;
}

export const DEFAULT_FRAUD_THRESHOLDS: FraudThresholds = {
  fuel_variance_pct: 10,
  idle_litres_per_hour: 3.0,
  min_baseline_trips: 3,
  min_fuel_km: 30,
  long_stop_minutes: 45,
  stop_radius_m: 100,
  side_trip_pct: 25,
  side_trip_min_km: 15,
  tamper_window_hours: 6,
  excess_idle_pct: 20,
  excess_idle_minutes: 60,
};

/** What a business may set each threshold to. */
export const FRAUD_LIMITS: Record<keyof FraudThresholds, [number, number]> = {
  fuel_variance_pct: [3, 50],
  idle_litres_per_hour: [0, 10],
  min_baseline_trips: [1, 20],
  min_fuel_km: [5, 500],
  long_stop_minutes: [10, 480],
  stop_radius_m: [30, 500],
  side_trip_pct: [5, 200],
  side_trip_min_km: [1, 500],
  tamper_window_hours: [1, 48],
  excess_idle_pct: [5, 90],
  excess_idle_minutes: [10, 600],
};

const WHOLE: (keyof FraudThresholds)[] = [
  "min_baseline_trips",
  "long_stop_minutes",
  "excess_idle_minutes",
];
const MOVING_KMH = 5;
const MINUTE = 60_000;
const HOUR = 3_600_000;

/** The defaults with a business's own values on top. Unknown names and values outside the allowed range are ignored. */
export function fraudThresholds(overrides: Record<string, unknown> | null): FraudThresholds {
  const out = { ...DEFAULT_FRAUD_THRESHOLDS };
  for (const key of Object.keys(out) as (keyof FraudThresholds)[]) {
    const raw = overrides?.[key];
    const [low, high] = FRAUD_LIMITS[key];
    if (typeof raw === "number" && raw >= low && raw <= high) {
      out[key] = WHOLE.includes(key) ? Math.trunc(raw) : raw;
    }
  }
  return out;
}

/** Loads in five-tonne steps, so a trip is compared with trips carrying about the same. */
export function loadBand(kg: number | null | undefined): string {
  if (kg == null || kg < 500) return "empty";
  return `${Math.floor(kg / 5000) * 5}t`;
}

export const routeKey = (origin: string | null, destination: string | null) =>
  `${(origin ?? "").trim().toLowerCase()}|${(destination ?? "").trim().toLowerCase()}`;

function median(values: number[]): number {
  const v = [...values].sort((a, b) => a - b);
  const mid = Math.floor(v.length / 2);
  return v.length % 2 ? v[mid]! : (v[mid - 1]! + v[mid]!) / 2;
}

const round = (x: number, places: number) => {
  const f = 10 ** places;
  return Math.round(x * f) / f;
};

export interface FuelSample {
  litres: number;
  km: number;
  idle_hours?: number;
}

/** A vehicle's normal litres per kilometre from its earlier trips, with what idling used taken out. Null until there are enough trips. */
export function fuelBaseline(
  samples: FuelSample[],
  t: FraudThresholds = DEFAULT_FRAUD_THRESHOLDS,
): { l_per_km: number; trips: number } | null {
  const rates: number[] = [];
  for (const s of samples) {
    if (s.km >= t.min_fuel_km && s.litres > 0) {
      const net = Math.max(s.litres - (s.idle_hours ?? 0) * t.idle_litres_per_hour, 0);
      if (net > 0) rates.push(net / s.km);
    }
  }
  if (rates.length < t.min_baseline_trips) return null;
  return { l_per_km: round(median(rates), 4), trips: rates.length };
}

export interface FuelVerdict {
  flagged: boolean;
  expected_litres: number | null;
  variance_pct: number | null;
  severity: "red" | "amber" | null;
}

/** Fuel bought for a trip against what the distance and the idling explain. */
export function fuelCheck(
  input: { litres: number; km: number; idle_hours: number; l_per_km: number },
  t: FraudThresholds = DEFAULT_FRAUD_THRESHOLDS,
): FuelVerdict {
  if (input.km < t.min_fuel_km || input.l_per_km <= 0) {
    return { flagged: false, expected_litres: null, variance_pct: null, severity: null };
  }
  const expected = input.l_per_km * input.km + input.idle_hours * t.idle_litres_per_hour;
  const variance = ((input.litres - expected) / expected) * 100;
  const flagged = variance > t.fuel_variance_pct;
  return {
    flagged,
    expected_litres: round(expected, 1),
    variance_pct: round(variance, 1),
    severity: flagged ? (variance > 2 * t.fuel_variance_pct ? "red" : "amber") : null,
  };
}

/** Driving much further than the route (or than this route usually takes) means somewhere else was visited on the way. */
export function sideTripCheck(
  input: { gps_km: number; expected_km: number },
  t: FraudThresholds = DEFAULT_FRAUD_THRESHOLDS,
): { flagged: boolean; extra_km: number; over_pct: number | null } {
  const extra = input.gps_km - input.expected_km;
  const flagged =
    input.expected_km > 0 &&
    input.gps_km > input.expected_km * (1 + t.side_trip_pct / 100) &&
    extra >= t.side_trip_min_km;
  return {
    flagged,
    extra_km: round(extra, 1),
    over_pct: input.expected_km > 0 ? round((extra / input.expected_km) * 100, 1) : null,
  };
}

export interface StopFix {
  at: string;
  lat: number;
  lng: number;
  speed: number | null;
}

export interface Stop {
  start: string;
  end: string;
  minutes: number;
  lat: number;
  lng: number;
}

/** Where a vehicle stood still for a while: a run of fixes that stay within the stop radius of where it began and are not moving fast. */
export function findStops(fixes: StopFix[], t: FraudThresholds = DEFAULT_FRAUD_THRESHOLDS): Stop[] {
  const stops: Stop[] = [];
  let run: StopFix[] = [];
  const close = () => {
    if (run.length >= 2) {
      const first = run[0]!;
      const last = run[run.length - 1]!;
      stops.push({
        start: first.at,
        end: last.at,
        minutes: round((Date.parse(last.at) - Date.parse(first.at)) / MINUTE, 1),
        lat: first.lat,
        lng: first.lng,
      });
    }
  };
  for (const f of fixes) {
    const still = f.speed == null || f.speed < MOVING_KMH;
    const first = run[0];
    if (
      first &&
      still &&
      haversineKm(first.lat, first.lng, f.lat, f.lng) * 1000 <= t.stop_radius_m
    ) {
      run.push(f);
      continue;
    }
    close();
    run = still ? [f] : [];
  }
  close();
  return stops;
}

/** Null when a stop needs no explaining (short, or at a known place), otherwise "unexplained". */
export function explainStop(
  stop: { minutes: number; lat: number; lng: number },
  places: Shape[],
  t: FraudThresholds = DEFAULT_FRAUD_THRESHOLDS,
): "unexplained" | null {
  if (stop.minutes < t.long_stop_minutes) return null;
  if (places.some((p) => insideShape(p, stop.lat, stop.lng))) return null;
  return "unexplained";
}

/** The latest tracker tamper within the window before a stop began (or just after), if any. Times are ISO strings. */
export function tamperBefore(
  stopStart: string,
  tampers: string[],
  t: FraudThresholds = DEFAULT_FRAUD_THRESHOLDS,
): string | null {
  const start = Date.parse(stopStart);
  const near = tampers
    .map((x) => Date.parse(x))
    .filter((x) => x >= start - t.tamper_window_hours * HOUR && x <= start + 30 * MINUTE);
  return near.length ? new Date(Math.max(...near)).toISOString() : null;
}

export function idleCheck(
  input: { idle_minutes: number; trip_minutes: number },
  t: FraudThresholds = DEFAULT_FRAUD_THRESHOLDS,
): { flagged: boolean; share_pct: number } {
  const share = input.trip_minutes > 0 ? (input.idle_minutes / input.trip_minutes) * 100 : 0;
  return {
    flagged: input.idle_minutes >= t.excess_idle_minutes && share >= t.excess_idle_pct,
    share_pct: round(share, 1),
  };
}

/** What a failed three-way distance check means: red when the odometer is the odd one out, amber when nobody can say which is wrong. */
export function odometerFinding(
  check: string | null,
  detail: { suspect?: string | null } | null,
): { flagged: boolean; severity: "red" | "amber" | null; suspect: string | null } {
  if (check !== "mismatch") return { flagged: false, severity: null, suspect: null };
  const suspect = detail?.suspect ?? null;
  return { flagged: true, severity: suspect === "odometer" ? "red" : "amber", suspect };
}
