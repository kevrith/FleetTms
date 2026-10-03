import * as Location from "expo-location";
import * as TaskManager from "expo-task-manager";
import { api } from "../api";
import { files, keys } from "../offline/device";
import { createVault } from "../offline/vault";
import * as Crypto from "expo-crypto";
import { createTracker, type Fix, type FlushResult } from "./tracker";

/**
 * Phone GPS during a trip (masterplan 5.3, 11.2). Tracking is a background task that runs only between the start and the end of a
 * trip, with a notification on the phone while it does. Positions go to the tracker, which keeps them encrypted until there is a
 * network. Accuracy: the GPS chip (high accuracy), because a lorry's distance and route need real GPS fixes and the balanced mode
 * gives vague network positions that the tracker would throw away. Battery: one fix every 20 seconds or 40 metres, and the
 * system is allowed to batch deliveries.
 */
const TASK = "fleettms-trip-tracking";
const FLUSH_EVERY_MS = 60_000;
const FLUSH_AT_POINTS = 12;

export const tracker = createTracker({
  files,
  vault: createVault(keys, (n) => Crypto.getRandomBytes(n)),
  api: { sendLocations: (tripId, points) => api.sendLocations(tripId, points) },
  now: () => new Date(),
});

let lastFlushAt = 0;
let loaded: Promise<unknown> | null = null;
const ready = () => (loaded ??= tracker.load());

const toFix = (l: Location.LocationObject): Fix => ({
  recorded_at: new Date(l.timestamp).toISOString(),
  lat: l.coords.latitude,
  lng: l.coords.longitude,
  speed_kmh:
    l.coords.speed != null && l.coords.speed >= 0
      ? Math.round(l.coords.speed * 3.6 * 10) / 10
      : null,
  heading: l.coords.heading != null && l.coords.heading >= 0 ? l.coords.heading : null,
  accuracy_m: l.coords.accuracy ?? null,
});

// Runs in the background, even with the phone locked. Must be registered when the app file loads (see index.js).
TaskManager.defineTask(TASK, async ({ data, error }) => {
  if (error) return;
  await ready();
  const { locations } = (data ?? {}) as { locations?: Location.LocationObject[] };
  if (!locations?.length) return;
  await tracker.add(locations.map(toFix));
  if (tracker.waiting() >= FLUSH_AT_POINTS || Date.now() - lastFlushAt > FLUSH_EVERY_MS) {
    lastFlushAt = Date.now();
    await tracker.flush().catch(() => undefined);
  }
});

/** (Re)registers the background location task. Safe to call again: the system replaces the earlier registration. */
async function startUpdates(): Promise<void> {
  await Location.startLocationUpdatesAsync(TASK, {
    accuracy: Location.Accuracy.High,
    timeInterval: 20_000,
    distanceInterval: 40,
    deferredUpdatesInterval: 20_000,
    deferredUpdatesDistance: 40,
    pausesUpdatesAutomatically: false,
    activityType: Location.ActivityType.AutomotiveNavigation,
    showsBackgroundLocationIndicator: true,
    foregroundService: {
      notificationTitle: "FleetTms is tracking this trip",
      notificationBody: "Your location is shared with your employer until you end the trip.",
      notificationColor: "#0a7d4f",
    },
  });
}

export type StartResult =
  { ok: true } | { ok: false; reason: "denied" | "background_denied" | "failed" };

/** Starts the background task for a trip. Asks for the location permissions it needs; says why if it cannot. */
export async function startTracking(tripId: string): Promise<StartResult> {
  await ready();
  await tracker.begin(tripId);
  try {
    const fg = await Location.requestForegroundPermissionsAsync();
    if (fg.status !== "granted") return { ok: false, reason: "denied" };
    const bg = await Location.requestBackgroundPermissionsAsync();
    if (bg.status !== "granted") return { ok: false, reason: "background_denied" };
    await startUpdates();
    return { ok: true };
  } catch {
    return { ok: false, reason: "failed" };
  }
}

/** Stops the background task and the collecting. What is already waiting is still handed in. */
export async function stopTracking(): Promise<FlushResult> {
  await ready();
  await tracker.end();
  try {
    if (await Location.hasStartedLocationUpdatesAsync(TASK))
      await Location.stopLocationUpdatesAsync(TASK);
  } catch {
    /* it was not running */
  }
  return tracker.flush();
}

/** After the app restarts mid-trip: make sure tracking is still running if a trip is still on. */
export async function resumeTracking(): Promise<void> {
  await ready();
  if (
    tracker.isTracking() &&
    !(await Location.hasStartedLocationUpdatesAsync(TASK).catch(() => false))
  ) {
    await startTracking(tracker.tripId()!);
  }
}

export async function flushTracking(): Promise<FlushResult> {
  await ready();
  lastFlushAt = Date.now();
  return tracker.flush();
}

/** Signing out: stop, and forget everything waiting. */
export async function clearTracking(): Promise<void> {
  await ready();
  try {
    if (await Location.hasStartedLocationUpdatesAsync(TASK))
      await Location.stopLocationUpdatesAsync(TASK);
  } catch {
    /* not running */
  }
  await tracker.clear();
}
