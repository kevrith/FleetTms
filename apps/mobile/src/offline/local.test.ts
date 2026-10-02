import type { Trip } from "@fleettms/types";
import { describe, expect, it } from "vitest";
import {
  assertInspectionClears,
  assertNotBelowOdometer,
  withOdometer,
  deliveredTrip,
  displayBalance,
  endedTrip,
  loadedTrip,
  LocalRuleError,
  startedTrip,
} from "./local";
import { emptyCache, type QueueItem } from "./types";

const trip = (over: Partial<Trip> = {}): Trip => ({
  id: "t1",
  status: "scheduled",
  vehicle_id: "v1",
  registration: "KCA 101A",
  driver_membership_id: "d",
  turnboy_membership_id: null,
  cargo_description: null,
  origin: null,
  destination: null,
  scheduled_for: null,
  started_at: null,
  loaded_at: null,
  loaded_weight_kg: null,
  cargo_photo: null,
  delivered_at: null,
  ended_at: null,
  distance_km: null,
  start_reading: null,
  end_reading: null,
  inspection: null,
  ...over,
});
const at = "2026-10-02T06:00:00Z";

describe("local trip rules", () => {
  it("walks a trip from scheduled to completed with the distance worked out", () => {
    const started = startedTrip(trip(), 125100, at);
    expect(started).toMatchObject({ status: "in_progress", started_at: at });
    expect(loadedTrip(started, at).loaded_at).toBe(at);
    const delivered = deliveredTrip(started, at);
    expect(delivered.status).toBe("delivered");
    expect(endedTrip(delivered, 125580, at)).toMatchObject({
      status: "completed",
      distance_km: 480,
    });
  });
  it("lets the cargo be weighed before the lorry leaves, and remembers an overload", () => {
    const weighed = loadedTrip(trip(), at, { weightKg: 11500, overloadKg: 1500 });
    expect(weighed).toMatchObject({
      status: "scheduled",
      loaded_weight_kg: 11500,
      overload_kg: 1500,
    });
  });
  it("can end a trip straight from in progress", () =>
    expect(endedTrip(startedTrip(trip(), 1000, at), 1200, at).distance_km).toBe(200));
  it("refuses steps that make no sense", () => {
    expect(() => startedTrip(trip({ status: "in_progress" }), 1, at)).toThrow(LocalRuleError);
    expect(() => loadedTrip(trip({ status: "completed" }), at)).toThrow(LocalRuleError);
    expect(() => deliveredTrip(null, at)).toThrow(LocalRuleError);
    expect(() => endedTrip(startedTrip(trip(), 1000, at), 900, at)).toThrow(/lower/);
  });
});

describe("inspection gate", () => {
  const cache = (status: "passed" | "blocked", day: string) => ({
    ...emptyCache(),
    inspection: { vehicleId: "v1", day, status },
  });
  it("needs an inspection for this vehicle on this Nairobi day", () => {
    expect(() => assertInspectionClears(emptyCache(), "v1", at)).toThrow(/inspection first/);
    expect(() => assertInspectionClears(cache("passed", "2026-10-01"), "v1", at)).toThrow(
      /inspection first/,
    );
    expect(() => assertInspectionClears(cache("passed", "2026-10-02"), "v2", at)).toThrow(
      /inspection first/,
    );
    expect(() => assertInspectionClears(cache("passed", "2026-10-02"), "v1", at)).not.toThrow();
  });
  it("blocks on a critical fault", () =>
    expect(() => assertInspectionClears(cache("blocked", "2026-10-02"), "v1", at)).toThrow(
      /critical fault/,
    ));
});

describe("displayBalance", () => {
  const withFloat = (cents: number) => ({
    ...emptyCache(),
    float: { balance_cents: cents, received_cents: cents, recent: [] },
  });
  const queued = (
    type: QueueItem["type"],
    amount: number,
    status: QueueItem["status"] = "queued",
  ): QueueItem => ({
    id: `${type}${amount}${status}`,
    type,
    payload: { amount_cents: amount },
    capturedAt: at,
    photoIds: [],
    status,
    attempts: 0,
  });
  it("is unknown until a balance has been downloaded", () =>
    expect(displayBalance(emptyCache(), [])).toBeNull());
  it("takes expenses that are still waiting off the balance", () =>
    expect(
      displayBalance(withFloat(300000), [
        queued("expense.add", 50000),
        queued("expense.add", 20000),
      ]),
    ).toBe(230000));
  it("ignores things that are not expenses, and expenses the office refused", () =>
    expect(
      displayBalance(withFloat(300000), [
        queued("fuel.add", 99999),
        queued("expense.add", 40000, "rejected"),
      ]),
    ).toBe(300000));
});

describe("odometer on the phone", () => {
  const withVehicle = (km: number) =>
    ({
      ...emptyCache(),
      vehicle: { vehicle: { id: "v1", odometer_km: km }, my_role: "driver", crew: [] },
    }) as never;
  it("refuses a reading below the vehicle's last one", () => {
    expect(() => assertNotBelowOdometer(withVehicle(125580), 125100)).toThrow(/lower than/);
    expect(() => assertNotBelowOdometer(withVehicle(125580), 125580)).not.toThrow();
  });
  it("moves the vehicle's odometer up with each reading, never down", () => {
    const c = withVehicle(125000) as ReturnType<typeof emptyCache>;
    expect(withOdometer(c.vehicle, 125580)?.vehicle.odometer_km).toBe(125580);
    expect(withOdometer(c.vehicle, 100)?.vehicle.odometer_km).toBe(125000);
    expect(withOdometer(null, 5)).toBeNull();
  });
});
