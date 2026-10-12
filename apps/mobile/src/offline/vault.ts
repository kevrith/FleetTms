import { xchacha20poly1305 } from "@noble/ciphers/chacha";
import { fromB64, toB64 } from "./bytes";

/** Where the vault key lives. On the phone this is the secure keystore, never the same place as the data. */
export interface KeyStore {
  get(): Promise<string | null>;
  set(value: string): Promise<void>;
  clear(): Promise<void>;
}
export type RandomBytes = (length: number) => Uint8Array;

const NONCE = 24;

/**
 * Encrypts everything the phone keeps for later (queued actions, photos). Each item gets its own random nonce, and
 * tampering is detected on opening. Signing out destroys the key, which makes anything left on disk unreadable.
 */
export function createVault(keys: KeyStore, random: RandomBytes) {
  // One load at a time: two things sealing before a key exists must not each make their own.
  let loading: Promise<Uint8Array> | null = null;

  function loadKey(): Promise<Uint8Array> {
    loading ??= (async () => {
      const saved = await keys.get();
      if (saved) return fromB64(saved);
      const fresh = random(32);
      await keys.set(toB64(fresh));
      return fresh;
    })().catch((e) => {
      loading = null;
      throw e;
    });
    return loading;
  }

  return {
    async seal(plain: Uint8Array): Promise<Uint8Array> {
      const nonce = random(NONCE);
      const sealed = xchacha20poly1305(await loadKey(), nonce).encrypt(plain);
      const out = new Uint8Array(NONCE + sealed.length);
      out.set(nonce, 0);
      out.set(sealed, NONCE);
      return out;
    },
    /** Throws if the data was changed, or if it was sealed with a different key. */
    async open(sealed: Uint8Array): Promise<Uint8Array> {
      return xchacha20poly1305(await loadKey(), sealed.slice(0, NONCE)).decrypt(
        sealed.slice(NONCE),
      );
    },
    async destroy(): Promise<void> {
      loading = null;
      await keys.clear();
    },
  };
}
export type Vault = ReturnType<typeof createVault>;
