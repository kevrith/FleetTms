import { describe, expect, it } from "vitest";
import {
  explainStop,
  findStops,
  fraudThresholds,
  fuelBaseline,
  fuelCheck,
  idleCheck,
  loadBand,
  odometerFinding,
  routeKey,
  sideTripCheck,
  tamperBefore,
  type FraudThresholds,
} from "./fraud";
import type { Shape } from "./geofence";
import fraud from "./fraud-cases.json";
import { findFuelEvents, matchRefills } from "./fuelsensor";
import sensor from "./fuelsensor-cases.json";
import {
  alertsScore,
  fuelScore,
  inspectionScore,
  overallScore,
  punctualityScore,
  safetyScore,
  scoreBand,
} from "./scorecard";
import scorecard from "./scorecard-cases.json";

const BASE = Date.parse("2026-10-02T08:00:00Z");
const at = (sec: number) => new Date(BASE + sec * 1000).toISOString();

describe("fraud rules", () => {
  for (const c of fraud.thresholds) {
    it(`thresholds: ${c.name}`, () => {
      expect(fraudThresholds(c.overrides as Record<string, unknown> | null)).toEqual(
        c.expected as FraudThresholds,
      );
    });
  }
  it("load bands", () => {
    for (const c of fraud.load_band) expect(loadBand(c.kg)).toBe(c.expected);
  });
  it("route keys", () => {
    for (const c of fraud.route_key) expect(routeKey(c.origin, c.destination)).toBe(c.expected);
  });
  for (const c of fraud.baseline) {
    it(`baseline: ${c.name}`, () => {
      expect(fuelBaseline(c.samples)).toEqual(c.expected);
    });
  }
  for (const c of fraud.fuel_check) {
    it(`fuel check: ${c.name}`, () => {
      expect(fuelCheck(c)).toEqual(c.expected);
    });
  }
  for (const c of fraud.side_trip) {
    it(`side trip: ${c.name}`, () => {
      expect(sideTripCheck({ gps_km: c.gps_km, expected_km: c.expected_km })).toEqual(c.expected);
    });
  }
  for (const c of fraud.find_stops) {
    it(`stops: ${c.name}`, () => {
      const got = findStops(
        c.points.map(([sec, lat, lng, speed]) => ({
          at: at(sec as number),
          lat: lat as number,
          lng: lng as number,
          speed: speed as number | null,
        })),
      ).map((s) => ({
        start_s: (Date.parse(s.start) - BASE) / 1000,
        end_s: (Date.parse(s.end) - BASE) / 1000,
        minutes: s.minutes,
        lat: s.lat,
        lng: s.lng,
      }));
      expect(got).toEqual(c.expected);
    });
  }
  for (const c of fraud.explain_stop) {
    it(`explain stop: ${c.name}`, () => {
      expect(explainStop(c.stop, c.places as Shape[])).toBe(c.expected);
    });
  }
  for (const c of fraud.tamper_before) {
    it(`tamper before: ${c.name}`, () => {
      const got = tamperBefore(at(c.stop_start_s), c.tampers_s.map(at));
      expect(got === null ? null : (Date.parse(got) - BASE) / 1000).toBe(c.expected);
    });
  }
  for (const c of fraud.idle_check) {
    it(`idle: ${c.name}`, () => {
      expect(idleCheck(c)).toEqual(c.expected);
    });
  }
  for (const c of fraud.odometer_finding) {
    it(`odometer finding: ${c.name}`, () => {
      expect(odometerFinding(c.check, c.detail)).toEqual(c.expected);
    });
  }
});

describe("scorecard rules", () => {
  it("safety", () => {
    for (const c of scorecard.safety)
      expect(safetyScore(c.counts as Record<string, number>, c.km), c.name).toBe(c.expected);
  });
  it("fuel", () => {
    for (const c of scorecard.fuel) expect(fuelScore(c.variances), c.name).toBe(c.expected);
  });
  it("punctuality", () => {
    for (const c of scorecard.punctuality)
      expect(punctualityScore(c.on_time, c.total), c.name).toBe(c.expected);
  });
  it("inspections", () => {
    for (const c of scorecard.inspections)
      expect(inspectionScore(c.clean, c.with_defects, c.total), c.name).toBe(c.expected);
  });
  it("alerts", () => {
    for (const c of scorecard.alerts)
      expect(alertsScore(c.confirmed, c.open), c.name).toBe(c.expected);
  });
  it("overall", () => {
    for (const c of scorecard.overall) expect(overallScore(c.parts), c.name).toBe(c.expected);
  });
  it("band", () => {
    for (const c of scorecard.band) expect(scoreBand(c.score)).toBe(c.expected);
  });
});

describe("fuel sensor rules", () => {
  const BASE_T = Date.parse("2026-10-02T22:00:00Z");
  const iso = (sec: number) => new Date(BASE_T + sec * 1000).toISOString();
  for (const c of sensor.events) {
    it(`events: ${c.name}`, () => {
      const got = findFuelEvents(
        c.points.map(([sec, litres, speed]) => ({
          at: iso(sec as number),
          litres: litres as number,
          speed: speed as number | null,
        })),
      ).map((e) => ({
        kind: e.kind,
        litres: e.litres,
        before: e.before,
        after: e.after,
        start_s: (Date.parse(e.start) - BASE_T) / 1000,
        end_s: (Date.parse(e.end) - BASE_T) / 1000,
      }));
      expect(got).toEqual(c.expected);
    });
  }
  for (const c of sensor.match) {
    it(`refills against purchases: ${c.name}`, () => {
      const got = matchRefills(
        c.refills.map(([sec, litres]) => ({ at: iso(sec as number), litres: litres as number })),
        c.purchases.map(([sec, litres]) => ({ at: iso(sec as number), litres: litres as number })),
      );
      expect(got).toEqual(c.expected);
    });
  }
});
