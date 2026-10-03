/**
 * Fuel level sensors (masterplan 5.3, 5.13): finding refills and parked drops in a tank's level over time, and matching refills with
 * the fuel that was paid for. Mirrored by apps/api/app/fuel_sensor_rules.py and tested against fuelsensor-cases.json on both sides.
 * A drop while the lorry is moving is fuel sloshing and burning, not a theft, so only a parked drop counts.
 */
import { DEFAULT_FRAUD_THRESHOLDS, type FraudThresholds } from "./fraud";

const NOISE_L = 1.0;
const SETTLE_MIN = 10;
const DROP_WINDOW_MIN = 60;
const SENSOR_MOVING_KMH = 5;
const MIN_GAP_L = 10;
const MATCH_WINDOW_MIN = 180;
const MINUTE = 60_000;

export interface FuelReading {
  at: string;
  litres: number;
  speed: number | null;
  lat?: number | null;
  lng?: number | null;
}

export interface FuelEvent {
  kind: "refill" | "drop";
  litres: number;
  before: number;
  after: number;
  start: string;
  end: string;
  lat: number | null;
  lng: number | null;
}

const round1 = (x: number) => Math.round(x * 10) / 10;

/** Each level replaced by the middle of it and its two neighbours, which removes a single wild reading. */
function smooth(readings: FuelReading[]): number[] {
  const levels = readings.map((r) => r.litres);
  if (levels.length < 3) return levels;
  const out = [levels[0]!];
  for (let i = 1; i < levels.length - 1; i++) {
    out.push([levels[i - 1]!, levels[i]!, levels[i + 1]!].sort((a, b) => a - b)[1]!);
  }
  out.push(levels[levels.length - 1]!);
  return out;
}

interface Run {
  start: number;
  end: number;
  sign: 1 | -1;
  total: number;
  changed: number;
}

/** Refills and parked drops. Readings are oldest first. */
export function findFuelEvents(
  readings: FuelReading[],
  t: FraudThresholds = DEFAULT_FRAUD_THRESHOLDS,
): FuelEvent[] {
  if (readings.length < 2) return [];
  const level = smooth(readings);
  const events: FuelEvent[] = [];
  let run: Run | null = null;

  const close = () => {
    if (!run) return;
    const first = readings[run.start]!;
    const last = readings[run.end]!;
    const litres = Math.abs(run.total);
    const parked = readings
      .slice(run.start, run.end + 1)
      .every((r) => r.speed == null || r.speed < SENSOR_MOVING_KMH);
    const minutes = (Date.parse(last.at) - Date.parse(first.at)) / MINUTE;
    const kind = run.sign > 0 ? "refill" : "drop";
    const wanted = kind === "refill" ? t.fuel_refill_litres : t.fuel_drop_litres;
    if (parked && litres >= wanted && (kind === "refill" || minutes <= DROP_WINDOW_MIN)) {
      events.push({
        kind,
        litres: round1(litres),
        before: round1(level[run.start]!),
        after: round1(level[run.end]!),
        start: first.at,
        end: last.at,
        lat: first.lat ?? null,
        lng: first.lng ?? null,
      });
    }
    run = null;
  };

  for (let i = 1; i < readings.length; i++) {
    const delta = level[i]! - level[i - 1]!;
    const at = Date.parse(readings[i]!.at);
    if (run && at - run.changed > SETTLE_MIN * MINUTE) close();
    if (Math.abs(delta) < NOISE_L) continue;
    const sign = delta > 0 ? 1 : -1;
    if (run && run.sign === sign) {
      run.total += delta;
      run.end = i;
      run.changed = at;
    } else {
      close();
      run = { start: i - 1, end: i, sign, total: delta, changed: at };
    }
  }
  close();
  return events;
}

/** Fuel paid for against fuel that reached the tank. Red when less than half of it arrived. */
export function refillVsPaid(
  input: { paid_litres: number; refilled_litres: number },
  t: FraudThresholds = DEFAULT_FRAUD_THRESHOLDS,
): { flagged: boolean; gap_litres: number; severity: "red" | "amber" | null } {
  const gap = input.paid_litres - input.refilled_litres;
  const flagged =
    input.paid_litres > 0 &&
    gap >= Math.max(MIN_GAP_L, (input.paid_litres * t.refill_paid_gap_pct) / 100);
  return {
    flagged,
    gap_litres: round1(gap),
    severity: flagged ? (input.refilled_litres < input.paid_litres / 2 ? "red" : "amber") : null,
  };
}

export interface MatchedPurchase {
  index: number;
  paid: number;
  refilled: number;
  flagged: boolean;
  gap_litres: number;
  severity: "red" | "amber" | null;
}

/** Pairs each refill with the nearest fuel purchase within three hours. */
export function matchRefills(
  refills: { at: string; litres: number }[],
  purchases: { at: string; litres: number }[],
  t: FraudThresholds = DEFAULT_FRAUD_THRESHOLDS,
): { purchases: MatchedPurchase[]; unmatched_refills: number[] } {
  const window = MATCH_WINDOW_MIN * MINUTE;
  const filled = purchases.map(() => 0);
  const unmatched: number[] = [];
  refills.forEach((r, ri) => {
    let best = -1;
    let bestGap = Infinity;
    purchases.forEach((p, pi) => {
      const gap = Math.abs(Date.parse(r.at) - Date.parse(p.at));
      if (gap <= window && gap < bestGap) {
        best = pi;
        bestGap = gap;
      }
    });
    if (best >= 0) filled[best]! += r.litres;
    else unmatched.push(ri);
  });
  return {
    purchases: purchases.map((p, pi) => ({
      index: pi,
      paid: p.litres,
      refilled: round1(filled[pi]!),
      ...refillVsPaid({ paid_litres: p.litres, refilled_litres: filled[pi]! }, t),
    })),
    unmatched_refills: unmatched,
  };
}
