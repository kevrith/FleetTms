import type {
  ChecklistItem,
  ExpenseCategory,
  FuelEntry,
  InspectionStatus,
  MyFloat,
  MySheet,
  MyVehicle,
  PhotoKind,
  Trip,
} from "@fleettms/types";

export type ActionType =
  | "inspection.submit"
  | "trip.start"
  | "trip.loading"
  | "trip.deliver"
  | "trip.end"
  | "fuel.add"
  | "expense.add"
  | "reconciliation.submit"
  | "incident.report"
  | "repair.request"
  | "sos.send";

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

/** An expense as the driver sees it: waiting to be sent, or as the office has it. */
export interface LocalExpense {
  clientId: string;
  category: ExpenseCategory;
  amount_cents: number;
  note: string | null;
  status: "waiting" | "recorded" | "awaiting_approval" | "approved" | "rejected";
  flags: string[];
  spent_at: string;
}

/** What the phone shows when there is no network: the last thing the server said, plus what the driver has done since. */
export interface DriverCache {
  vehicle: MyVehicle | null;
  trip: Trip | null;
  checklist: ChecklistItem[];
  inspection: { vehicleId: string; day: string; status: InspectionStatus } | null;
  float: MyFloat | null;
  fuel: LocalFuel[];
  expenses: LocalExpense[];
  /** Today's float sheet as the office last saw it. */
  sheet: MySheet | null;
  /** Tyre positions on the driver's vehicle (no serials: the driver reads those off the tyres). */
  tyrePositions: string[];
  /** The driver's open SOS alert as the office has it. */
  sos: { id: string; acknowledged: boolean; sentAt: string } | null;
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
  expenses: [],
  sheet: null,
  tyrePositions: [],
  sos: null,
  refreshedAt: null,
});
