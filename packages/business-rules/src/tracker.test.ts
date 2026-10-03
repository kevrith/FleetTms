import { describe, expect, it } from "vitest";
import { behaviourStep, newBehaviourState } from "./behaviour";
import behaviour from "./behaviour-cases.json";
import { geofenceStep, insideShape, type Shape, type SideState } from "./geofence";
import geofence from "./geofence-cases.json";
import { threeWay } from "./gps";
import gps from "./gps-cases.json";
import { immobiliserCheck } from "./immobiliser";
import immobiliser from "./immobiliser-cases.json";

describe("behaviourStep", () => {
  for (const c of behaviour) {
    it(c.name, () => {
      const base = Date.parse("base" in c ? (c.base as string) : "2026-10-02T08:00:00Z");
      let state = newBehaviourState();
      const got: Record<string, unknown>[] = [];
      for (const [sec, speed, heading, ignition] of c.points as [
        number,
        number,
        number,
        boolean | null,
      ][]) {
        const out = behaviourStep(state, {
          at: new Date(base + sec * 1000).toISOString(),
          speed,
          heading,
          ignition,
        });
        state = out.state;
        for (const e of out.events) {
          got.push({
            kind: e.kind,
            value: e.value,
            at_s: (Date.parse(e.at) - base) / 1000,
            ...(e.ended_at ? { ended_s: (Date.parse(e.ended_at) - base) / 1000 } : {}),
          });
        }
      }
      expect(got).toHaveLength(c.expected.length);
      got.forEach((g, i) => {
        const want = c.expected[i] as Record<string, unknown>;
        expect(g.kind).toBe(want.kind);
        expect(Math.abs((g.value as number) - (want.value as number))).toBeLessThan(0.011);
        expect(g.at_s).toBe(want.at_s);
        expect(g.ended_s).toBe(want.ended_s);
      });
    });
  }
});

describe("insideShape", () => {
  for (const c of geofence.inside) {
    it(c.name, () => {
      expect(insideShape(c.shape as Shape, c.point[0]!, c.point[1]!)).toBe(c.expected);
    });
  }
});

describe("geofenceStep", () => {
  for (const c of geofence.steps) {
    it(c.name, () => {
      let state: SideState | null = null;
      const got = c.sides.map((side) => {
        const out = geofenceStep(state, side);
        state = out.state;
        return out.event;
      });
      expect(got).toEqual(c.expected);
    });
  }
});

describe("immobiliserCheck", () => {
  for (const c of immobiliser) {
    it(c.name, () => {
      expect(
        immobiliserCheck({
          action: c.action as "immobilise" | "release",
          speed_kmh: c.speed,
          position_age_s: c.age_s,
          online: c.online,
          supported: c.supported,
        }),
      ).toEqual({ allowed: c.allowed, reason: c.reason });
    });
  }
});

describe("threeWay", () => {
  for (const c of gps.three_way) {
    it(c.name, () => {
      const got = threeWay({
        odometer_km: c.odometer_km,
        phone_km: c.phone_km,
        phone_points: c.phone_points,
        tracker_km: c.tracker_km,
        tracker_points: c.tracker_points,
      });
      expect(got.check).toBe(c.check);
      expect(got.suspect).toBe(c.suspect);
    });
  }
});
