import type { DeviceReport, SyncAction, SyncResponse } from "@fleettms/types";
import type { Store } from "./store";
import type { DriverCache, QueueItem } from "./types";

export interface EngineApi {
  uploadPhoto(
    file: { uri: string; name: string; type: string },
    meta: Record<string, unknown>,
  ): Promise<unknown>;
  sync(actions: SyncAction[], device: DeviceReport): Promise<SyncResponse>;
  /** The server's current view of the driver's vehicle, trip, checklist, inspection and float. */
  refresh(): Promise<Partial<DriverCache>>;
}

export type RunResult =
  | { status: "offline" }
  | { status: "signed_out" }
  | { status: "done"; applied: number; rejected: number; waiting: number };

export const BATCH = 50;
export const GIVE_UP_AFTER = 5;

interface ApiLike {
  status: number;
  code?: string;
  message?: string;
}
const asApiError = (e: unknown): ApiLike | null =>
  e && typeof e === "object" && typeof (e as ApiLike).status === "number" ? (e as ApiLike) : null;

/**
 * Sends the queue when there is a network. Photos go first (each with the id the phone gave it, so a retry never
 * stores one twice), then the actions in the order the driver did them. Anything the server has already applied comes
 * back as a duplicate and is simply cleared, which makes a lost reply harmless: the next run resends and it settles.
 */
