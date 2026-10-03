import type {
  AuditEntry,
  AccessInfo,
  AskAnswer,
  AskExample,
  CatalogReport,
  DataExportInfo,
  FirstJobInput,
  InboxMessage,
  PlanName,
  PlansInfo,
  PlatformBusinessDetail,
  PlatformBusinessRow,
  PlatformOverview,
  ReportData,
  SentMessage,
  SubscriptionInvoice,
  SubscriptionStatus,
  DocumentReading,
  DocumentReadingSummary,
  ExpectedFuel,
  FuelLevel,
  MonthForecast,
  QuotePreview,
  ReadableDocument,
  VehicleModelInfo,
  CurrentFuelPrice,
  FeedbackRow,
  FraudAlert,
  FraudSettings,
  FraudSummary,
  FuelPrices,
  Onboarding,
  RouteSuggestion,
  Scorecards,
  VehicleBaselines,
  BehaviourEvent,
  BehaviourSummary,
  Geofence,
  GeofenceEvent,
  GeofenceInput,
  ImmobiliserCommand,
  ImmobiliserState,
  Replay,
  TrackerAlert,
  TrackerDevice,
  TrackerInput,
  ChecklistItem,
  ComplianceDocument,
  CrewAssignment,
  CrewRole,
  Dashboard,
  Depot,
  DeviceReport,
  DocumentInput,
  Expense,
  ExpenseInput,
  FloatTransfer,
  FuelEntry,
  FuelInput,
  HealthResponse,
  ImportResult,
  ReportSchedule,
  Inspection,
  InspectionAnswer,
  InviteInput,
  Me,
  MyFloat,
  MySheet,
  MyVehicle,
  Party,
  PartyInput,
  PendingDocument,
  PhotoRef,
  PhotoUpload,
  ProfileInput,
  ReadingInput,
  Reconciliation,
  ReconciliationDetail,
  ReportSummary,
  Role,
  RouteCost,
  ServiceHistory,
  ServiceInput,
  ServiceSchedule,
  SpendLimit,
  SignupInput,
  StaffMember,
  StaffProfile,
  SupportGrant,
  SyncAction,
  SyncResponse,
  TokenResponse,
  Tokens,
  Trip,
  TripInput,
  Vehicle,
  VehicleInput,
  VehicleTrust,
  WorkOrder,
  Tyre,
  TyreReport,
  TyreAlert,
  TyreStatus,
  Part,
  StockMovement,
  UnfittedPart,
  StockCountResult,
  Incident,
  IncidentType,
  InsuranceClaim,
  ClaimStatus,
  FinesSummary,
  SosAlert,
  DeliveryFollow,
  Debtors,
  FinanceAgreement,
  LeaseAgreement,
  LeaseDetail,
  LeaseEntry,
  LeaseStatement,
  LiveMap,
  OwnershipCost,
  PartsOrder,
  PayrollRun,
  PortalLease,
  ProfitReport,
  SalaryAdvance,
  Supplier,
  TrackingGapRow,
  TrackingLinkRow,
  TrackingStatus,
  TripTrack,
  DebtorDetail,
  EtimsSubmission,
  EtimsSummary,
  Invoice,
  MpesaPayment,
  PaymentSettings,
  StatementImport,
  StatementLine,
  ProofOfDeliveryInput,
  Client,
  SavedRoute,
  Quote,
  QuoteDefaults,
  Job,
  JobStatus,
  QuoteStatus,
  DispatchCalendar,
  Availability,
  VehicleBrief,
  MySos,
  MyTyrePositions,
} from "@fleettms/types";

/** Where tokens live. Web uses localStorage, mobile uses the secure keystore. */
export interface TokenStore {
  get(): Promise<Tokens | null>;
  set(tokens: Tokens | null): Promise<void>;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

export interface ApiClientOptions {
  store?: TokenStore;
  /** Called when the session can no longer be refreshed, so the app can show the sign-in screen. */
  onSignedOut?: () => void;
  fetchImpl?: typeof fetch;
}

const GENERIC_ERROR = "Something went wrong. Please try again.";

function toApiError(status: number, body: unknown): ApiError {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const d = detail as { code?: string; message?: string };
    return new ApiError(status, d.code ?? "error", d.message ?? GENERIC_ERROR);
  }
  if (status === 422)
    return new ApiError(status, "validation", "Please check the form and try again.");
  return new ApiError(status, "error", GENERIC_ERROR);
}

