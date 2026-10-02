import {
  fuelFlags,
  inspectionOutcome,
  nairobiDay,
  normalizeMpesaCode,
} from "@fleettms/business-rules";
import type { DeviceReport } from "@fleettms/types";
import NetInfo from "@react-native-community/netinfo";
import Constants from "expo-constants";
import * as Crypto from "expo-crypto";
import * as Device from "expo-device";
import * as FileSystem from "expo-file-system";
import * as Location from "expo-location";
import * as SecureStore from "expo-secure-store";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { AppState } from "react-native";
import { api } from "../api";
import { useAuth } from "../auth";
import { fromB64, toB64 } from "./bytes";
import { createSyncEngine, type EngineApi, type RunResult } from "./engine";
import { assertInspectionClears, deliveredTrip, endedTrip, loadedTrip, startedTrip } from "./local";
import { createStore, type FileAdapter } from "./store";
import type { DriverCache, LocalPhoto, OfflineState, QueueItem } from "./types";
import { createVault, type KeyStore } from "./vault";

const KEY_NAME = "fleettms.vaultkey";
const DIR = `${FileSystem.documentDirectory ?? ""}fleettms/`;

const keys: KeyStore = {
  get: () => SecureStore.getItemAsync(KEY_NAME),
  set: (v) => SecureStore.setItemAsync(KEY_NAME, v),
  clear: () => SecureStore.deleteItemAsync(KEY_NAME),
};

const files: FileAdapter = {
  async read(name) {
    const info = await FileSystem.getInfoAsync(DIR + name);
    return info.exists
      ? FileSystem.readAsStringAsync(DIR + name, { encoding: FileSystem.EncodingType.UTF8 })
      : null;
  },
  async write(name, base64) {
    await FileSystem.makeDirectoryAsync(DIR, { intermediates: true });
    await FileSystem.writeAsStringAsync(DIR + name, base64, {
      encoding: FileSystem.EncodingType.UTF8,
    });
  },
  remove: (name) => FileSystem.deleteAsync(DIR + name, { idempotent: true }),
  removeAll: () => FileSystem.deleteAsync(DIR, { idempotent: true }),
  async writeTemp(name, bytes) {
    const uri = `${FileSystem.cacheDirectory}${name}`;
    await FileSystem.writeAsStringAsync(uri, toB64(bytes), {
      encoding: FileSystem.EncodingType.Base64,
    });
    return { uri, cleanup: () => FileSystem.deleteAsync(uri, { idempotent: true }) };
  },
};

const store = createStore({
  files,
  vault: createVault(keys, (n) => Crypto.getRandomBytes(n)),
  uuid: () => Crypto.randomUUID(),
  now: () => new Date(),
});

const realApi: EngineApi = {
  uploadPhoto: (file, meta) => api.uploadPhoto(file, meta as never),
  sync: (actions, device) => api.sync(actions, device),
  async refresh() {
    const [vehicle, trips, checklist, float] = await Promise.all([
      api.myVehicle(),
      api.myTrips(),
      api.checklist(),
      api.myFloat().catch(() => null),
    ]);
    const trip = trips[0] ?? null;
    const vehicleId = trip?.vehicle_id ?? vehicle?.vehicle.id;
    let inspection: DriverCache["inspection"] = null;
    if (vehicleId) {
      const today = await api.inspectionToday(vehicleId).catch(() => null);
      if (today?.inspection) {
        inspection = {
          vehicleId,
          day: nairobiDay(today.inspection.performed_at),
          status: today.inspection.status,
        };
      }
    }
    return { vehicle, trip, checklist, inspection, float };
  },
};

async function isOnline(): Promise<boolean> {
  const s = await NetInfo.fetch();
  return Boolean(s.isConnected) && s.isInternetReachable !== false;
}

async function deviceReport(): Promise<DeviceReport> {
  const state = store.get();
  const rooted = await Device.isRootedExperimentalAsync().catch(() => false);
  return {
    device_id: state.deviceId,
    mock_location: state.mockSeen,
    rooted,
    device_time: new Date().toISOString(),
    app_version: Constants.expoConfig?.version ?? "dev",
    vehicle_id: state.cache.vehicle?.vehicle.id ?? null,
  };
}

const engine = createSyncEngine({ store, api: realApi, isOnline, device: deviceReport });

