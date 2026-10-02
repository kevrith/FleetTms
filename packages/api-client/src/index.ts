import type {
  AuditEntry,
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
  Invoice,
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
    createReportSchedule: (input: Pick<ReportSchedule, "frequency" | "channel" | "recipient">) =>
      post<ReportSchedule>("/report-schedules", input),
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