export function createApiClient(baseUrl: string, options: ApiClientOptions = {}) {
  const doFetch = options.fetchImpl ?? fetch;
  let refreshing: Promise<boolean> | null = null;

  async function send(method: string, path: string, body: unknown, accessToken?: string) {
    const headers: Record<string, string> = {};
    const isForm = typeof FormData !== "undefined" && body instanceof FormData;
    if (body !== undefined && !isForm) headers["Content-Type"] = "application/json";
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
    return doFetch(`${baseUrl}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
    });
  }

  /** One refresh at a time, so parallel 401s do not burn the rotating refresh token twice. */
  function refresh(): Promise<boolean> {
    refreshing ??= (async () => {
      try {
        const current = await options.store?.get();
        if (!current) return false;
        const res = await send("POST", "/auth/refresh", { refresh_token: current.refresh_token });
        if (!res.ok) {
          await options.store?.set(null);
          return false;
        }
        const next = (await res.json()) as TokenResponse;
        await options.store?.set({
          access_token: next.access_token,
          refresh_token: next.refresh_token,
        });
        return true;
      } finally {
        refreshing = null;
      }
    })();
    return refreshing;
  }

  async function request<T>(
    method: string,
    path: string,
    body?: unknown,
    auth = true,
    asBlob = false,
  ): Promise<T> {
    let tokens = auth ? await options.store?.get() : null;
    let res = await send(method, path, body, tokens?.access_token);
    if (auth && res.status === 401 && tokens) {
      if (await refresh()) {
        tokens = await options.store?.get();
        res = await send(method, path, body, tokens?.access_token);
      } else {
        options.onSignedOut?.();
      }
    }
    if (res.status === 204) return undefined as T;
    if (asBlob && res.ok) return (await res.blob()) as T;
    const data = await res.json().catch(() => null);
    if (!res.ok) throw toApiError(res.status, data);
    return data as T;
  }

  async function startSession(res: TokenResponse): Promise<TokenResponse> {
    await options.store?.set({ access_token: res.access_token, refresh_token: res.refresh_token });
    return res;
  }

  const get = <T>(path: string) => request<T>("GET", path);
  const post = <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {});

  return {
    health: () => request<HealthResponse>("GET", "/health", undefined, false),

    // ---- sign in / out ----
    signup: async (input: SignupInput) =>
      startSession(await request<TokenResponse>("POST", "/auth/signup", input, false)),
    login: async (input: {
      identifier: string;
      password: string;
      totp_code?: string;
      sms_code?: string;
      business_id?: string;
      device_label?: string;
    }) => startSession(await request<TokenResponse>("POST", "/auth/login", input, false)),
    otpRequest: (phone: string) =>
      request<{ message: string }>("POST", "/auth/otp/request", { phone }, false),
    otpVerify: async (input: {
      phone: string;
      code: string;
      business_id?: string;
      device_label?: string;
    }) => startSession(await request<TokenResponse>("POST", "/auth/otp/verify", input, false)),
    /** Sign in with the PIN and the secret this phone was given when quick sign-in was turned on. */
    quickLogin: async (input: {
      phone: string;
      device_id: string;
      device_secret: string;
      pin: string;
      business_id?: string;
      device_label?: string;
    }) => startSession(await request<TokenResponse>("POST", "/auth/quick-login", input, false)),
    quickLoginEnable: (input: { device_id: string; pin: string; device_label?: string }) =>
      post<{ device_secret: string }>("/auth/quick-login/enable", input),
    quickLoginDisable: (deviceId: string) =>
      request<void>("POST", "/auth/quick-login/disable", { device_id: deviceId }),
    quickLoginStatus: (deviceId: string) =>
      get<{ enabled: boolean }>(
        `/auth/quick-login/status?device_id=${encodeURIComponent(deviceId)}`,
      ),
    acceptInvite: (token: string, password: string) =>
      request<void>("POST", "/auth/accept-invite", { token, password }, false),
    logout: async () => {
      try {
        await post<void>("/auth/logout");
      } finally {
        await options.store?.set(null);
      }
    },
    logoutAll: async () => {
      try {
        await post<void>("/auth/logout-all");
      } finally {
        await options.store?.set(null);
      }
    },
    me: () => get<Me>("/auth/me"),
    switchCompany: (businessId: string) =>
      post<{ business_id: string; mfa_setup_required: boolean }>("/auth/switch-company", {
        business_id: businessId,
      }),
    twoFactorSetup: () => post<{ secret: string; otpauth_uri: string }>("/auth/2fa/setup"),
    twoFactorConfirm: (code: string) => post<void>("/auth/2fa/confirm", { code }),
    smsTwoFactorSetup: () => post<{ message: string }>("/auth/2fa/sms/setup"),
    smsTwoFactorConfirm: (code: string) => post<void>("/auth/2fa/sms/confirm", { code }),

    // ---- people and places ----
    users: () => get<StaffMember[]>("/users"),
    inviteUser: (input: InviteInput) => post<StaffMember>("/users", input),
    setRoles: (membershipId: string, roles: Role[], vehicleScope?: string[] | null) =>
      request<StaffMember>("PUT", `/users/${membershipId}/roles`, {
        roles,
        vehicle_scope: vehicleScope ?? null,
      }),
    removeUser: (membershipId: string) => request<void>("DELETE", `/users/${membershipId}`),
    depots: () => get<Depot[]>("/depots"),
    createDepot: (input: { name: string; location?: string | null }) =>
      post<Depot>("/depots", input),
    updateDepot: (id: string, input: { name: string; location?: string | null }) =>
      request<Depot>("PUT", `/depots/${id}`, input),
    deleteDepot: (id: string) => request<void>("DELETE", `/depots/${id}`),

    // ---- vehicles, lessors, crew ----
    vehicles: () => get<Vehicle[]>("/vehicles"),
    vehicle: (id: string) => get<Vehicle>(`/vehicles/${id}`),
    createVehicle: (input: VehicleInput) => post<Vehicle>("/vehicles", input),
    updateVehicle: (id: string, input: VehicleInput) =>
      request<Vehicle>("PUT", `/vehicles/${id}`, input),
    parties: () => get<Party[]>("/parties"),
    createParty: (input: PartyInput) => post<Party>("/parties", input),
    updateParty: (id: string, input: PartyInput) => request<Party>("PUT", `/parties/${id}`, input),
    crew: (vehicleId: string) => get<CrewAssignment[]>(`/vehicles/${vehicleId}/crew`),
    assignCrew: (vehicleId: string, membershipId: string, role: CrewRole) =>
      post<CrewAssignment>(`/vehicles/${vehicleId}/crew`, { membership_id: membershipId, role }),
    unassignCrew: (vehicleId: string, role: CrewRole) =>
      request<void>("DELETE", `/vehicles/${vehicleId}/crew/${role}`),
    myVehicle: () => get<MyVehicle | null>("/me/vehicle"),

    // ---- staff and documents ----
    staff: () => get<StaffProfile[]>("/staff"),
    updateStaffProfile: (membershipId: string, input: ProfileInput) =>
      request<StaffProfile>("PUT", `/staff/${membershipId}/profile`, input),
    documents: (owner: { vehicleId: string } | { membershipId: string }) =>
      get<ComplianceDocument[]>(
        "vehicleId" in owner
          ? `/documents?vehicle_id=${owner.vehicleId}`
          : `/documents?membership_id=${owner.membershipId}`,
      ),
    expiringDocuments: (days = 30) => get<ComplianceDocument[]>(`/documents/expiring?days=${days}`),
    createDocument: (input: DocumentInput) => post<ComplianceDocument>("/documents", input),
    updateDocument: (id: string, input: DocumentInput) =>
      request<ComplianceDocument>("PUT", `/documents/${id}`, input),
    deleteDocument: (id: string) => request<void>("DELETE", `/documents/${id}`),

    // ---- Excel import ----
    importTemplate: (kind: "vehicles" | "staff") =>
      request<Blob>("GET", `/imports/${kind}/template`, undefined, true, true),
    importFile: (kind: "vehicles" | "staff", file: Blob, dryRun: boolean) => {
      const form = new FormData();
      form.append("file", file);
      return request<ImportResult>("POST", `/imports/${kind}?dry_run=${dryRun}`, form);
    },

    // ---- photos, inspections, trips ----
    /** Turns a relative photo link from the API into an address an image view can load. */
    mediaUrl: (path: string) => `${baseUrl}${path}`,
    /** `file` is a Blob on the web, or { uri, name, type } in React Native. */
    uploadPhoto: (file: unknown, meta: PhotoUpload & { client_id?: string; offline?: boolean }) => {
      const form = new FormData();
      form.append("kind", meta.kind);
      form.append("source", meta.source);
      if (meta.captured_at) form.append("captured_at", meta.captured_at);
      if (meta.lat != null && meta.lng != null) {
        form.append("lat", String(meta.lat));
        form.append("lng", String(meta.lng));
      }
      if (meta.client_id) form.append("client_id", meta.client_id);
      if (meta.offline) form.append("offline", "true");
      form.append("file", file as never);
      return request<PhotoRef>("POST", "/photos", form);
    },
    checklist: (includeInactive = false) =>
      get<ChecklistItem[]>(
        `/inspection/checklist${includeInactive ? "?include_inactive=true" : ""}`,
      ),
    addChecklistItem: (input: Omit<ChecklistItem, "id">) =>
      post<ChecklistItem>("/inspection/checklist", input),
    updateChecklistItem: (id: string, input: Omit<ChecklistItem, "id">) =>
      request<ChecklistItem>("PUT", `/inspection/checklist/${id}`, input),
    submitInspection: (vehicleId: string, results: InspectionAnswer[], notes?: string) =>
      post<Inspection>(`/vehicles/${vehicleId}/inspections`, { results, notes: notes ?? null }),
    inspections: (vehicleId: string) => get<Inspection[]>(`/vehicles/${vehicleId}/inspections`),
    inspectionToday: (vehicleId: string) =>
      get<{ inspection: Inspection | null; can_start_trip: boolean }>(
        `/vehicles/${vehicleId}/inspections/today`,
      ),
    overrideInspection: (id: string, reason: string) =>
      post<Inspection>(`/inspections/${id}/override`, { reason }),
    trips: (params: { status?: string; vehicleId?: string } = {}) => {
      const q = new URLSearchParams();
      if (params.status) q.set("status_filter", params.status);
      if (params.vehicleId) q.set("vehicle_id", params.vehicleId);
      const qs = q.toString();
      return get<Trip[]>(`/trips${qs ? `?${qs}` : ""}`);
    },
    myTrips: () => get<Trip[]>("/me/trips"),
    trip: (id: string) => get<Trip>(`/trips/${id}`),
    createTrip: (input: TripInput) => post<Trip>("/trips", input),
    startTrip: (id: string, reading: ReadingInput) => post<Trip>(`/trips/${id}/start`, reading),
    recordLoading: (
      id: string,
      photoId: string,
      loadedWeightKg?: number | null,
      weighbridgePhotoId?: string | null,
    ) =>
      post<Trip>(`/trips/${id}/loading`, {
        photo_id: photoId,
        loaded_weight_kg: loadedWeightKg ?? null,
        weighbridge_photo_id: weighbridgePhotoId ?? null,
      }),
    deliverTrip: (id: string, pod?: ProofOfDeliveryInput) =>
      post<Trip>(`/trips/${id}/deliver`, pod ? { pod } : undefined),
    requestPodCode: (id: string) =>
      post<{ sent_to_last4: string; expires_in_s: number }>(`/trips/${id}/pod/code`),
    tripInvoice: (id: string) => get<{ invoice: Invoice | null }>(`/trips/${id}/invoice`),
    invoiceTrip: (id: string, weightKg?: number) =>
      post<Invoice>(`/trips/${id}/invoice`, { weight_kg: weightKg ?? null }),
    endTrip: (id: string, reading: ReadingInput) => post<Trip>(`/trips/${id}/end`, reading),
    cancelTrip: (id: string) => post<Trip>(`/trips/${id}/cancel`),

    // ---- fuel, floats, sync, device checks ----
    fuel: (vehicleId?: string) =>
      get<FuelEntry[]>(`/fuel${vehicleId ? `?vehicle_id=${vehicleId}` : ""}`),
    addFuel: (input: FuelInput) => post<FuelEntry>("/fuel", input),
    floats: (driverMembershipId?: string) =>
      get<FloatTransfer[]>(
        `/floats${driverMembershipId ? `?driver_membership_id=${driverMembershipId}` : ""}`,
      ),
    sendFloat: (input: {
      driver_membership_id: string;
      amount_cents: number;
      mpesa_code?: string | null;
      note?: string | null;
    }) => post<FloatTransfer>("/floats", input),
    myFloat: () => get<MyFloat>("/me/float"),
    vehicleTrust: (vehicleId: string) => get<VehicleTrust>(`/vehicles/${vehicleId}/trust`),
    reportDevice: (report: DeviceReport) =>
      post<{ flags: string[]; server_time: string }>("/devices/integrity", report),
    sync: (actions: SyncAction[], device?: DeviceReport) =>
      post<SyncResponse>("/sync", { actions, device: device ?? null }),

    // ---- expenses, reconciliation ----
    expenses: (
      params: {
        vehicleId?: string;
        status?: string;
        day?: string;
        driverMembershipId?: string;
      } = {},
    ) => {
      const q = new URLSearchParams();
      if (params.vehicleId) q.set("vehicle_id", params.vehicleId);
      if (params.status) q.set("status_filter", params.status);
      if (params.day) q.set("day", params.day);
      if (params.driverMembershipId) q.set("driver_membership_id", params.driverMembershipId);
      const qs = q.toString();
      return get<Expense[]>(`/expenses${qs ? `?${qs}` : ""}`);
    },
    myExpenses: () => get<Expense[]>("/me/expenses"),
    addExpense: (input: ExpenseInput) => post<Expense>("/expenses", input),
    decideExpense: (id: string, approve: boolean, note?: string) =>
      post<Expense>(`/expenses/${id}/decision`, { approve, note: note ?? null }),
    spendLimits: () => get<SpendLimit[]>("/spend-limits"),
    setSpendLimits: (limits: SpendLimit[]) =>
      request<SpendLimit[]>(
        "PUT",
        "/spend-limits",
        limits.map(({ category, role, limit_cents }) => ({ category, role, limit_cents })),
      ),
    routeCosts: () => get<RouteCost[]>("/route-costs"),
    addRouteCost: (input: Omit<RouteCost, "id">) => post<RouteCost>("/route-costs", input),
    deleteRouteCost: (id: string) => request<void>("DELETE", `/route-costs/${id}`),
    mySheet: (day?: string) => get<MySheet>(`/me/reconciliation${day ? `?day=${day}` : ""}`),
    submitSheet: (day?: string) =>
      post<Reconciliation>("/me/reconciliation/submit", day ? { day } : {}),
    reconciliations: (status?: string) =>
      get<Reconciliation[]>(`/reconciliations${status ? `?status_filter=${status}` : ""}`),
    reconciliation: (id: string) => get<ReconciliationDetail>(`/reconciliations/${id}`),
    approveReconciliation: (
      id: string,
      balanceAction: "carry_forward" | "returned",
      note?: string,
    ) =>
      post<Reconciliation>(`/reconciliations/${id}/approve`, {
        balance_action: balanceAction,
        note: note ?? null,
      }),
    rejectReconciliation: (id: string, note: string) =>
      post<Reconciliation>(`/reconciliations/${id}/reject`, { note }),

    // ---- workshop and service ----
    workOrders: (params: { openOnly?: boolean; vehicleId?: string } = {}) => {
      const q = new URLSearchParams();
      if (params.openOnly) q.set("open_only", "true");
      if (params.vehicleId) q.set("vehicle_id", params.vehicleId);
      const qs = q.toString();
      return get<WorkOrder[]>(`/work-orders${qs ? `?${qs}` : ""}`);
    },
    createWorkOrder: (input: {
      vehicle_id: string;
      title: string;
      description?: string | null;
      priority?: string;
    }) => post<WorkOrder>("/work-orders", input),
    updateWorkOrder: (id: string, input: Record<string, unknown>) =>
      request<WorkOrder>("PUT", `/work-orders/${id}`, input),
    completeWorkOrder: (
      id: string,
      input: { odometer_km?: number | null; labour_cents?: number | null; notes?: string | null },
    ) => post<WorkOrder>(`/work-orders/${id}/complete`, input),
    serviceSchedules: (dueOnly = false) =>
      get<ServiceSchedule[]>(`/service-schedules${dueOnly ? "?due_only=true" : ""}`),
    vehicleServices: (vehicleId: string) => get<ServiceHistory>(`/vehicles/${vehicleId}/services`),
    addServiceSchedule: (vehicleId: string, input: ServiceInput) =>
      post<ServiceSchedule>(`/vehicles/${vehicleId}/services`, input),

    // ---- dashboard and reports ----
    dashboard: () => get<Dashboard>("/dashboard"),
    reportSummary: (from: string, to: string) =>
      get<ReportSummary>(`/reports/summary?from=${from}&to=${to}`),
    exportReport: (from: string, to: string, format: "xlsx" | "pdf") =>
      request<Blob>(
        "GET",
        `/reports/export?from=${from}&to=${to}&format=${format}`,
        undefined,
        true,
        true,
      ),

    reportSchedules: () => get<ReportSchedule[]>("/report-schedules"),
    createReportSchedule: (
      input: Pick<ReportSchedule, "frequency" | "channel" | "recipient" | "report" | "file_format">,
    ) => post<ReportSchedule>("/report-schedules", input),
    setReportScheduleActive: (id: string, isActive: boolean) =>
      request<ReportSchedule>("PATCH", `/report-schedules/${id}`, { is_active: isActive }),
    deleteReportSchedule: (id: string) => request<void>("DELETE", `/report-schedules/${id}`),
    sendReportScheduleNow: (id: string) =>
      post<{ sent: boolean }>(`/report-schedules/${id}/send-now`),

    workshopVehicles: () => get<VehicleBrief[]>("/workshop/vehicles"),

    // ---- tyres ----
    tyres: (params: { status?: TyreStatus; vehicleId?: string } = {}) => {
      const q = new URLSearchParams();
      if (params.status) q.set("status_filter", params.status);
      if (params.vehicleId) q.set("vehicle_id", params.vehicleId);
      const qs = q.toString();
      return get<Tyre[]>(`/tyres${qs ? `?${qs}` : ""}`);
    },
    addTyre: (input: {
      serial: string;
      brand: string;
      size: string;
      cost_cents: number;
      supplier?: string | null;
    }) => post<Tyre>("/tyres", input),
    tyreHistory: (id: string) =>
      get<
        Tyre & {
          history: {
            kind: string;
            position: string | null;
            odometer_km: number | null;
            tread_mm: number | null;
            cost_cents: number | null;
            note: string | null;
            occurred_at: string;
          }[];
        }
      >(`/tyres/${id}`),
    fitTyre: (id: string, input: { vehicle_id: string; position: string; odometer_km?: number }) =>
      post<Tyre>(`/tyres/${id}/fit`, input),
    removeTyre: (id: string, input: { scrap?: boolean; note?: string; odometer_km?: number }) =>
      post<Tyre>(`/tyres/${id}/remove`, input),
    rotateTyre: (id: string, position: string) => post<Tyre>(`/tyres/${id}/rotate`, { position }),
    tyreTread: (id: string, treadMm: string) =>
      post<Tyre>(`/tyres/${id}/tread`, { tread_mm: treadMm }),
    retreadTyre: (id: string, costCents: number) =>
      post<Tyre>(`/tyres/${id}/retread`, { cost_cents: costCents }),
    tyreReport: () => get<TyreReport>("/tyres/report"),
    tyreAlerts: (openOnly = true) => get<TyreAlert[]>(`/tyre-alerts?open_only=${openOnly}`),
    resolveTyreAlert: (id: string, note?: string) =>
      post<TyreAlert>(`/tyre-alerts/${id}/resolve`, { note }),

    // ---- spare parts store ----
    parts: (lowStock = false) => get<Part[]>(`/parts${lowStock ? "?low_stock=true" : ""}`),
    addPart: (input: {
      name: string;
      sku?: string | null;
      unit?: string;
      reorder_level?: number;
      supplier?: string | null;
    }) => post<Part>("/parts", input),
    receivePart: (
      id: string,
      input: { quantity: number; unit_cost_cents: number; note?: string },
    ) => post<Part>(`/parts/${id}/receive`, input),
    stockMovements: (partId?: string) =>
      get<StockMovement[]>(`/parts/movements${partId ? `?part_id=${partId}` : ""}`),
    countStock: (counts: { part_id: string; counted: number }[]) =>
      post<StockCountResult>("/parts/counts", { counts }),
    unfittedParts: () => get<UnfittedPart[]>("/parts/unfitted"),
    issuePart: (workOrderId: string, partId: string, quantity: number) =>
      post<WorkOrder>(`/work-orders/${workOrderId}/issue`, { part_id: partId, quantity }),
    markPartFitted: (workOrderId: string, rowId: string, fitted: boolean) =>
      post<WorkOrder>(`/work-orders/${workOrderId}/parts/${rowId}/fitted`, { fitted }),
    returnPart: (workOrderId: string, rowId: string) =>
      post<WorkOrder>(`/work-orders/${workOrderId}/parts/${rowId}/return`),

    // ---- incidents, fines, claims ----
    incidents: (params: { type?: IncidentType; status?: string } = {}) => {
      const q = new URLSearchParams();
      if (params.type) q.set("type_filter", params.type);
      if (params.status) q.set("status_filter", params.status);
      const qs = q.toString();
      return get<Incident[]>(`/incidents${qs ? `?${qs}` : ""}`);
    },
    incident: (id: string) => get<Incident>(`/incidents/${id}`),
    reportIncident: (input: Record<string, unknown>) => post<Incident>("/incidents", input),
    setFine: (
      id: string,
      input: {
        fine_amount_cents: number | null;
        fine_payer: "business" | "driver" | null;
        deduct_from_payroll?: boolean;
        reference?: string;
      },
    ) => request<Incident>("PUT", `/incidents/${id}/fine`, input),
    resolveIncident: (id: string, input: { note?: string; cost_cents?: number }) =>
      post<Incident>(`/incidents/${id}/resolve`, input),
    finesSummary: () => get<FinesSummary>("/fines/summary"),
    claims: () => get<InsuranceClaim[]>("/claims"),
    fileClaim: (
      incidentId: string,
      input: { insurer: string; policy_no?: string; amount_claimed_cents?: number; notes?: string },
    ) => post<InsuranceClaim>(`/incidents/${incidentId}/claims`, input),
    updateClaim: (
      id: string,
      input: {
        status?: ClaimStatus;
        claim_no?: string;
        amount_paid_cents?: number;
        amount_claimed_cents?: number;
        notes?: string;
      },
    ) => request<InsuranceClaim>("PUT", `/claims/${id}`, input),

    // ---- clients, quotes, jobs, dispatch ----
    clients: () => get<Client[]>("/clients"),
    client: (id: string) => get<Client>(`/clients/${id}`),
    addClient: (input: Record<string, unknown>) => post<Client>("/clients", input),
    updateClient: (id: string, input: Record<string, unknown>) =>
      request<Client>("PUT", `/clients/${id}`, input),
    routes: () => get<SavedRoute[]>("/routes"),
    addRoute: (clientId: string, input: Record<string, unknown>) =>
      post<SavedRoute>(`/clients/${clientId}/routes`, input),
    updateRoute: (id: string, input: Record<string, unknown>) =>
      request<SavedRoute>("PUT", `/routes/${id}`, input),
    quoteDefaults: (clientId: string, routeId?: string, vehicleId?: string) => {
      const q = new URLSearchParams({ client_id: clientId });
      if (routeId) q.set("route_id", routeId);
      if (vehicleId) q.set("vehicle_id", vehicleId);
      return get<QuoteDefaults>(`/quotes/defaults?${q.toString()}`);
    },
    quotes: (status?: QuoteStatus) =>
      get<Quote[]>(`/quotes${status ? `?status_filter=${status}` : ""}`),
    quote: (id: string) => get<Quote>(`/quotes/${id}`),
    createQuote: (input: Record<string, unknown>) => post<Quote>("/quotes", input),
    updateQuote: (id: string, input: Record<string, unknown>) =>
      request<Quote>("PUT", `/quotes/${id}`, input),
    sendQuote: (id: string, channel: "email" | "whatsapp" | "sms", recipient?: string) =>
      post<Quote>(`/quotes/${id}/send`, { channel, recipient: recipient || null }),
    acceptQuote: (id: string) => post<{ quote: Quote; job: Job }>(`/quotes/${id}/accept`),
    declineQuote: (id: string, note?: string) => post<Quote>(`/quotes/${id}/decline`, { note }),
    jobs: (params: { status?: JobStatus; openOnly?: boolean } = {}) => {
      const q = new URLSearchParams();
      if (params.status) q.set("status_filter", params.status);
      if (params.openOnly) q.set("open_only", "true");
      const qs = q.toString();
      return get<Job[]>(`/jobs${qs ? `?${qs}` : ""}`);
    },
    job: (id: string) => get<Job>(`/jobs/${id}`),
    createJob: (input: Record<string, unknown>) => post<Job>("/jobs", input),
    updateJob: (id: string, input: Record<string, unknown>) =>
      request<Job>("PUT", `/jobs/${id}`, input),
    cancelJob: (id: string) => post<Job>(`/jobs/${id}/cancel`),
    repeatJob: (id: string, input: { pickup_at?: string | null; deliver_by?: string | null }) =>
      post<Job>(`/jobs/${id}/repeat`, input),
    dispatchJob: (
      id: string,
      input: {
        vehicle_id: string;
        scheduled_for: string;
        driver_membership_id?: string | null;
        turnboy_membership_id?: string | null;
      },
    ) => post<Job>(`/jobs/${id}/dispatch`, input),
    calendar: (from: string, to: string) =>
      get<DispatchCalendar>(`/dispatch/calendar?from=${from}&to=${to}`),
    available: (start: string, hours: number) =>
      get<Availability>(`/dispatch/available?start=${encodeURIComponent(start)}&hours=${hours}`),

    // ---- invoices ----
    invoices: (params: { status?: string; unpaidOnly?: boolean; clientId?: string } = {}) => {
      const q = new URLSearchParams();
      if (params.status) q.set("status_filter", params.status);
      if (params.unpaidOnly) q.set("unpaid_only", "true");
      if (params.clientId) q.set("client_id", params.clientId);
      const qs = q.toString();
      return get<Invoice[]>(`/invoices${qs ? `?${qs}` : ""}`);
    },
    invoice: (id: string) => get<Invoice>(`/invoices/${id}`),
    invoicePdf: (id: string) => request<Blob>("GET", `/invoices/${id}/pdf`, undefined, true, true),
    addPayment: (
      id: string,
      input: {
        amount_cents: number;
        method: "cash" | "mpesa" | "bank" | "cheque";
        reference?: string | null;
        received_on?: string | null;
        note?: string | null;
      },
    ) => post<Invoice>(`/invoices/${id}/payments`, input),
    voidInvoice: (id: string, reason: string) => post<Invoice>(`/invoices/${id}/void`, { reason }),
    sendInvoice: (id: string, channel: "email" | "whatsapp" | "sms", recipient?: string) =>
      post<Invoice>(`/invoices/${id}/send`, { channel, recipient: recipient || null }),
    runContractInvoices: (month: string) =>
      post<{ month: string; issued: Invoice[] }>("/invoices/contracts/run", { month }),

    remindInvoice: (id: string, channels: ("sms" | "email")[]) =>
      post<{
        sent: { channel: string; recipient: string; status: string; error: string | null }[];
      }>(`/invoices/${id}/remind`, { channels }),

    // ---- client payments, debtors, statements, eTIMS ----
    mpesaPayments: (status?: string) =>
      get<MpesaPayment[]>(`/payments/mpesa${status ? `?status_filter=${status}` : ""}`),
    mpesaPayment: (id: string) => get<MpesaPayment>(`/payments/mpesa/${id}`),
    matchPayment: (id: string, invoiceId: string, amountCents?: number) =>
      post<MpesaPayment>(`/payments/mpesa/${id}/match`, {
        invoice_id: invoiceId,
        amount_cents: amountCents ?? null,
      }),
    dismissPayment: (id: string, reason: string) =>
      post<MpesaPayment>(`/payments/mpesa/${id}/dismiss`, { reason }),
    paymentSettings: () => get<PaymentSettings>("/payments/settings"),
    savePaymentSettings: (input: Partial<PaymentSettings>) =>
      request<PaymentSettings>("PUT", "/payments/settings", input),
    registerDarajaUrls: () =>
      post<{ registered_at: string }>("/payments/settings/register-urls", {}),
    simulatePayment: (amountCents: number, billRef: string) =>
      post<MpesaPayment | { sent_to_safaricom: boolean }>("/payments/simulate", {
        amount_cents: amountCents,
        bill_ref: billRef,
      }),
    debtors: () => get<Debtors>("/debtors"),
    debtor: (clientId: string) => get<DebtorDetail>(`/debtors/${clientId}`),
    uploadStatement: (file: Blob) => {
      const form = new FormData();
      form.append("file", file);
      return request<StatementImport>("POST", "/payments/statements", form);
    },
    statementImports: () => get<StatementImport[]>("/payments/statements"),
    statementLines: (params: { state?: string; direction?: "in" | "out" } = {}) => {
      const q = new URLSearchParams();
      if (params.state) q.set("state", params.state);
      if (params.direction) q.set("direction", params.direction);
      const qs = q.toString();
      return get<StatementLine[]>(`/payments/statements/lines${qs ? `?${qs}` : ""}`);
    },
    ignoreStatementLine: (id: string, note: string) =>
      post<StatementLine>(`/payments/statements/lines/${id}/ignore`, { note }),
    etimsSubmissions: (status?: string) =>
      get<EtimsSubmission[]>(`/etims/submissions${status ? `?status_filter=${status}` : ""}`),
    etimsSummary: () => get<EtimsSummary>("/etims/summary"),
    etimsConnect: () => post<{ connected_at: string }>("/etims/connect", {}),
    etimsRetry: (id: string) => post<EtimsSubmission>(`/etims/submissions/${id}/retry`, {}),
    etimsResolve: (id: string, note: string, receiptNo?: string) =>
      post<EtimsSubmission>(`/etims/submissions/${id}/resolve`, {
        note,
        receipt_no: receiptNo || null,
      }),

    // ---- leases, loans, ownership costs, profit ----
    leaseItems: () =>
      get<{ items: Record<string, string>; defaults: Record<string, "lessee" | "lessor"> }>(
        "/leases/responsibility-items",
      ),
    leases: () => get<LeaseAgreement[]>("/leases"),
    lease: (id: string) => get<LeaseDetail>(`/leases/${id}`),
    createLease: (input: Record<string, unknown>) => post<LeaseAgreement>("/leases", input),
    updateLease: (id: string, input: Record<string, unknown>) =>
      request<LeaseAgreement>("PUT", `/leases/${id}`, input),
    endLease: (id: string, endDate?: string) =>
      post<LeaseAgreement>(`/leases/${id}/end`, { end_date: endDate ?? null }),
    runLease: (
      id: string,
      month: string,
      reported?: { trips: number; km: number; revenue_cents: number; profit_cents: number },
    ) =>
      post<{ charge: LeaseEntry; offsets: LeaseEntry[] }>(`/leases/${id}/run`, {
        month,
        reported: reported ?? null,
      }),
    runAllLeases: (month: string) =>
      post<{ month: string; done: number; waiting_for_lessee_figures: string[] }>(
        "/leases/run-month",
        { month },
      ),
    leasePayment: (
      id: string,
      input: {
        amount_cents: number;
        method: "mpesa" | "bank" | "cash" | "cheque";
        mpesa_code?: string | null;
        reference?: string | null;
        received_on?: string | null;
      },
    ) => post<LeaseEntry>(`/leases/${id}/payments`, input),
    leaseAdjustment: (id: string, amountCents: number, reason: string) =>
      post<LeaseEntry>(`/leases/${id}/adjustments`, { amount_cents: amountCents, reason }),
    leaseStatement: (id: string, month: string) =>
      get<LeaseStatement>(`/leases/${id}/statement?month=${month}`),
    leaseStatementPdf: (id: string, month: string) =>
      request<Blob>("GET", `/leases/${id}/statement.pdf?month=${month}`, undefined, true, true),
    sendLeaseStatement: (id: string, month: string, channel: "email" | "whatsapp") =>
      post<{ sent: boolean; to: string }>(`/leases/${id}/statement/send`, { month, channel }),
    loans: () => get<FinanceAgreement[]>("/finance"),
    loan: (id: string) => get<FinanceAgreement>(`/finance/${id}`),
    createLoan: (input: Record<string, unknown>) => post<FinanceAgreement>("/finance", input),
    repayLoan: (
      id: string,
      number: number,
      input: {
        amount_cents?: number | null;
        method: "mpesa" | "bank" | "cash" | "cheque";
        mpesa_code?: string | null;
        reference?: string | null;
      },
    ) => post<FinanceAgreement>(`/finance/${id}/instalments/${number}/pay`, input),
    ownershipCosts: (vehicleId?: string) =>
      get<OwnershipCost[]>(`/ownership-costs${vehicleId ? `?vehicle_id=${vehicleId}` : ""}`),
    addOwnershipCost: (input: Record<string, unknown>) =>
      post<OwnershipCost>("/ownership-costs", input),
    deleteOwnershipCost: (id: string) => request<void>("DELETE", `/ownership-costs/${id}`),
    profit: (fromMonth?: string, toMonth?: string, includeTrips = false) => {
      const q = new URLSearchParams();
      if (fromMonth) q.set("from_month", fromMonth);
      if (toMonth) q.set("to_month", toMonth);
      if (includeTrips) q.set("include_trips", "true");
      const qs = q.toString();
      return get<ProfitReport>(`/profit${qs ? `?${qs}` : ""}`);
    },

    // ---- payroll ----
    payrollRuns: () => get<PayrollRun[]>("/payroll/runs"),
    payrollRun: (id: string) => get<PayrollRun>(`/payroll/runs/${id}`),
    createPayrollRun: (month: string) => post<PayrollRun>("/payroll/runs", { month }),
    recalculatePayroll: (id: string) => post<PayrollRun>(`/payroll/runs/${id}/recalculate`, {}),
    approvePayroll: (id: string) => post<PayrollRun>(`/payroll/runs/${id}/approve`, {}),
    payPayroll: (id: string) => post<PayrollRun>(`/payroll/runs/${id}/paid`, {}),
    advances: (owingOnly = false) =>
      get<SalaryAdvance[]>(`/payroll/advances${owingOnly ? "?owing_only=true" : ""}`),
    giveAdvance: (input: {
      membership_id: string;
      amount_cents: number;
      note?: string | null;
      mpesa_code?: string | null;
    }) => post<SalaryAdvance>("/payroll/advances", input),
    salaried: () =>
      get<{ membership_id: string; name: string | null; monthly_salary_cents: number }[]>(
        "/payroll/people",
      ),

    // ---- suppliers and parts orders ----
    suppliers: () => get<Supplier[]>("/suppliers"),
    addSupplier: (input: Partial<Supplier>) => post<Supplier>("/suppliers", input),
    updateSupplier: (id: string, input: Partial<Supplier>) =>
      request<Supplier>("PUT", `/suppliers/${id}`, input),
    orders: (status?: string) =>
      get<PartsOrder[]>(`/orders${status ? `?status_filter=${status}` : ""}`),
    createOrder: (input: {
      supplier_id: string;
      lines: {
        part_id?: string | null;
        description: string;
        quantity: number;
        unit_cost_cents: number;
      }[];
      notes?: string | null;
      expected_on?: string | null;
    }) => post<PartsOrder>("/orders", input),
    draftLowStockOrders: (supplierId?: string) =>
      post<PartsOrder[]>("/orders/from-low-stock", { supplier_id: supplierId ?? null }),
    sendOrder: (id: string) => post<PartsOrder>(`/orders/${id}/send`, {}),
    moveOrder: (id: string, status: string, reference?: string) =>
      post<PartsOrder>(`/orders/${id}/status`, { status, reference: reference ?? null }),

    // ---- the lessor portal ----
    portalLeases: () => get<PortalLease[]>("/portal/leases"),
    portalLease: (id: string) => get<PortalLease>(`/portal/leases/${id}`),
    portalStatement: (id: string, month: string) =>
      get<LeaseStatement>(`/portal/leases/${id}/statement?month=${month}`),
    portalStatementPdf: (id: string, month: string) =>
      request<Blob>(
        "GET",
        `/portal/leases/${id}/statement.pdf?month=${month}`,
        undefined,
        true,
        true,
      ),

    // ---- phone GPS, live map, client tracking links ----
    liveMap: () => get<LiveMap>("/map/vehicles"),
    trackingGaps: () => get<TrackingGapRow[]>("/map/gaps"),
    tripTrack: (tripId: string) => get<TripTrack>(`/trips/${tripId}/track`),
    sendLocations: (
      tripId: string,
      points: {
        recorded_at: string;
        lat: number;
        lng: number;
        speed_kmh?: number | null;
        heading?: number | null;
        accuracy_m?: number | null;
      }[],
    ) =>
      post<{
        accepted: number;
        duplicate: number;
        rejected: Record<string, number>;
        tracking: boolean;
      }>(`/trips/${tripId}/locations`, { points }),
    myTracking: () => get<TrackingStatus>("/me/tracking"),
    createTrackingLink: (
      tripId: string,
      input: { send_sms?: boolean; phone?: string | null } = {},
    ) => post<TrackingLinkRow>(`/trips/${tripId}/tracking-link`, input),
    trackingLinks: (tripId: string) => get<TrackingLinkRow[]>(`/trips/${tripId}/tracking-links`),
    revokeTrackingLink: (id: string) => request<void>("DELETE", `/tracking-links/${id}`),
    /** What a client sees. No sign-in: the secret in the address is the key. */
    followDelivery: (token: string) =>
      request<DeliveryFollow>("GET", `/track/${encodeURIComponent(token)}`, undefined, false),

    // ---- trackers, alerts, behaviour, mapped areas, replay, immobiliser ----
    trackers: () => get<TrackerDevice[]>("/trackers"),
    addTracker: (input: TrackerInput) => post<TrackerDevice>("/trackers", input),
    updateTracker: (id: string, input: TrackerInput) =>
      request<TrackerDevice>("PUT", `/trackers/${id}`, input),
    trackerAlerts: (status?: "open") =>
      get<TrackerAlert[]>(`/tracker/alerts${status ? `?status_filter=${status}` : ""}`),
    handleTrackerAlert: (
      id: string,
      input: { note: string; outcome?: "explained" | "confirmed" },
    ) => post<TrackerAlert>(`/tracker/alerts/${id}/handle`, input),
    geofences: () => get<Geofence[]>("/geofences"),
    addGeofence: (input: GeofenceInput) => post<Geofence>("/geofences", input),
    updateGeofence: (id: string, input: GeofenceInput) =>
      request<Geofence>("PUT", `/geofences/${id}`, input),
    deleteGeofence: (id: string) => request<void>("DELETE", `/geofences/${id}`),
    geofenceEvents: (params: { vehicle_id?: string; limit?: number } = {}) => {
      const q = new URLSearchParams();
      if (params.vehicle_id) q.set("vehicle_id", params.vehicle_id);
      if (params.limit) q.set("limit", String(params.limit));
      const qs = q.toString();
      return get<GeofenceEvent[]>(`/geofences/events${qs ? `?${qs}` : ""}`);
    },
    behaviourEvents: (params: { vehicle_id?: string; kind?: string; limit?: number } = {}) => {
      const q = new URLSearchParams();
      if (params.vehicle_id) q.set("vehicle_id", params.vehicle_id);
      if (params.kind) q.set("kind", params.kind);
      if (params.limit) q.set("limit", String(params.limit));
      const qs = q.toString();
      return get<BehaviourEvent[]>(`/behaviour/events${qs ? `?${qs}` : ""}`);
    },
    behaviourSummary: () => get<BehaviourSummary>("/behaviour/summary"),
    tripReplay: (tripId: string) => get<Replay>(`/trips/${tripId}/replay`),
    vehicleReplay: (vehicleId: string, start: string, end: string) =>
      get<Replay>(`/vehicles/${vehicleId}/replay?${new URLSearchParams({ start, end })}`),
    immobiliserState: (vehicleId: string) =>
      get<ImmobiliserState>(`/vehicles/${vehicleId}/immobiliser`),
    requestImmobiliser: (
      vehicleId: string,
      input: { action: "immobilise" | "release"; reason: string },
    ) => post<ImmobiliserCommand>(`/vehicles/${vehicleId}/immobiliser`, input),
    confirmImmobiliser: (id: string, input: { registration: string; password: string }) =>
      post<ImmobiliserCommand>(`/immobiliser/${id}/confirm`, input),
    cancelImmobiliser: (id: string) => post<ImmobiliserCommand>(`/immobiliser/${id}/cancel`),

    // ---- fraud engine, scorecards, fuel prices, route suggestions, private beta ----
    fraudAlerts: (
      params: {
        status_filter?: FraudAlert["status"];
        kind?: string;
        severity?: string;
        vehicle_id?: string;
        trip_id?: string;
        limit?: number;
      } = {},
    ) => {
      const q = new URLSearchParams();
      for (const [k, v] of Object.entries(params)) if (v !== undefined) q.set(k, String(v));
      const qs = q.toString();
      return get<FraudAlert[]>(`/fraud/alerts${qs ? `?${qs}` : ""}`);
    },
    handleFraudAlert: (id: string, input: { note: string; outcome: "explained" | "confirmed" }) =>
      post<FraudAlert>(`/fraud/alerts/${id}/handle`, input),
    fraudSummary: () => get<FraudSummary>("/fraud/summary"),
    scanNow: () => post<{ raised: number }>("/fraud/scan"),
    fraudSettings: () => get<FraudSettings>("/fraud/settings"),
    saveFraudSettings: (input: {
      thresholds?: Record<string, number>;
      channels?: Record<string, { roles: string[]; channels: string[] }>;
    }) => request<FraudSettings>("PUT", "/fraud/settings", input),
    vehicleBaselines: (vehicleId: string) =>
      get<VehicleBaselines>(`/vehicles/${vehicleId}/baselines`),
    scorecards: (start?: string, end?: string) => {
      const q = new URLSearchParams();
      if (start) q.set("start", start);
      if (end) q.set("end", end);
      const qs = q.toString();
      return get<Scorecards>(`/scorecards${qs ? `?${qs}` : ""}`);
    },
    fuelPrices: () => get<FuelPrices>("/fuel-prices"),
    saveFuelPrice: (input: {
      month: string;
      region: string;
      diesel_cents: number;
      petrol_cents: number;
    }) => request<{ current: CurrentFuelPrice | null }>("PUT", "/fuel-prices", input),
    setFuelRegion: (region: string) =>
      request<{ region: string }>("PUT", "/fuel-prices/region", { region }),
    fetchFuelPrices: () => post<{ saved: number }>("/fuel-prices/fetch"),
    suggestRoute: (origin: string, destination: string) =>
      post<RouteSuggestion>("/routes/suggest", { origin, destination }),
    onboarding: () => get<Onboarding>("/onboarding"),
    dismissOnboarding: () => request<void>("POST", "/onboarding/dismiss", {}),
    restoreOnboarding: () => request<void>("POST", "/onboarding/restore", {}),
    sendFeedback: (input: {
      kind: "problem" | "idea" | "praise";
      message: string;
      page?: string;
      app?: "web" | "mobile";
    }) => post<{ id: string }>("/feedback", input),
    feedback: () => get<FeedbackRow[]>("/feedback"),

    // ---- Premium: fuel sensors, predictions, learned models, document reading ----
    fuelLevel: (vehicleId: string, start?: string, end?: string) => {
      const q = new URLSearchParams();
      if (start) q.set("start", start);
      if (end) q.set("end", end);
      const qs = q.toString();
      return get<FuelLevel>(`/vehicles/${vehicleId}/fuel-level${qs ? `?${qs}` : ""}`);
    },
    previewQuote: (input: Record<string, unknown>) => post<QuotePreview>("/quotes/preview", input),
    expectedFuel: (params: {
      vehicle_id: string;
      distance_km: number;
      weight_tonnes?: number;
      origin?: string;
      destination?: string;
      return_empty?: boolean;
    }) => {
      const q = new URLSearchParams();
      for (const [k, v] of Object.entries(params)) if (v !== undefined) q.set(k, String(v));
      return get<ExpectedFuel>(`/predictions/fuel?${q.toString()}`);
    },
    monthForecast: () => get<MonthForecast>("/predictions/forecast"),
    vehicleModel: (vehicleId: string) => get<VehicleModelInfo>(`/vehicles/${vehicleId}/model`),
    readDocument: (input: {
      photo_id: string;
      kind: ReadableDocument;
      vehicle_id?: string | null;
    }) => post<DocumentReading>("/document-readings", input),
    confirmReading: (id: string, fields: Record<string, string | number | null>) =>
      post<DocumentReading>(`/document-readings/${id}/confirm`, { fields }),
    rejectReading: (id: string) => request<void>("POST", `/document-readings/${id}/reject`, {}),
    applyReading: (id: string) =>
      post<{ document_id: string; vehicle_id: string; expires_on: string }>(
        `/document-readings/${id}/apply`,
      ),
    readingSummary: () => get<DocumentReadingSummary[]>("/document-readings/summary"),

    // ---- subscriptions ----
    plans: () => request<PlansInfo>("GET", "/plans", undefined, false),
    subscription: () => get<SubscriptionStatus>("/subscription"),
    subscriptionBanner: () => get<AccessInfo>("/subscription/banner"),
    setVehiclePlans: (vehicles: { vehicle_id: string; plan: PlanName }[]) =>
      request<SubscriptionStatus>("PUT", "/subscription/plans", { vehicles }),
    setSubscriptionSettings: (input: {
      period?: "monthly" | "annual";
      payroll_enabled?: boolean;
    }) => request<SubscriptionStatus>("PUT", "/subscription/settings", input),
    raiseInvoice: () => post<SubscriptionInvoice>("/subscription/invoices"),
    buySmsBundle: (messages: number) =>
      post<SubscriptionInvoice>("/subscription/sms-bundles", { messages }),
    payInvoice: (id: string, phone: string) =>
      post<{ payment_id: string; status: string; message: string }>(
        `/subscription/invoices/${id}/pay`,
        { method: "mpesa", phone },
      ),
    invoiceStatus: (id: string) => get<SubscriptionInvoice>(`/subscription/invoices/${id}`),

    // ---- getting started ----
    createFirstJob: (input: FirstJobInput) =>
      post<{ client_id: string; route_id: string; job: { id: string; number: string } }>(
        "/onboarding/first-job",
        input,
      ),
    addSampleData: () => post<{ vehicle_id: string; job_id: string }>("/onboarding/sample-data"),
    removeSampleData: () => request<void>("DELETE", "/onboarding/sample-data"),

    // ---- messages ----
    sendMessage: (input: {
      body: string;
      all_drivers?: boolean;
      membership_ids?: string[];
      job_id?: string | null;
      also_sms?: boolean;
    }) => post<SentMessage>("/messages", input),
    sentMessages: (jobId?: string) =>
      get<SentMessage[]>(`/messages${jobId ? `?job_id=${jobId}` : ""}`),
    myMessages: () => get<{ unread: number; messages: InboxMessage[] }>("/me/messages"),
    markMessageRead: (id: string) => request<void>("POST", `/me/messages/${id}/read`, {}),

    // ---- the report catalogue ----
    reportCatalog: () => get<CatalogReport[]>("/report-catalog"),
    runReport: (key: string, start?: string, end?: string) => {
      const q = new URLSearchParams();
      if (start) q.set("start", start);
      if (end) q.set("end", end);
      const qs = q.toString();
      return get<ReportData>(`/report-catalog/${key}${qs ? `?${qs}` : ""}`);
    },
    reportFile: (key: string, fileFormat: "pdf" | "xlsx", start?: string, end?: string) => {
      const q = new URLSearchParams({ file_format: fileFormat });
      if (start) q.set("start", start);
      if (end) q.set("end", end);
      return request<Blob>(
        "GET",
        `/report-catalog/${key}/export?${q.toString()}`,
        undefined,
        true,
        true,
      );
    },

    // ---- ask in plain English ----
    ask: (question: string) => post<AskAnswer>("/ask", { question }),
    askExamples: () => get<AskExample[]>("/ask/examples"),
    askLookup: (lookup: string, args: Record<string, string>) =>
      post<ReportData>("/ask/lookup", { lookup, args }),

    // ---- data export ----
    requestExport: (includePhotos: boolean) =>
      post<DataExportInfo>("/data-exports", { include_photos: includePhotos }),
    dataExports: () => get<DataExportInfo[]>("/data-exports"),
    dataExport: (id: string) => get<DataExportInfo>(`/data-exports/${id}`),
    dataExportFile: (id: string) =>
      request<Blob>("GET", `/data-exports/${id}/download`, undefined, true, true),

    // ---- the platform console ----
    platformOverview: () => get<PlatformOverview>("/platform/overview"),
    platformHealth: () =>
      get<{ database: boolean; redis: boolean; version: string; checked_at: string }>(
        "/platform/health",
      ),
    platformBusinesses: (state?: string, q?: string) => {
      const p = new URLSearchParams();
      if (state) p.set("state", state);
      if (q) p.set("q", q);
      const qs = p.toString();
      return get<PlatformBusinessRow[]>(`/platform/customers${qs ? `?${qs}` : ""}`);
    },
    platformBusiness: (id: string) => get<PlatformBusinessDetail>(`/platform/businesses/${id}`),
    platformAct: (
      id: string,
      action: "extend-trial" | "complimentary" | "suspend" | "unsuspend" | "custom-price",
      body: Record<string, unknown> = {},
    ) => post<PlatformBusinessRow>(`/platform/businesses/${id}/${action}`, body),
    platformMarkPaid: (invoiceId: string, reference: string) =>
      post<{ id: string; status: string }>(`/platform/invoices/${invoiceId}/mark-paid`, {
        method: "bank",
        reference,
      }),

    // ---- SOS ----
    myTyrePositions: () => get<MyTyrePositions>("/me/tyre-positions"),
    mySos: () => get<MySos | null>("/me/sos"),
    sosLocation: (id: string, input: { lat: number; lng: number; accuracy_m?: number | null }) =>
      post<{ status: string; acknowledged: boolean }>(`/sos/${id}/location`, input),
    sosAlerts: (activeOnly = true) => get<SosAlert[]>(`/sos?active_only=${activeOnly}`),
    acknowledgeSos: (id: string, note?: string) =>
      post<SosAlert>(`/sos/${id}/acknowledge`, { note }),
    resolveSos: (id: string, note?: string) => post<SosAlert>(`/sos/${id}/resolve`, { note }),

    // ---- audit, privacy, support ----
    audit: (params: { action?: string; limit?: number; offset?: number } = {}) => {
      const q = new URLSearchParams();
      for (const [k, v] of Object.entries(params)) if (v !== undefined) q.set(k, String(v));
      const qs = q.toString();
      return get<AuditEntry[]>(`/audit${qs ? `?${qs}` : ""}`);
    },
    acceptDocument: (doc: PendingDocument) => post<void>("/privacy/accept", doc),
    supportGrants: () => get<SupportGrant[]>("/support/grants"),
    grantSupport: (hours: number, reason: string) =>
      post<SupportGrant>("/support/grants", { hours, reason }),
    revokeSupport: (id: string) => request<void>("DELETE", `/support/grants/${id}`),
  };
}

export type ApiClient = ReturnType<typeof createApiClient>;
