import {
  inspectionClearsTrip,
  nairobiDay,
  tripDistanceKm,
  type InspectionOutcome,
} from "@fleettms/business-rules";
import type { Trip } from "@fleettms/types";
import type { DriverCache, QueueItem } from "./types";

/**
 * What the phone shows for a trip right after the driver acts, before the server has heard about it.
 * The server applies the same rules when the queue syncs and its answer replaces this once nothing is waiting.
 */

export class LocalRuleError extends Error {}

/** Today's inspection must clear the vehicle, judged on the day the trip is being started. */
export function assertInspectionClears(cache: DriverCache, vehicleId: string, atIso: string): void {
  const i = cache.inspection;
  const today = i && i.vehicleId === vehicleId && i.day === nairobiDay(atIso);
  if (!today) throw new LocalRuleError("Do the pre-trip inspection first.");
  if (!inspectionClearsTrip(i.status as InspectionOutcome)) {
    throw new LocalRuleError(
      "The inspection found a critical fault. A manager must clear it before you can start.",
    );
  }
}

/** An odometer never goes backwards: a reading below the vehicle's last one is refused, as the server does. */
export function assertNotBelowOdometer(cache: DriverCache, value: number): void {
  const last = cache.vehicle?.vehicle.odometer_km ?? 0;
  if (value < last) {
    throw new LocalRuleError(
      `That is lower than this vehicle's last odometer reading (${last.toLocaleString("en-KE")} km). Check the number.`,
    );
  }
}

/** The vehicle as the phone shows it once a reading has been taken: its odometer is the highest reading seen. */
export function withOdometer(
  vehicle: DriverCache["vehicle"],
  value: number,
): DriverCache["vehicle"] {
  if (!vehicle) return vehicle;
  return {
    ...vehicle,
    vehicle: { ...vehicle.vehicle, odometer_km: Math.max(vehicle.vehicle.odometer_km, value) },
  };
}

const must = (trip: Trip | null, ...allowed: Trip["status"][]): Trip => {
  if (!trip || !allowed.includes(trip.status))
    throw new LocalRuleError("That cannot be done at this point in the trip.");
  return trip;
};

export function startedTrip(trip: Trip | null, value: number, at: string): Trip {
  const t = must(trip, "scheduled");
  return {
    ...t,
    status: "in_progress",
    started_at: at,
    start_reading: { value, auto_read_value: null, flags: [], photo: null, recorded_at: at },
  };
}

/** Cargo can be loaded and weighed before the lorry leaves, or on the road. The overload is judged on the phone too. */
export function loadedTrip(
  trip: Trip | null,
  at: string,
  weigh?: { weightKg: number | null; overloadKg: number | null },
): Trip {
  return {
    ...must(trip, "scheduled", "in_progress"),
    loaded_at: at,
    loaded_weight_kg: weigh?.weightKg ?? null,
    overload_kg: weigh?.overloadKg ?? null,
  };
}

export function deliveredTrip(trip: Trip | null, at: string): Trip {
  return { ...must(trip, "in_progress"), status: "delivered", delivered_at: at };
}

export function endedTrip(trip: Trip | null, value: number, at: string): Trip {
  const t = must(trip, "in_progress", "delivered");
  const distance = tripDistanceKm(t.start_reading?.value ?? value, value);
  if (distance === null)
    throw new LocalRuleError("The end reading cannot be lower than the start reading.");
  return {
    ...t,
    status: "completed",
    ended_at: at,
    distance_km: distance,
    end_reading: { value, auto_read_value: null, flags: [], photo: null, recorded_at: at },
  };
}

/**
 * The float balance to show. Expenses waiting to be sent are taken off already, so the driver sees what they really have
 * even before the office has heard. Null until the first balance has been downloaded.
 */
export function displayBalance(cache: DriverCache, queue: QueueItem[]): number | null {
  if (!cache.float) return null;
  const waiting = queue.filter((i) => i.type === "expense.add" && i.status === "queued");
  return (
    cache.float.balance_cents -
    waiting.reduce((sum, i) => sum + Number(i.payload.amount_cents ?? 0), 0)
  );
}