export interface PhotoInput {
  kind: LocalPhoto["kind"];
  uri: string;
  capturedAt: string;
  lat: number | null;
  lng: number | null;
}
export interface InspectionAnswerInput {
  itemId: string;
  label: string;
  critical: boolean;
  ok: boolean;
  note: string;
  photo: LocalPhoto | null;
}
export interface FuelFormInput {
  vehicleId: string;
  tripId: string | null;
  litres: string;
  priceCents: number;
  amountCents: number;
  station: string;
  mpesaCode: string;
  receipt: LocalPhoto | null;
}

interface Offline {
  ready: boolean;
  state: OfflineState;
  online: boolean;
  syncing: boolean;
  pending: number;
  attention: QueueItem[];
  noteMockLocation: () => void;
  capturePhoto: (input: PhotoInput) => Promise<LocalPhoto>;
  submitInspection: (
    vehicleId: string,
    answers: InspectionAnswerInput[],
  ) => Promise<"passed" | "passed_with_defects" | "blocked">;
  startTrip: (photo: LocalPhoto, value: number) => Promise<void>;
  recordLoading: (photo: LocalPhoto) => Promise<void>;
  markDelivered: () => Promise<void>;
  endTrip: (photo: LocalPhoto, value: number) => Promise<void>;
  addFuel: (input: FuelFormInput) => Promise<void>;
  syncNow: () => Promise<RunResult>;
  /** Records on the phone that have not reached the office, including ones it refused. */
  unsent: () => number;
  discard: (id: string) => Promise<void>;
  retry: (id: string) => Promise<void>;
  wipe: () => Promise<void>;
}

const OfflineContext = createContext<Offline | null>(null);

