import type { DashboardAlert } from "@fleettms/types";
import { describe, expect, it } from "vitest";
import {
  ago,
  ALERTS_SHOWN,
  fleetLine,
  kesShort,
  tabForLink,
  tripsLine,
  visibleAlerts,
} from "./dashboard";

const alert = (over: Partial<DashboardAlert>): DashboardAlert => ({
  kind: "service_due",
  severity: "amber",
  title: "t",
  detail: "",
  link: "/vehicles/1",
  ...over,
});

describe("kesShort", () => {
  it("drops the cents and keeps the sign", () => {
    expect(kesShort(1_250_050)).toBe("KES 12,501");
    expect(kesShort(0)).toBe("KES 0");
    expect(kesShort(-450_000)).toBe("-KES 4,500");
  });
});

describe("ago", () => {
  const now = new Date("2026-10-05T10:00:00Z");
  it("says it the way a person would", () => {
    expect(ago("2026-10-05T09:59:30Z", now)).toBe("just now");
    expect(ago("2026-10-05T09:55:00Z", now)).toBe("5 min ago");
    expect(ago("2026-10-05T07:00:00Z", now)).toBe("3 h ago");
    expect(ago("2026-10-04T10:00:00Z", now)).toBe("1 day ago");
    expect(ago("2026-10-02T10:00:00Z", now)).toBe("3 days ago");
  });
  it("never goes negative when the phone clock is behind", () => {
    expect(ago("2026-10-05T10:05:00Z", now)).toBe("just now");
  });
});

describe("tabForLink", () => {
  it("points a web link at the phone tab that shows it", () => {
    expect(tabForLink("/map")).toBe("Map");
    expect(tabForLink("/tracking")).toBe("Map");
    expect(tabForLink("/vehicles/abc")).toBe("Vehicles");
    expect(tabForLink("/workshop/tyres")).toBe("Workshop");
    expect(tabForLink("/expenses/expenses")).toBe("Money");
  });
  it("has no tab for what is only on the web", () => {
    expect(tabForLink("/clients/debtors")).toBeNull();
    expect(tabForLink("/alerts")).toBeNull();
  });
});

describe("visibleAlerts", () => {
  const many = [
    alert({ severity: "red", title: "a" }),
    alert({ severity: "red", title: "b" }),
    alert({ severity: "amber", title: "c" }),
    alert({ severity: "amber", title: "d" }),
    alert({ severity: "amber", title: "e" }),
    alert({ kind: "sos_active", severity: "red", emergency: true }),
  ];
  it("leaves emergencies to their banner and cuts the rest to the first few", () => {
    const v = visibleAlerts(many, false);
    expect(v.shown.map((a) => a.title)).toEqual(["a", "b", "c"]);
    expect(v.shown).toHaveLength(ALERTS_SHOWN);
    expect(v).toMatchObject({ hidden: 2, urgent: 2, watch: 3 });
  });
  it("shows everything when asked", () => {
    const v = visibleAlerts(many, true);
    expect(v.shown).toHaveLength(5);
    expect(v.hidden).toBe(0);
  });
});

describe("fleetLine and tripsLine", () => {
  it("lists only the states that have lorries", () => {
    const fleet = { moving: 6, idle: 2, offline: 0, parked: 0, unknown: 0, in_workshop: 1, total: 9 };
    expect(fleetLine(fleet)).toBe("6 moving · 2 standing · 1 in the workshop");
  });
  it("copes with no lorries", () => {
    const none = { moving: 0, idle: 0, offline: 0, parked: 0, unknown: 0, in_workshop: 0, total: 0 };
    expect(fleetLine(none)).toBe("No active lorries");
  });
  it("sums up the trips", () => {
    expect(tripsLine(3, 5)).toBe("3 running · 5 done");
  });
});
