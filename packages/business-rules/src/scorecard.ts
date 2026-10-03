/**
 * Driver scorecards (masterplan 5.25): safety, fuel, punctuality, inspections and alerts, each out of 100, and an overall score from
 * the ones that have data. Mirrored by apps/api/app/scorecard_rules.py and tested against scorecard-cases.json on both sides.
 */

export const SAFETY_WEIGHTS: Record<string, number> = {
  speeding: 3,
  harsh_braking: 2,
  harsh_acceleration: 1.5,
  harsh_cornering: 2,
  night_driving: 0.5,
  long_driving: 2,
};
export const SCORE_WEIGHTS: Record<string, number> = {
  safety: 0.3,
  fuel: 0.25,
  punctuality: 0.15,
  inspections: 0.15,
  alerts: 0.15,
};
const MIN_KM = 50;

const clamp = (x: number) => Math.max(0, Math.min(100, Math.floor(x + 0.5)));

export function safetyScore(counts: Record<string, number>, km: number): number | null {
  if (km <= 0) return null;
  const weighted = Object.entries(counts).reduce(
    (a, [k, n]) => a + (SAFETY_WEIGHTS[k] ?? 0) * n,
    0,
  );
  return clamp(100 - ((weighted * 100) / Math.max(km, MIN_KM)) * 2);
}

export function fuelScore(variancesPct: number[]): number | null {
  if (variancesPct.length === 0) return null;
  const avg = variancesPct.reduce((a, v) => a + Math.max(v, 0), 0) / variancesPct.length;
  return clamp(100 - avg * 5);
}

export const punctualityScore = (onTime: number, total: number): number | null =>
  total > 0 ? clamp((onTime / total) * 100) : null;

export const inspectionScore = (
  clean: number,
  withDefects: number,
  total: number,
): number | null => (total > 0 ? clamp(((clean + 0.5 * withDefects) / total) * 100) : null);

export const alertsScore = (confirmed: number, open: number): number =>
  clamp(100 - 25 * confirmed - 10 * open);

export function overallScore(parts: Record<string, number | null | undefined>): number | null {
  const have = Object.entries(parts).filter(
    (e): e is [string, number] => e[1] != null && e[0] in SCORE_WEIGHTS,
  );
  if (have.length === 0) return null;
  const weight = have.reduce((a, [k]) => a + SCORE_WEIGHTS[k]!, 0);
  return clamp(have.reduce((a, [k, v]) => a + SCORE_WEIGHTS[k]! * v, 0) / weight);
}

export function scoreBand(score: number | null): "good" | "watch" | "poor" | null {
  if (score == null) return null;
  return score >= 80 ? "good" : score >= 60 ? "watch" : "poor";
}