export function createSyncEngine(deps: {
  store: Store;
  api: EngineApi;
  isOnline: () => Promise<boolean>;
  device: () => Promise<DeviceReport>;
}) {
  const { store, api } = deps;
  let running: Promise<RunResult> | null = null;

  const waiting = () => store.get().queue.filter((i) => i.status === "queued").length;
  const setItem = (id: string, patch: Partial<QueueItem>) =>
    store.update((s) => ({
      ...s,
      queue: s.queue.map((i) => (i.id === id ? { ...i, ...patch } : i)),
    }));

  async function uploadPhotos(): Promise<"ok" | "offline" | "signed_out"> {
    for (const item of store.get().queue.filter((i) => i.status === "queued")) {
      for (const id of item.photoIds) {
        const photo = store.get().photos[id];
        if (!photo || photo.uploaded) continue;
        const temp = await store.materialize(id);
        if (!temp) {
          await setItem(item.id, {
            status: "rejected",
            code: "photo_lost",
            message: "A photo for this record is missing from the phone.",
          });
          break;
        }
        try {
          await api.uploadPhoto(
            { uri: temp.uri, name: "photo.jpg", type: "image/jpeg" },
            {
              kind: photo.kind,
              source: "camera",
              captured_at: photo.capturedAt,
              lat: photo.lat,
              lng: photo.lng,
              client_id: id,
              offline: true,
            },
          );
          await store.update((s) => ({
            ...s,
            photos: { ...s.photos, [id]: { ...s.photos[id]!, uploaded: true } },
          }));
        } catch (e) {
          const err = asApiError(e);
          if (!err) return "offline";
          if (err.status === 401) return "signed_out";
          // The server looked at the photo and refused it (blank, too old, too small). Retrying cannot help.
          await setItem(item.id, {
            status: "rejected",
            code: err.code ?? "photo_refused",
            message: err.message ?? "The photo was refused.",
          });
          break;
        } finally {
          await temp.cleanup();
        }
      }
    }
    return "ok";
  }

  async function sendActions(only?: (i: QueueItem) => boolean): Promise<{
    outcome: "ok" | "offline" | "signed_out";
    applied: number;
    rejected: number;
    more: boolean;
  }> {
    const ready = store
      .get()
      .queue.filter(
        (i) =>
          i.status === "queued" &&
          (only?.(i) ?? true) &&
          i.photoIds.every((id) => store.get().photos[id]?.uploaded),
      )
      .slice(0, BATCH);
    const device = await deps.device();
    let res: SyncResponse;
    try {
      res = await api.sync(
        ready.map((i) => ({
          client_id: i.id,
          type: i.type,
          payload: { ...i.payload, captured_at: i.capturedAt },
        })),
        device,
      );
    } catch (e) {
      const err = asApiError(e);
      return {
        outcome: err?.status === 401 ? "signed_out" : "offline",
        applied: 0,
        rejected: 0,
        more: false,
      };
    }
    let applied = 0;
    let rejected = 0;
    for (const r of res.results) {
      const item = store.get().queue.find((i) => i.id === r.client_id);
      if (!item) continue;
      if (r.status === "ok" || r.status === "duplicate") {
        applied += 1;
        if (item.type === "fuel.add") {
          await store.update((s) => ({
            ...s,
            cache: {
              ...s.cache,
              fuel: s.cache.fuel.map((f) =>
                f.clientId === item.payload.client_id ? { ...f, synced: true } : f,
              ),
            },
          }));
        }
        await store.discard(item.id); // done: forget it and delete its photos
      } else if (r.retryable && item.attempts + 1 < GIVE_UP_AFTER) {
        await setItem(item.id, { attempts: item.attempts + 1, code: r.code, message: r.message });
        // The photo may not have arrived under that id; upload it again on the next run.
        await store.update((s) => ({
          ...s,
          photos: Object.fromEntries(
            Object.entries(s.photos).map(([k, p]) => [
              k,
              item.photoIds.includes(k) ? { ...p, uploaded: false } : p,
            ]),
          ),
        }));
      } else {
        rejected += 1;
        await setItem(item.id, {
          status: "rejected",
          code: r.code,
          message: r.message,
          attempts: item.attempts + 1,
        });
      }
    }
    // The device report went with this batch; a mock-location sighting is now on the record.
    await store.update((s) => ({ ...s, mockSeen: false, lastSyncAt: res.server_time }));
    return { outcome: "ok", applied, rejected, more: ready.length === BATCH };
  }

  async function runOnce(refresh: boolean): Promise<RunResult> {
    if (!(await deps.isOnline())) return { status: "offline" };
    let applied = 0;
    let rejected = 0;
    // An SOS never waits behind photo uploads or other records.
    if (store.get().queue.some((i) => i.type === "sos.send" && i.status === "queued")) {
      const urgent = await sendActions((i) => i.type === "sos.send");
      if (urgent.outcome !== "ok")
        return urgent.outcome === "offline" ? { status: "offline" } : { status: "signed_out" };
      applied += urgent.applied;
      rejected += urgent.rejected;
    }
    for (let round = 0; round < 20; round++) {
      const photos = await uploadPhotos();
      if (photos !== "ok")
        return photos === "offline" ? { status: "offline" } : { status: "signed_out" };
      const hasReady = store
        .get()
        .queue.some(
          (i) =>
            i.status === "queued" && i.photoIds.every((id) => store.get().photos[id]?.uploaded),
        );
      if (!hasReady && round > 0) break;
      if (!hasReady && !refresh) break;
      const sent = await sendActions();
      if (sent.outcome !== "ok")
        return sent.outcome === "offline" ? { status: "offline" } : { status: "signed_out" };
      applied += sent.applied;
      rejected += sent.rejected;
      if (!sent.more) break;
    }
    // Only take the server's word for the driver's state once nothing of theirs is still waiting to be sent.
    if (waiting() === 0 && (refresh || applied > 0)) {
      try {
        const fresh = await api.refresh();
        await store.update((s) => ({
          ...s,
          cache: {
            ...s.cache,
            ...fresh,
            fuel: s.cache.fuel.slice(0, 10),
            refreshedAt: new Date().toISOString(),
          },
        }));
      } catch (e) {
        if (asApiError(e)?.status === 401) return { status: "signed_out" };
      }
    }
    return { status: "done", applied, rejected, waiting: waiting() };
  }

  return {
    /** Runs one sync pass. Calls made while one is running share its result instead of starting another. */
    run(options: { refresh?: boolean } = {}): Promise<RunResult> {
      running ??= runOnce(options.refresh ?? false).finally(() => {
        running = null;
      });
      return running;
    },
    isRunning: () => running !== null,
  };
}
export type SyncEngine = ReturnType<typeof createSyncEngine>;
