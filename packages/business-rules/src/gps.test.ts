import { describe, expect, it } from "vitest";
import {
  distanceCheck,
  etaMinutes,
  goodFix,
  haversineKm,
  pathDistanceKm,
  vehicleState,
} from "./gps";
import cases from "./gps-cases.json";

const T0 = Date.parse("2026-10-02T08:00:00Z");
const at = (s: number) => new Date(T0 + s * 1000).toISOString();

describe("haversineKm", () => {
  for (const c of cases.haversine) {
    it(c.name, () => {
      const got = haversineKm(c.from[0]!, c.from[1]!, c.to[0]!, c.to[1]!);
      expect(Math.abs(got - c.km)).toBeLessThanOrEqual(c.tolerance ?? 0.001);
    });
  }
});

describe("goodFix", () => {
  for (const c of cases.good_fix) {
    it(c.name, () => {
      expect(goodFix(c.lat, c.lng, c.accuracy_m)).toBe(c.expected);
    });
  }
});

describe("pathDistanceKm", () => {
  for (const c of cases.paths) {
    it(c.name, () => {
      const points = c.points.map(([s, lat, lng, a]) => ({
        at: at(s!),
        lat: lat!,
        lng: lng!,
        accuracy_m: a,
      }));
      expect(pathDistanceKm(points)).toEqual({ km: c.km, used: c.used });
    });
  }
});

describe("vehicleState", () => {
  for (const c of cases.states) {
    it(c.name, () => {
      const now = at(100000);
      const last =
        c.age_s === null ? null : new Date(Date.parse(now) - c.age_s * 1000).toISOString();
      expect(vehicleState({ on_trip: c.on_trip, last_at: last, now, speed_kmh: c.speed })).toBe(
        c.expected,
      );
    });
  }
});

describe("distanceCheck", () => {
  for (const c of cases.checks) {
    it(c.name, () => {
      expect(distanceCheck(c.odometer_km, c.gps_km, c.points)).toBe(c.expected);
    });
  }
});

describe("etaMinutes", () => {
  for (const c of cases.etas) {
    it(c.name, () => {
      expect(etaMinutes(c.remaining_km, c.speeds)).toBe(c.expected);
    });
  }
});
