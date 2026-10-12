import type { Tokens } from "@fleettms/types";
import { describe, expect, it, vi } from "vitest";
import {
  ApiError,
  createApiClient,
  createConnectionState,
  NetworkError,
  type ReadCache,
  type ReadCacheEntry,
  type TokenStore,
} from "./index";

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

  it("sends the headers it was given with every request", async () => {
    const fetchImpl = vi.fn(async () => json(200, { user: {} }));
    await createApiClient("http://x", {
      fetchImpl: fetchImpl as never,
      headers: { "X-App-Version-Code": "7" },
    }).health();
    const init = (fetchImpl.mock.calls[0] as unknown as [string, RequestInit])[1];
    expect((init.headers as Record<string, string>)["X-App-Version-Code"]).toBe("7");
  });

  it("tells the app when the server says its build is too old", async () => {
    const onUpgradeRequired = vi.fn();
    const fetchImpl = vi.fn(async () =>
      json(426, { detail: { code: "app_outdated", message: "Old" } }),
    );
    const api = createApiClient("http://x", { fetchImpl: fetchImpl as never, onUpgradeRequired });
    await expect(api.health()).rejects.toMatchObject({ status: 426, code: "app_outdated" });
    expect(onUpgradeRequired).toHaveBeenCalledTimes(1);
  });

  describe("offline reads", () => {
    const signedIn = () => memoryStore({ access_token: "a1", refresh_token: "s.r1" });
    function memoryCache(): ReadCache & { saved: Map<string, ReadCacheEntry> } {
      const saved = new Map<string, ReadCacheEntry>();
      return {
        saved,
        get: async (k) => saved.get(k) ?? null,
        set: async (k, v) => void saved.set(k, v),
        clear: async () => saved.clear(),
      };
    }
    const settle = () => new Promise((r) => setTimeout(r, 0));
    let up = true;
    const flaky = (body: unknown) =>
      vi.fn(async () => {
        if (!up) throw new TypeError("Network request failed");
        return json(200, body);
      });

    it("answers a GET from the saved copy when the network is down, and says how old it is", async () => {
      const readCache = memoryCache();
      const onStale = vi.fn();
      const onLive = vi.fn();
      up = true;
      const fetchImpl = flaky([{ id: "v1" }]);
      const api = createApiClient("http://x", {
        store: signedIn(),
        readCache,
        onStale,
        onLive,
        fetchImpl: fetchImpl as never,
      });
      expect(await api.vehicles()).toEqual([{ id: "v1" }]);
      await settle();
      expect(onLive).toHaveBeenCalledTimes(1);
      up = false;
      expect(await api.vehicles()).toEqual([{ id: "v1" }]);
      expect(onStale).toHaveBeenCalledWith(readCache.saved.get("/vehicles")?.at);
    });

    it("throws a plain NetworkError when offline with nothing saved", async () => {
      up = false;
      const api = createApiClient("http://x", {
        store: signedIn(),
        readCache: memoryCache(),
        fetchImpl: flaky([]) as never,
      });
      const err = await api.vehicles().catch((e: unknown) => e);
      expect(err).toBeInstanceOf(NetworkError);
      expect((err as NetworkError).message).toBe(
        "You are offline. Check your connection and try again.",
      );
      expect((err as { status?: number }).status).toBeUndefined();
    });

    it("never answers a write from the saved copy", async () => {
      const readCache = memoryCache();
      up = true;
      const api = createApiClient("http://x", {
        store: signedIn(),
        readCache,
        fetchImpl: flaky({ ok: true }) as never,
      });
      await api.createDepot({ name: "Yard" } as never);
      await settle();
      expect(readCache.saved.size).toBe(0);
      up = false;
      await expect(api.createDepot({ name: "Yard" } as never)).rejects.toBeInstanceOf(NetworkError);
    });

    it("does not save sign-in calls, but does save who-am-I, and does not save a failed reply", async () => {
      const readCache = memoryCache();
      up = true;
      const api = createApiClient("http://x", {
        store: signedIn(),
        readCache,
        fetchImpl: flaky({ user: {} }) as never,
      });
      await api.me();
      await settle();
      expect([...readCache.saved.keys()]).toEqual(["/auth/me"]);
      const failing = vi.fn(async () =>
        json(403, { detail: { code: "forbidden", message: "No." } }),
      );
      const other = memoryCache();
      const api2 = createApiClient("http://x", {
        store: signedIn(),
        readCache: other,
        fetchImpl: failing as never,
      });
      await expect(api2.vehicles()).rejects.toBeInstanceOf(ApiError);
      await settle();
      expect(other.saved.size).toBe(0);
    });

    it("forgets what it saved on sign-out, so the next person never sees it", async () => {
      const readCache = memoryCache();
      up = true;
      const api = createApiClient("http://x", {
        store: signedIn(),
        readCache,
        fetchImpl: flaky([{ id: "v1" }]) as never,
      });
      await api.vehicles();
      await settle();
      expect(readCache.saved.size).toBe(1);
      await api.logout();
      expect(readCache.saved.size).toBe(0);
    });

    it("reports how many requests are waiting", async () => {
      const seen: number[] = [];
      up = true;
      const api = createApiClient("http://x", {
        store: signedIn(),
        onActivity: (n) => seen.push(n),
        fetchImpl: flaky([]) as never,
      });
      await Promise.all([api.vehicles(), api.depots()]);
      expect(seen).toEqual([1, 2, 1, 0]);
    });
  });

  it("connection state changes only when a value does", () => {
    const c = createConnectionState();
    const first = c.get();
    const calls = vi.fn();
    c.subscribe(calls);
    c.handlers.onLive();
    expect(c.get()).toBe(first);
    c.handlers.onStale("2026-10-12T08:00:00Z");
    c.handlers.onActivity(2);
    expect(c.get()).toEqual({ pending: 2, staleSince: "2026-10-12T08:00:00Z" });
    c.handlers.onLive();
    expect(c.get().staleSince).toBeNull();
    expect(calls).toHaveBeenCalledTimes(3);
  });
});
