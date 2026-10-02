import { createApiClient, type TokenStore } from "@fleettms/api-client";
import type { Tokens } from "@fleettms/types";

const KEY = "fleettms.tokens";

// Browser storage can be blocked (private windows); the app then just asks for a sign-in.
const store: TokenStore = {
  async get() {
    try {
      const raw = localStorage.getItem(KEY);
      return raw ? (JSON.parse(raw) as Tokens) : null;
    } catch {
      return null;
    }
  },
  async set(tokens) {
    try {
      if (tokens) localStorage.setItem(KEY, JSON.stringify(tokens));
      else localStorage.removeItem(KEY);
    } catch {
      /* ignore */
    }
  },
};

let signedOutListener: () => void = () => {};
export const onSignedOut = (fn: () => void) => {
  signedOutListener = fn;
};

export const api = createApiClient(import.meta.env.VITE_API_URL ?? "http://localhost:8010", {
  store,
  onSignedOut: () => signedOutListener(),
});

export const hasStoredTokens = async () => (await store.get()) !== null;
