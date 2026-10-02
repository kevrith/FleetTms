import type { Tokens } from "@fleettms/types";
import { describe, expect, it, vi } from "vitest";
import { ApiError, createApiClient, type TokenStore } from "./index";

function memoryStore(initial: Tokens | null): TokenStore & { current: Tokens | null } {
  const s = {
    current: initial,
    get: async () => s.current,
    set: async (t: Tokens | null) => {
      s.current = t;
    },
  };
  return s;
}

const json = (status: number, body: unknown) =>
  new Response(status === 204 ? null : JSON.stringify(body), { status });

describe("api client", () => {
  it("sends the bearer token", async () => {
    const store = memoryStore({ access_token: "a1", refresh_token: "s.r1" });
    const fetchImpl = vi.fn(async () => json(200, { user: {} }));
    await createApiClient("http://x", { store, fetchImpl: fetchImpl as never }).me();
    const init = (fetchImpl.mock.calls[0] as unknown as [string, RequestInit])[1];
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer a1");
  });

  it("refreshes once on 401 and retries, even for parallel calls", async () => {
    const store = memoryStore({ access_token: "old", refresh_token: "s.r1" });
    let refreshCalls = 0;
    const fetchImpl = vi.fn(async (url: string, init: RequestInit) => {
      if (url.endsWith("/auth/refresh")) {
        refreshCalls++;
        return json(200, { access_token: "new", refresh_token: "s.r2" });
      }
      const auth = (init.headers as Record<string, string>).Authorization;
      return auth === "Bearer new"
        ? json(200, [])
        : json(401, { detail: { code: "not_authenticated" } });
    });
    const api = createApiClient("http://x", { store, fetchImpl: fetchImpl as never });
    await Promise.all([api.users(), api.depots(), api.audit()]);
    expect(refreshCalls).toBe(1);
    expect(store.current).toEqual({ access_token: "new", refresh_token: "s.r2" });
  });

  it("signs out when the refresh fails", async () => {
    const store = memoryStore({ access_token: "old", refresh_token: "s.r1" });
    const onSignedOut = vi.fn();
    const fetchImpl = vi.fn(async () =>
      json(401, { detail: { code: "not_authenticated", message: "Please sign in again." } }),
    );
    const api = createApiClient("http://x", { store, onSignedOut, fetchImpl: fetchImpl as never });
    await expect(api.users()).rejects.toBeInstanceOf(ApiError);
    expect(onSignedOut).toHaveBeenCalled();
    expect(store.current).toBeNull();
  });

  it("turns API errors into plain-English messages", async () => {
    const fetchImpl = vi.fn(async () =>
      json(401, {
        detail: { code: "invalid_credentials", message: "Incorrect email, phone or password." },
      }),
    );
    const api = createApiClient("http://x", { fetchImpl: fetchImpl as never });
    await expect(api.login({ identifier: "a", password: "b" })).rejects.toMatchObject({
      code: "invalid_credentials",
      message: "Incorrect email, phone or password.",
    });
  });

  it("gives a friendly message for validation errors", async () => {
    const fetchImpl = vi.fn(async () => json(422, { detail: [{ msg: "x" }] }));
    const api = createApiClient("http://x", { fetchImpl: fetchImpl as never });
    await expect(api.login({ identifier: "a", password: "b" })).rejects.toMatchObject({
      code: "validation",
    });
  });

  it("stores tokens after login", async () => {
    const store = memoryStore(null);
    const fetchImpl = vi.fn(async () =>
      json(200, {
        access_token: "A",
        refresh_token: "s.R",
        token_type: "bearer",
        mfa_setup_required: false,
        business_id: "b",
      }),
    );
    const api = createApiClient("http://x", { store, fetchImpl: fetchImpl as never });
    await api.login({ identifier: "a", password: "b" });
    expect(store.current).toEqual({ access_token: "A", refresh_token: "s.R" });
  });
});
