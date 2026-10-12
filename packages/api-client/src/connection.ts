/** What the screen needs to tell the person about the network: busy fetching, or showing a saved copy. */
export interface ConnectionSnapshot {
  /** Requests waiting for the server. */
  pending: number;
  /** When the saved copy now on screen was received; null while the server is answering live. */
  staleSince: string | null;
}

/**
 * Small shared state for the loading bar and the offline banner. `handlers` plug straight into createApiClient;
 * `get` and `subscribe` fit React's useSyncExternalStore (the snapshot object only changes when a value does).
 */
export function createConnectionState() {
  let snapshot: ConnectionSnapshot = { pending: 0, staleSince: null };
  const listeners = new Set<() => void>();
  const set = (next: ConnectionSnapshot) => {
    if (next.pending === snapshot.pending && next.staleSince === snapshot.staleSince) return;
    snapshot = next;
    listeners.forEach((l) => l());
  };
  return {
    get: (): ConnectionSnapshot => snapshot,
    subscribe(listener: () => void): () => void {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    handlers: {
      onActivity: (pending: number) => set({ ...snapshot, pending }),
      onStale: (at: string) => set({ ...snapshot, staleSince: at }),
      onLive: () => set({ ...snapshot, staleSince: null }),
    },
  };
}
export type ConnectionState = ReturnType<typeof createConnectionState>;
