import { randomBytes } from "node:crypto";
import type { DeviceReport, SyncAction, SyncResponse, SyncResult } from "@fleettms/types";
import type { EngineApi } from "./engine";
import type { FileAdapter } from "./store";
import { createStore } from "./store";
import { createVault, type KeyStore } from "./vault";

export const random = (n: number) => new Uint8Array(randomBytes(n));

export function memoryKeys(): KeyStore & { value: string | null } {
  const keys = {
    value: null as string | null,
    get: async () => keys.value,
    set: async (v: string) => void (keys.value = v),
    clear: async () => void (keys.value = null),
  };
  return keys;
}

export function memoryFiles(): FileAdapter & {
  disk: Map<string, string>;
  temps: Map<string, Uint8Array>;
} {
  const disk = new Map<string, string>();
  const temps = new Map<string, Uint8Array>();
  return {
    disk,
    temps,
    read: async (n) => disk.get(n) ?? null,
    write: async (n, b) => void disk.set(n, b),
    remove: async (n) => void disk.delete(n),
    removeAll: async () => disk.clear(),
    writeTemp: async (name, bytes) => {
      temps.set(name, bytes);
      return { uri: `file:///tmp/${name}`, cleanup: async () => void temps.delete(name) };
    },
  };
}

export function makeStore() {
  const files = memoryFiles();
  const keys = memoryKeys();
  let n = 0;
  const store = createStore({
    files,
    vault: createVault(keys, random),
    uuid: () => `id-${++n}`,
    now: () => new Date("2026-10-02T08:00:00Z"),
  });
  return { store, files, keys };
}

export class ApiFailure extends Error {
  constructor(
    public status: number,
    public code: string,
    message = code,
  ) {
    super(message);
  }
}

/** A pretend server that behaves like the real one: an action id it has applied is answered "duplicate". */
export function fakeServer(
  options: {
    rejectType?: Record<string, { code: string; retryable?: boolean }>;
    photoMissing?: Set<string>;
  } = {},
) {
  const applied = new Map<string, SyncResult>();
  const photos = new Set<string>();
  const server = {
    applied,
    photos,
    syncCalls: [] as SyncAction[][],
    devices: [] as DeviceReport[],
    failNext: [] as ("network" | "lost_reply" | "401")[],
    refreshes: 0,
    photoFailure: null as ApiFailure | null,
    api: {
      async uploadPhoto(_file, meta) {
        const mode = server.failNext[0];
        if (mode === "network") {
          server.failNext.shift();
          throw new TypeError("Network request failed");
        }
        if (server.photoFailure) throw server.photoFailure;
        photos.add(String(meta.client_id));
        return {};
      },
      async sync(actions: SyncAction[], device): Promise<SyncResponse> {
        const mode = server.failNext.shift();
        if (mode === "network") throw new TypeError("Network request failed");
        if (mode === "401") throw new ApiFailure(401, "not_authenticated");
        server.syncCalls.push(actions);
        server.devices.push(device);
        const results: SyncResult[] = actions.map((a) => {
          const seen = applied.get(a.client_id);
          if (seen) return { client_id: a.client_id, status: "duplicate", result: seen.result };
          const reject = options.rejectType?.[a.type];
          if (reject)
            return {
              client_id: a.client_id,
              status: "rejected",
              code: reject.code,
              message: reject.code,
              retryable: reject.retryable ?? false,
            };
          const missing =
            (a.payload.photo_client_id as string | undefined) &&
            !photos.has(String(a.payload.photo_client_id));
          if (missing)
            return {
              client_id: a.client_id,
              status: "rejected",
              code: "photo_invalid",
              message: "photo",
              retryable: true,
            };
          const ok: SyncResult = {
            client_id: a.client_id,
            status: "ok",
            result: { id: a.client_id },
          };
          applied.set(a.client_id, ok);
          return ok;
        });
        if (mode === "lost_reply") throw new TypeError("Network request failed"); // applied, but the phone never heard
        return { server_time: "2026-10-02T08:05:00Z", device_flags: [], results };
      },
      async refresh() {
        server.refreshes += 1;
        return { refreshedAt: "now" };
      },
    } satisfies EngineApi,
  };
  return server;
}

export const device = async (): Promise<DeviceReport> => ({ device_id: "pixel-1" });
