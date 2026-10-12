import type { ReadCache, ReadCacheEntry } from "@fleettms/api-client";

const DB = "fleettms-reads";
const TABLE = "replies";

/** The browser's IndexedDB if it works (it can be blocked in private windows); null otherwise. */
function open(): Promise<IDBDatabase | null> {
  return new Promise((resolve) => {
    try {
      const req = indexedDB.open(DB, 1);
      req.onupgradeneeded = () => req.result.createObjectStore(TABLE);
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => resolve(null);
      req.onblocked = () => resolve(null);
    } catch {
      resolve(null);
    }
  });
}

function run<T>(
  db: IDBDatabase,
  mode: IDBTransactionMode,
  work: (table: IDBObjectStore) => IDBRequest<T>,
): Promise<T | null> {
  return new Promise((resolve) => {
    try {
      const req = work(db.transaction(TABLE, mode).objectStore(TABLE));
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => resolve(null);
    } catch {
      resolve(null);
    }
  });
}

/**
 * Saves the last reply to every page's data, so a page opens offline with what it showed last. It is emptied on sign-out
 * and when the company changes (the api client does that). If the browser will not store anything, pages simply need a network.
 */
export function createBrowserReadCache(): ReadCache {
  const db = open();
  return {
    async get(key) {
      const d = await db;
      return d ? ((await run(d, "readonly", (t) => t.get(key))) as ReadCacheEntry | null) : null;
    },
    async set(key, entry) {
      const d = await db;
      if (d) await run(d, "readwrite", (t) => t.put(entry, key));
    },
    async clear() {
      const d = await db;
      if (d) await run(d, "readwrite", (t) => t.clear());
    },
  };
}
