import type { ReadCache, ReadCacheEntry } from "@fleettms/api-client";
import { fromB64, toB64, unutf8, utf8 } from "./bytes";
import type { FileAdapter } from "./store";
import type { Vault } from "./vault";

const FILE = "reads.enc";
const MAX_ENTRIES = 80; // the pages a person actually goes back to; the oldest are dropped first
const MAX_ENTRY_CHARS = 1_000_000; // one huge reply is not worth the space
const SAVE_DELAY_MS = 1500; // a burst of replies is written once

/**
 * The last reply to each GET, kept encrypted on the phone so the office screens open with what they showed last when there
 * is no network. Signing out destroys the vault key and clears this, so the next person never sees it.
 */
export function createReadCache(deps: {
  files: FileAdapter;
  vault: Vault;
}): ReadCache & { flush(): Promise<void> } {
  const { files, vault } = deps;
  let entries: Map<string, ReadCacheEntry> | null = null;
  let loading: Promise<Map<string, ReadCacheEntry>> | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let writing: Promise<void> = Promise.resolve();

  function load(): Promise<Map<string, ReadCacheEntry>> {
    if (entries) return Promise.resolve(entries);
    loading ??= (async () => {
      const found = new Map<string, ReadCacheEntry>();
      try {
        const sealed = await files.read(FILE);
        if (sealed) {
          const saved = JSON.parse(unutf8(await vault.open(fromB64(sealed)))) as [
            string,
            ReadCacheEntry,
          ][];
          for (const [k, v] of saved) found.set(k, v);
        }
      } catch {
        /* unreadable (key lost or file damaged): start empty rather than fail a screen */
      }
      entries ??= found;
      return entries;
    })();
    return loading;
  }

  function save(): Promise<void> {
    if (!entries) return writing;
    const snapshot = JSON.stringify([...entries]);
    writing = writing.then(async () => {
      await files.write(FILE, toB64(await vault.seal(utf8(snapshot))));
    });
    return writing;
  }

  return {
    async get(key) {
      return (await load()).get(key) ?? null;
    },
    async set(key, entry) {
      if (JSON.stringify(entry.data).length > MAX_ENTRY_CHARS) return;
      const all = await load();
      all.delete(key); // re-added last, so it counts as the newest
      all.set(key, entry);
      while (all.size > MAX_ENTRIES) all.delete(all.keys().next().value as string);
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => {
        timer = null;
        void save().catch(() => undefined);
      }, SAVE_DELAY_MS);
    },
    async clear() {
      if (timer) clearTimeout(timer);
      timer = null;
      entries = new Map();
      loading = null;
      await writing.catch(() => undefined);
      await files.remove(FILE);
    },
    /** Writes what is waiting now (used when the app goes to the background, and by tests). */
    async flush() {
      if (timer) {
        clearTimeout(timer);
        timer = null;
        await save();
      } else {
        await writing;
      }
    },
  };
}
