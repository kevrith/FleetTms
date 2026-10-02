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
  let key: Uint8Array | null = null;

  async function loadKey(): Promise<Uint8Array> {
    if (key) return key;
    const saved = await keys.get();
    if (saved) {
      key = fromB64(saved);
    } else {
      key = random(32);
      await keys.set(toB64(key));
    }
    return key;
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
      key = null;
      await keys.clear();
    },
  };
}
export type Vault = ReturnType<typeof createVault>;
