import type {
  ChecklistItem,
  FuelEntry,
  InspectionStatus,
  MyFloat,
  MyVehicle,
  PhotoKind,
  Trip,
} from "@fleettms/types";

export type ActionType =
  "inspection.submit" | "trip.start" | "trip.loading" | "trip.deliver" | "trip.end" | "fuel.add";

/** A photo taken on the phone, kept encrypted until it has been uploaded. */
export interface LocalPhoto {
  clientId: string;
  kind: PhotoKind;
  capturedAt: string;
  lat: number | null;
  lng: number | null;
  uploaded: boolean;
}

/** Something the driver did, waiting to be sent. `capturedAt` is when they did it, not when it syncs. */
export interface QueueItem {
  id: string;
  type: ActionType;
  payload: Record<string, unknown>;
  capturedAt: string;
  photoIds: string[];
  status: "queued" | "rejected";
  code?: string;
  message?: string;
  attempts: number;
}

/** A fuel entry as the driver sees it before the server has confirmed it. */
export type LocalFuel = Pick<
  FuelEntry,
  | "litres"
  | "price_per_litre_cents"
  | "amount_cents"
  | "station"
  | "mpesa_code"
  | "flags"
  | "captured_at"
> & {
  clientId: string;
  synced: boolean;
};

/** What the phone shows when there is no network: the last thing the server said, plus what the driver has done since. */
export interface DriverCache {
  vehicle: MyVehicle | null;
  trip: Trip | null;
  checklist: ChecklistItem[];
  inspection: { vehicleId: string; day: string; status: InspectionStatus } | null;
  float: MyFloat | null;
  fuel: LocalFuel[];
  refreshedAt: string | null;
}

export interface OfflineState {
  version: 1;
  deviceId: string;
  /** Whose work this is. A different person signing in on the same phone starts with an empty vault. */
  ownerUserId: string | null;
  queue: QueueItem[];
  photos: Record<string, LocalPhoto>;
  cache: DriverCache;
  /** A mock-location app was seen since the last report. Reported with the next sync, then cleared. */
  mockSeen: boolean;
  lastSyncAt: string | null;
}

export const emptyCache = (): DriverCache => ({
  vehicle: null,
  trip: null,
  checklist: [],
  inspection: null,
  float: null,
  fuel: [],
  refreshedAt: null,
});
