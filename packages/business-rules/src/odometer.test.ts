import { describe, expect, it } from "vitest";
import { odometerProblem, parseOdometer, readingFlags, tripDistanceKm } from "./odometer";

describe("parseOdometer", () => {
  it("accepts whole numbers, ignoring spaces and commas", () => {
    expect(parseOdometer("125,400")).toBe(125400);
    expect(parseOdometer(" 98 200 ")).toBe(98200);
    expect(parseOdometer("0")).toBe(0);
  });
  it("rejects anything else", () => {
    for (const bad of ["", "12.5", "-3", "abc", "10000000", "12 km"])
      expect(parseOdometer(bad)).toBeNull();
  });
});

describe("readingFlags", () => {
  const base = { confirmed: 125100, autoRead: 125100, lastKnownKm: 125000, hasLocation: true };
  it("flags nothing for a normal reading", () => expect(readingFlags(base)).toEqual([]));
  it("flags a mismatch between the read and confirmed numbers", () =>
    expect(readingFlags({ ...base, autoRead: 125900 })).toEqual(["mismatch"]));
  it("does not flag a mismatch when no reader ran", () =>
    expect(readingFlags({ ...base, autoRead: null })).toEqual([]));
  it("flags a backward reading", () =>
    expect(readingFlags({ ...base, confirmed: 124000, autoRead: 124000 })).toEqual(["backward"]));
  it("flags a large jump but not a long normal trip", () => {
    expect(readingFlags({ ...base, confirmed: 128100, autoRead: 128100 })).toEqual(["large_jump"]);
    expect(readingFlags({ ...base, confirmed: 128000, autoRead: 128000 })).toEqual([]);
  });
  it("flags a missing location, and combines flags", () =>
    expect(readingFlags({ ...base, confirmed: 100, autoRead: 200, hasLocation: false })).toEqual([
      "mismatch",
      "backward",
      "no_location",
    ]));
});

describe("tripDistanceKm", () => {
  it("is the difference, and null when the end is below the start", () => {
    expect(tripDistanceKm(125100, 125580)).toBe(480);
    expect(tripDistanceKm(125100, 125100)).toBe(0);
    expect(tripDistanceKm(125100, 125000)).toBeNull();
  });
});

describe("odometerProblem", () => {
  it("returns null for a sensible number", () =>
    expect(odometerProblem("125100", 125000)).toBeNull());
  it("explains each problem in plain words", () => {
    expect(odometerProblem("abc", 1)).toMatch(/whole number/);
    expect(odometerProblem("100", 125000)).toMatch(/lower than the last reading/);
    expect(odometerProblem("140000", 125000)).toMatch(/long way/);
    expect(odometerProblem("125000", 125000, 125100)).toMatch(/end reading/);
  });
});
