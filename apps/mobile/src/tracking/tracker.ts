import { goodFix } from "@fleettms/business-rules";
import { fromB64, toB64, unutf8, utf8 } from "../offline/bytes";
import type { FileAdapter } from "../offline/store";
import type { Vault } from "../offline/vault";

/** One position the phone took. Times are ISO with a time zone, as the server requires. */
export interface Fix {
  recorded_at: string;
  lat: number;
  lng: number;
  speed_kmh: number | null;
  heading: number | null;
  accuracy_m: number | null;
}

export interface TrackApi {
  sendLocations(tripId: string, points: Fix[]): Promise<unknown>;
}

interface State {
  tripId: string | null;
  /** Set when the trip ends: fixes taken after this moment are never kept. */
  stoppedAt: string | null;
  points: Fix[];
}

const FILE = "track.enc";
export const BATCH_SIZE = 500;
export const MAX_POINTS = 5000;
export const KEEP_DAYS = 3;
const empty = (): State => ({ tripId: null, stoppedAt: null, points: [] });

interface ApiLike {
  status?: number;
}

export type FlushResult =
  | { status: "idle" }
  | { status: "offline" }
  | { status: "signed_out" }
  | { status: "waiting" } // the server has not started this trip yet: try again later
  | { status: "done"; sent: number };

/**
 * What the phone does about location, and only that. Fixes are collected for one trip at a time: with no trip begun, nothing is
 * kept, and once the trip has ended a fix taken after the end is thrown away, so tracking stops with the work. Fixes wait in an
 * encrypted file until there is a network, then go to the server in batches; the server stores each moment once, so a resend is
 * harmless. Nothing here talks to the GPS: the background task hands fixes in.
 */
export function createTracker(deps: {
  files: FileAdapter;
  vault: Vault;
  api: TrackApi;
  now: () => Date;
}) {
  let state: State = empty();
  let writing: Promise<void> = Promise.resolve();
  let flushing: Promise<FlushResult> | null = null;

  function persist(): Promise<void> {
    const snapshot = JSON.stringify(state);
    writing = writing.then(async () => {
      await deps.files.write(FILE, toB64(await deps.vault.seal(utf8(snapshot))));
    });
    return writing;
  }

  async function load(): Promise<State> {
    const sealed = await deps.files.read(FILE);
    if (!sealed) return (state = empty());
    try {
      state = JSON.parse(unutf8(await deps.vault.open(fromB64(sealed)))) as State;
    } catch {
      state = empty(); // unreadable (key lost): start clean rather than crash
    }
    return state;
  }

  const prune = (points: Fix[]) => {
    const oldest = deps.now().getTime() - KEEP_DAYS * 86_400_000;
    const kept = points.filter((p) => Date.parse(p.recorded_at) >= oldest);
    return kept.length > MAX_POINTS ? kept.slice(kept.length - MAX_POINTS) : kept;
  };

  async function sendAll(): Promise<FlushResult> {
    if (state.tripId === null || state.points.length === 0) {
      if (state.tripId !== null && state.stoppedAt !== null) {
        state = empty(); // the trip is over and everything has been handed in
        await persist();
      }
      return { status: "idle" };
    }
    const tripId = state.tripId;
    let sent = 0;
    while (state.points.length > 0) {
      const batch = state.points.slice(0, BATCH_SIZE);
      try {
        await deps.api.sendLocations(tripId, batch);
      } catch (e) {
        const status = (e as ApiLike | null)?.status;
        if (status === 401) return { status: "signed_out" };
        if (status === 404) {
          // The server says this is not our trip. Keep nothing of it.
          state = empty();
          await persist();
          return { status: "idle" };
        }
        if (status === 409) return { status: "waiting" };
        return { status: "offline" };
      }
      // Accepted, or refused for good (outside the trip's hours): either way it is not sent again.
      state = { ...state, points: state.points.slice(batch.length) };
      sent += batch.length;
      await persist();
    }
    if (state.stoppedAt !== null) {
      state = empty();
      await persist();
    }
    return { status: "done", sent };
  }

  return {
    load,
    /** Starts collecting for a trip. Fixes already waiting for the same trip are kept. */
    async begin(tripId: string): Promise<void> {
      state =
        state.tripId === tripId
          ? { ...state, stoppedAt: null }
          : { tripId, stoppedAt: null, points: [] };
      await persist();
    },
    /** Takes fixes from the GPS. Ignored unless a trip has begun and not ended. Returns how many were kept. */
    async add(fixes: Fix[]): Promise<number> {
      if (state.tripId === null) return 0;
      const stop = state.stoppedAt === null ? Infinity : Date.parse(state.stoppedAt);
      const have = new Set(state.points.map((p) => p.recorded_at));
      const fresh = fixes.filter(
        (f) =>
          goodFix(f.lat, f.lng, f.accuracy_m) &&
          Date.parse(f.recorded_at) <= stop &&
          !have.has(f.recorded_at),
      );
      if (fresh.length === 0) return 0;
      state = {
        ...state,
        points: prune(
          [...state.points, ...fresh].sort(
            (a, b) => Date.parse(a.recorded_at) - Date.parse(b.recorded_at),
          ),
        ),
      };
      await persist();
      return fresh.length;
    },
    /** The trip has ended: no more fixes are kept from this moment, and what is waiting is handed in. */
    async end(): Promise<void> {
      if (state.tripId === null) return;
      state = { ...state, stoppedAt: deps.now().toISOString() };
      await persist();
    },
    /** Sends what is waiting. Calls made while one is running share its result. */
    flush(): Promise<FlushResult> {
      flushing ??= sendAll().finally(() => {
        flushing = null;
      });
      return flushing;
    },
    /** True while a trip is being tracked (begun and not yet ended). */
    isTracking: () => state.tripId !== null && state.stoppedAt === null,
    tripId: () => state.tripId,
    waiting: () => state.points.length,
    /** Signing out: nothing of this person's trip stays on the phone. */
    async clear(): Promise<void> {
      await writing.catch(() => undefined);
      state = empty();
      await deps.files.remove(FILE);
    },
  };
}
export type Tracker = ReturnType<typeof createTracker>;
