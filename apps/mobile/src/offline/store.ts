import { fromB64, toB64, unutf8, utf8 } from "./bytes";
import { emptyCache, type LocalPhoto, type OfflineState, type QueueItem } from "./types";
import type { Vault } from "./vault";

/** The phone's files. Everything passed to `write` is already encrypted. */
export interface FileAdapter {
  read(name: string): Promise<string | null>;
  write(name: string, base64: string): Promise<void>;
  remove(name: string): Promise<void>;
  removeAll(): Promise<void>;
  /** A short-lived plain copy, only so a photo can be uploaded. `cleanup` deletes it. */
  writeTemp(
    name: string,
    bytes: Uint8Array,
  ): Promise<{ uri: string; cleanup: () => Promise<void> }>;
}

const STATE_FILE = "state.enc";
const photoFile = (clientId: string) => `photo-${clientId}.enc`;

export interface StoreDeps {
  files: FileAdapter;
  vault: Vault;
  uuid: () => string;
  now: () => Date;
}

/** The offline database: queued actions, photos and cached server data, encrypted at rest. */
export function createStore(deps: StoreDeps) {
  const { files, vault } = deps;
  let state: OfflineState = fresh();
  const listeners = new Set<() => void>();
  let writing: Promise<void> = Promise.resolve();

  function fresh(): OfflineState {
    return {
      version: 1,
      deviceId: deps.uuid(),
      ownerUserId: null,
      queue: [],
      photos: {},
      cache: emptyCache(),
      mockSeen: false,
      lastSyncAt: null,
    };
  }

  /** Writes happen one at a time, in order, so a quick burst of changes never saves an older state last. */
  function persist(): Promise<void> {
    const snapshot = JSON.stringify(state);
    writing = writing.then(async () => {
      await files.write(STATE_FILE, toB64(await vault.seal(utf8(snapshot))));
    });
    return writing;
  }

  return {
    async load(): Promise<OfflineState> {
      const sealed = await files.read(STATE_FILE);
      if (sealed) {
        try {
          state = JSON.parse(unutf8(await vault.open(fromB64(sealed)))) as OfflineState;
        } catch {
          state = fresh(); // unreadable (key lost or file damaged): start clean rather than crash
        }
      } else {
        state = fresh();
        await persist();
      }
      listeners.forEach((l) => l());
      return state;
    },
    get: (): OfflineState => state,
    async update(change: (s: OfflineState) => OfflineState): Promise<void> {
      state = change(state);
      listeners.forEach((l) => l());
      await persist();
    },
    subscribe(listener: () => void): () => void {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    async addPhoto(
      bytes: Uint8Array,
      meta: Omit<LocalPhoto, "clientId" | "uploaded">,
    ): Promise<LocalPhoto> {
      const photo: LocalPhoto = { ...meta, clientId: deps.uuid(), uploaded: false };
      await files.write(photoFile(photo.clientId), toB64(await vault.seal(bytes)));
      await this.update((s) => ({ ...s, photos: { ...s.photos, [photo.clientId]: photo } }));
      return photo;
    },
    async photoBytes(clientId: string): Promise<Uint8Array | null> {
      const sealed = await files.read(photoFile(clientId));
      return sealed ? vault.open(fromB64(sealed)) : null;
    },
    async materialize(clientId: string) {
      const bytes = await this.photoBytes(clientId);
      return bytes ? files.writeTemp(`upload-${clientId}.jpg`, bytes) : null;
    },
    async removePhotos(ids: string[]): Promise<void> {
      for (const id of ids) await files.remove(photoFile(id));
      await this.update((s) => {
        const photos = { ...s.photos };
        for (const id of ids) delete photos[id];
        return { ...s, photos };
      });
    },
    async enqueue(item: Omit<QueueItem, "id" | "status" | "attempts">): Promise<QueueItem> {
      const queued: QueueItem = { ...item, id: deps.uuid(), status: "queued", attempts: 0 };
      await this.update((s) => ({ ...s, queue: [...s.queue, queued] }));
      return queued;
    },
    async discard(itemId: string): Promise<void> {
      const item = state.queue.find((i) => i.id === itemId);
      if (!item) return;
      await this.removePhotos(item.photoIds);
      await this.update((s) => ({ ...s, queue: s.queue.filter((i) => i.id !== itemId) }));
    },
    async retry(itemId: string): Promise<void> {
      await this.update((s) => ({
        ...s,
        queue: s.queue.map((i) =>
          i.id === itemId
            ? { ...i, status: "queued", attempts: 0, code: undefined, message: undefined }
            : i,
        ),
      }));
    },
    /** Signing out: delete every file and destroy the key, so nothing of this person's work stays on the phone. */
    async clear(): Promise<void> {
      await writing.catch(() => undefined);
      await files.removeAll();
      await vault.destroy();
      state = fresh();
      listeners.forEach((l) => l());
    },
  };
}
export type Store = ReturnType<typeof createStore>;
