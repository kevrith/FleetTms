import type {
  AuditEntry,
  ComplianceDocument,
  CrewAssignment,
  CrewRole,
  Depot,
  DocumentInput,
  HealthResponse,
  ImportResult,
  InviteInput,
  Me,
  MyVehicle,
  Party,
  PartyInput,
  PendingDocument,
  ProfileInput,
  Role,
  SignupInput,
  StaffMember,
  StaffProfile,
  SupportGrant,
  TokenResponse,
  Tokens,
  Vehicle,
  VehicleInput,
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