/** Keeps the driver's work safe on the phone and sends it when there is a network. Only active for drivers and turnboys. */
export function OfflineProvider({ children }: { children: ReactNode }) {
  const { me } = useAuth();
  const active = Boolean(me?.permissions.includes("trips.own"));
  const [state, setState] = useState<OfflineState>(store.get());
  const [ready, setReady] = useState(false);
  const [online, setOnline] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const userId = me?.user.id ?? null;
  const loadedFor = useRef<string | null>(null);

  const syncNow = useCallback(async (): Promise<RunResult> => {
    setSyncing(true);
    try {
      return await engine.run({ refresh: true });
    } finally {
      setSyncing(false);
    }
  }, []);

  useEffect(() => store.subscribe(() => setState(store.get())), []);

  // Load the vault once per signed-in person. Someone else's leftovers are wiped, never shown.
  useEffect(() => {
    if (!active || !userId || loadedFor.current === userId) return;
    loadedFor.current = userId;
    (async () => {
      await store.load();
      if (store.get().ownerUserId !== userId) {
        await store.clear();
        await store.load();
        await store.update((s) => ({ ...s, ownerUserId: userId }));
      }
      setReady(true);
      void syncNow();
    })();
  }, [active, userId, syncNow]);

  // Sync when the network returns, when the app comes back to the front, and every minute while it is open.
  useEffect(() => {
    if (!active) return;
    const net = NetInfo.addEventListener((s) => {
      const up = Boolean(s.isConnected) && s.isInternetReachable !== false;
      setOnline(up);
      if (up) void syncNow();
    });
    const app = AppState.addEventListener("change", (s) => s === "active" && void syncNow());
    const timer = setInterval(() => void syncNow(), 60_000);
    return () => {
      net();
      app.remove();
      clearInterval(timer);
    };
  }, [active, syncNow]);

  const value = useMemo<Offline>(() => {
    const queueAndSync = async (item: Omit<QueueItem, "id" | "status" | "attempts">) => {
      await store.enqueue(item);
      void syncNow();
    };
    const nowIso = () => new Date().toISOString();
    const cache = () => store.get().cache;
    const setCache = (patch: Partial<DriverCache>) =>
      store.update((s) => ({ ...s, cache: { ...s.cache, ...patch } }));

    return {
      ready,
      state,
      online,
      syncing,
      pending: state.queue.filter((i) => i.status === "queued").length,
      attention: state.queue.filter((i) => i.status === "rejected"),
      noteMockLocation: () => void store.update((s) => ({ ...s, mockSeen: true })),

      async capturePhoto(input) {
        const b64 = await FileSystem.readAsStringAsync(input.uri, {
          encoding: FileSystem.EncodingType.Base64,
        });
        const photo = await store.addPhoto(fromB64(b64), {
          kind: input.kind,
          capturedAt: input.capturedAt,
          lat: input.lat,
          lng: input.lng,
        });
        await FileSystem.deleteAsync(input.uri, { idempotent: true }); // the unencrypted copy is not kept
        return photo;
      },

      async submitInspection(vehicleId, answers) {
        const at = nowIso();
        const outcome = inspectionOutcome(answers);
        await queueAndSync({
          type: "inspection.submit",
          capturedAt: at,
          photoIds: answers.flatMap((a) => (a.photo ? [a.photo.clientId] : [])),
          payload: {
            vehicle_id: vehicleId,
            results: answers.map((a) => ({
              item_id: a.itemId,
              ok: a.ok,
              note: a.ok ? null : a.note.trim(),
              photo_client_id: a.photo?.clientId ?? null,
            })),
          },
        });
        await setCache({ inspection: { vehicleId, day: nairobiDay(at), status: outcome } });
        return outcome === "blocked"
          ? "blocked"
          : outcome === "passed_with_defects"
            ? "passed_with_defects"
            : "passed";
      },

      async startTrip(photo, value) {
        const c = cache();
        const at = nowIso();
        assertInspectionClears(c, c.trip?.vehicle_id ?? "", at);
        const trip = startedTrip(c.trip, value, at);
        await queueAndSync({
          type: "trip.start",
          capturedAt: at,
          photoIds: [photo.clientId],
          payload: { trip_id: trip.id, photo_client_id: photo.clientId, value },
        });
        await setCache({ trip });
      },

      async recordLoading(photo) {
        const at = nowIso();
        const trip = loadedTrip(cache().trip, at);
        await queueAndSync({
          type: "trip.loading",
          capturedAt: at,
          photoIds: [photo.clientId],
          payload: { trip_id: trip.id, photo_client_id: photo.clientId },
        });
        await setCache({ trip });
      },

      async markDelivered() {
        const at = nowIso();
        const trip = deliveredTrip(cache().trip, at);
        await queueAndSync({
          type: "trip.deliver",
          capturedAt: at,
          photoIds: [],
          payload: { trip_id: trip.id },
        });
        await setCache({ trip });
      },

      async endTrip(photo, value) {
        const at = nowIso();
        const trip = endedTrip(cache().trip, value, at);
        await queueAndSync({
          type: "trip.end",
          capturedAt: at,
          photoIds: [photo.clientId],
          payload: { trip_id: trip.id, photo_client_id: photo.clientId, value },
        });
        await setCache({ trip });
      },

      async addFuel(input) {
        const at = nowIso();
        const code = input.mpesaCode.trim() ? normalizeMpesaCode(input.mpesaCode) : null;
        if (input.mpesaCode.trim() && !code)
          throw new Error("An M-Pesa code is 10 letters and numbers, like QGH7XYZ123.");
        const clientId = Crypto.randomUUID();
        const flags = fuelFlags({
          litres: Number(input.litres),
          priceCents: input.priceCents,
          amountCents: input.amountCents,
          hasReceipt: input.receipt !== null,
        });
        await queueAndSync({
          type: "fuel.add",
          capturedAt: at,
          photoIds: input.receipt ? [input.receipt.clientId] : [],
          payload: {
            vehicle_id: input.vehicleId,
            trip_id: input.tripId,
            litres: input.litres,
            price_per_litre_cents: input.priceCents,
            amount_cents: input.amountCents,
            station: input.station.trim() || null,
            mpesa_code: code,
            receipt_photo_client_id: input.receipt?.clientId ?? null,
            client_id: clientId,
          },
        });
        await setCache({
          fuel: [
            {
              clientId,
              litres: input.litres,
              price_per_litre_cents: input.priceCents,
              amount_cents: input.amountCents,
              station: input.station || null,
              mpesa_code: code,
              flags,
              captured_at: at,
              synced: false,
            },
            ...cache().fuel,
          ].slice(0, 10),
        });
      },

      syncNow,
      unsent: () => store.get().queue.length,
      discard: (id) => store.discard(id),
      retry: async (id) => {
        await store.retry(id);
        void syncNow();
      },
      wipe: async () => {
        loadedFor.current = null;
        await store.clear();
        setReady(false);
      },
    };
  }, [ready, state, online, syncing, syncNow]);

  return <OfflineContext.Provider value={value}>{children}</OfflineContext.Provider>;
}

export function useOffline(): Offline {
  const ctx = useContext(OfflineContext);
  if (!ctx) throw new Error("useOffline must be used inside OfflineProvider");
  return ctx;
}

/** A location check that does not ask for permission: used to notice a mock-location app while the app is open. */
export async function sampleForMockLocation(note: () => void): Promise<void> {
  try {
    const perm = await Location.getForegroundPermissionsAsync();
    if (!perm.granted) return;
    const last = await Location.getLastKnownPositionAsync();
    if (last?.mocked) note();
  } catch {
    /* no fix available */
  }
}
