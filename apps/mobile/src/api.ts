import { createApiClient, type TokenStore } from "@fleettms/api-client";
import type { Tokens } from "@fleettms/types";
import * as SecureStore from "expo-secure-store";

const KEY = "fleettms.tokens";

// Tokens live in the phone's secure keystore, and are cleared on sign-out (masterplan Section 10).
const store: TokenStore = {
  async get() {
    try {
      const raw = await SecureStore.getItemAsync(KEY);
      return raw ? (JSON.parse(raw) as Tokens) : null;
    } catch {
      return null;
    }
  },
  async set(tokens) {
    try {
      if (tokens) await SecureStore.setItemAsync(KEY, JSON.stringify(tokens));
      else await SecureStore.deleteItemAsync(KEY);
    } catch {
      /* the next request will ask for a sign-in */
    }
  },
};

let signedOutListener: () => void = () => {};
export const onSignedOut = (fn: () => void) => {
  signedOutListener = fn;
};

// Android emulator reaches the host machine at 10.0.2.2; set EXPO_PUBLIC_API_URL for a real phone.
export const api = createApiClient(process.env.EXPO_PUBLIC_API_URL ?? "http://10.0.2.2:8010", {
  store,
  onSignedOut: () => signedOutListener(),
});

export const hasStoredTokens = async () => (await store.get()) !== null;
