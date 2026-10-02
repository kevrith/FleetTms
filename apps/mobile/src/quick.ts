import * as Crypto from "expo-crypto";
import * as SecureStore from "expo-secure-store";

/** What this phone keeps for quick sign-in. Both live in the secure keystore, never in ordinary storage. */
export interface QuickCredentials {
  phone: string;
  deviceId: string;
  secret: string;
}

const CREDS = "fleettms.quick";
const DEVICE = "fleettms.deviceid";

/** An id for this phone, made once. The server ties a phone's quick sign-in to it. */
export async function deviceId(): Promise<string> {
  const saved = await SecureStore.getItemAsync(DEVICE);
  if (saved) return saved;
  const fresh = Crypto.randomUUID();
  await SecureStore.setItemAsync(DEVICE, fresh);
  return fresh;
}

export async function getQuick(): Promise<QuickCredentials | null> {
  try {
    const raw = await SecureStore.getItemAsync(CREDS);
    return raw ? (JSON.parse(raw) as QuickCredentials) : null;
  } catch {
    return null;
  }
}

export const saveQuick = (c: QuickCredentials) =>
  SecureStore.setItemAsync(CREDS, JSON.stringify(c));
export const clearQuick = () => SecureStore.deleteItemAsync(CREDS);
