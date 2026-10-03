import { describe, expect, it } from "vitest";
import { createSyncEngine } from "./engine";
import { createStore } from "./store";
import {
  ApiFailure,
  device,
  fakeServer,
  makeStore,
  memoryFiles,
  memoryKeys,
  random,
} from "./testkit";
import { createVault } from "./vault";

const bytes = (text: string) => new TextEncoder().encode(text);

describe("vault", () => {
  it("encrypts and decrypts, with a fresh nonce each time", async () => {
    const vault = createVault(memoryKeys(), random);
    const plain = bytes("odometer 125100");
    const a = await vault.seal(plain);
    const b = await vault.seal(plain);
    expect(a).not.toEqual(b);
    expect(new TextDecoder().decode(await vault.open(a))).toBe("odometer 125100");
  });
  it("detects tampering", async () => {
    const vault = createVault(memoryKeys(), random);
    const sealed = await vault.seal(bytes("secret"));
    sealed[sealed.length - 1] = (sealed[sealed.length - 1] ?? 0) ^ 1;
    await expect(vault.open(sealed)).rejects.toThrow();
  });
  it("cannot be opened with another key, or after the key is destroyed", async () => {
    const keys = memoryKeys();
    const vault = createVault(keys, random);
    const sealed = await vault.seal(bytes("secret"));
    await expect(createVault(memoryKeys(), random).open(sealed)).rejects.toThrow();
    await vault.destroy();
    expect(keys.value).toBeNull();
    await expect(createVault(keys, random).open(sealed)).rejects.toThrow(); // a new key was made
  });
});

describe("store", () => {
  it("keeps data across restarts and never writes it in the clear", async () => {
    const files = memoryFiles();
    const keys = memoryKeys();
    let n = 0;
    const make = () =>
      createStore({
        files,
        vault: createVault(keys, random),
        uuid: () => `id-${++n}`,
        now: () => new Date(),
      });
    const first = make();
    await first.load();
    await first.enqueue({
      type: "fuel.add",
      payload: { station: "Total Naivasha" },
      capturedAt: "2026-10-02T06:00:00Z",
      photoIds: [],
    });
    await first.addPhoto(bytes("PLAIN-PHOTO-BYTES"), {
      kind: "odometer",
      capturedAt: "2026-10-02T06:00:00Z",
      lat: -1.29,
      lng: 36.82,
    });

    for (const content of files.disk.values()) {
      expect(atob(content)).not.toContain("Total Naivasha");
      expect(atob(content)).not.toContain("PLAIN-PHOTO-BYTES");
    }
    const second = make();
    const restored = await second.load();
    expect(restored.queue).toHaveLength(1);
    expect(restored.queue[0]?.payload).toEqual({ station: "Total Naivasha" });
    const [photoId] = Object.keys(restored.photos);
    expect(new TextDecoder().decode((await second.photoBytes(photoId!))!)).toBe(
      "PLAIN-PHOTO-BYTES",
    );
  });
  it("starts clean when the stored data cannot be read", async () => {
    const files = memoryFiles();
    files.disk.set("state.enc", "AAAA");
    const store = createStore({
      files,
      vault: createVault(memoryKeys(), random),
      uuid: () => "id",
      now: () => new Date(),
    });
    expect((await store.load()).queue).toEqual([]);
  });
  it("wipes every file and the key on sign out", async () => {
    const { store, files, keys } = makeStore();
    await store.load();
    await store.addPhoto(bytes("x"), {
      kind: "cargo",
      capturedAt: "2026-10-02T06:00:00Z",
      lat: null,
      lng: null,
    });
    expect(files.disk.size).toBeGreaterThan(0);
    await store.clear();
    expect(files.disk.size).toBe(0);
    expect(keys.value).toBeNull();
    expect(store.get().queue).toEqual([]);
  });
});

async function setup(options?: Parameters<typeof fakeServer>[0]) {
  const { store, files } = makeStore();
  await store.load();
  const server = fakeServer(options);
  let online = true;
  const engine = createSyncEngine({ store, api: server.api, isOnline: async () => online, device });
  return {
    store,
    files,
    server,
    engine,
    goOffline: () => void (online = false),
    goOnline: () => void (online = true),
  };
}

const queueMorning = async (store: Awaited<ReturnType<typeof setup>>["store"]) => {
  const photo = await store.addPhoto(bytes("jpeg"), {
    kind: "odometer",
    capturedAt: "2026-10-02T05:00:00Z",
    lat: -1.2,
    lng: 36.8,
  });
  await store.enqueue({
    type: "inspection.submit",
    payload: { vehicle_id: "v1" },
    capturedAt: "2026-10-02T04:50:00Z",
    photoIds: [],
  });
  await store.enqueue({
    type: "trip.start",
    payload: { trip_id: "t1", photo_client_id: photo.clientId, value: 125100 },
    capturedAt: "2026-10-02T05:00:00Z",
    photoIds: [photo.clientId],
  });
  await store.enqueue({
    type: "fuel.add",
    payload: { vehicle_id: "v1", client_id: "f1" },
    capturedAt: "2026-10-02T06:00:00Z",
    photoIds: [],
  });
  return photo;
};

describe("sync engine", () => {
  it("does nothing while offline and keeps everything queued", async () => {
    const { store, server, engine, goOffline } = await setup();
    await queueMorning(store);
    goOffline();
    expect(await engine.run()).toEqual({ status: "offline" });
    expect(store.get().queue).toHaveLength(3);
    expect(server.syncCalls).toHaveLength(0);
  });

  it("uploads photos first, sends actions in order with the original times, then clears the queue", async () => {
    const { store, server, engine, files } = await setup();
    const photo = await queueMorning(store);
    const result = await engine.run();
    expect(result).toMatchObject({ status: "done", applied: 3, rejected: 0, waiting: 0 });
    expect(server.photos.has(photo.clientId)).toBe(true);
    const sent = server.syncCalls[0]!;
    expect(sent.map((a) => a.type)).toEqual(["inspection.submit", "trip.start", "fuel.add"]);
    expect(sent[1]!.payload.captured_at).toBe("2026-10-02T05:00:00Z"); // when it was done, not when it synced
    expect(store.get().queue).toEqual([]);
    expect(store.get().photos).toEqual({});
    expect([...files.disk.keys()]).toEqual(["state.enc"]); // the photo file is gone once it has been delivered
    expect(files.temps.size).toBe(0); // and no plain copy is left behind
    expect(server.refreshes).toBe(1);
  });

  it("sends an SOS first, ahead of photo uploads and the rest of the queue", async () => {
    const { store, server, engine } = await setup();
    await queueMorning(store);
    await store.enqueue({
      type: "sos.send",
      payload: { lat: -1.29, lng: 36.82 },
      capturedAt: "2026-10-02T07:00:00Z",
      photoIds: [],
    });
    expect(await engine.run()).toMatchObject({ status: "done", applied: 4, waiting: 0 });
    expect(server.syncCalls[0]!.map((a) => a.type)).toEqual(["sos.send"]);
    expect(server.syncCalls[0]![0]!.payload.captured_at).toBe("2026-10-02T07:00:00Z");
    expect(server.syncCalls[1]!.map((a) => a.type)).toEqual([
      "inspection.submit",
      "trip.start",
      "fuel.add",
    ]);
  });

  it("an SOS pressed with no network waits and goes the moment there is one", async () => {
    const { store, server, engine, goOffline, goOnline } = await setup();
    await store.enqueue({
      type: "sos.send",
      payload: { lat: null, lng: null },
      capturedAt: "2026-10-02T07:00:00Z",
      photoIds: [],
    });
    goOffline();
    expect((await engine.run()).status).toBe("offline");
    expect(store.get().queue).toHaveLength(1);
    goOnline();
    expect(await engine.run()).toMatchObject({ status: "done", applied: 1 });
    expect(server.syncCalls).toHaveLength(1);
  });

  it("carries an incident report with its photo and the time it happened", async () => {
    const { store, server, engine } = await setup();
    const photo = await store.addPhoto(bytes("jpeg"), {
      kind: "incident",
      capturedAt: "2026-10-02T09:00:00Z",
      lat: -1.3,
      lng: 36.9,
    });
    await store.enqueue({
      type: "incident.report",
      payload: {
        type: "breakdown",
        occurred_at: "2026-10-02T09:00:05Z",
        photo_client_ids: [photo.clientId],
      },
      capturedAt: "2026-10-02T09:00:05Z",
      photoIds: [photo.clientId],
    });
    expect(await engine.run()).toMatchObject({ status: "done", applied: 1 });
    expect(server.photos.has(photo.clientId)).toBe(true);
    expect(server.syncCalls[0]![0]).toMatchObject({
      type: "incident.report",
      payload: { type: "breakdown", occurred_at: "2026-10-02T09:00:05Z" },
    });
  });

  it("is safe to run again: a second run sends nothing new", async () => {
    const { store, server, engine } = await setup();
    await queueMorning(store);
    await engine.run();
    await engine.run();
    expect(server.syncCalls).toHaveLength(1);
    expect(server.applied.size).toBe(3);
  });

  it("survives a lost reply: the resend is answered as duplicates and nothing is applied twice", async () => {
    const { store, server, engine } = await setup();
    await queueMorning(store);
    server.failNext.push("lost_reply"); // the server applies the batch, but the phone never hears back
    expect((await engine.run()).status).toBe("offline");
    expect(server.applied.size).toBe(3);
    expect(store.get().queue).toHaveLength(3); // the phone still thinks they are unsent

    expect(await engine.run()).toMatchObject({ status: "done", applied: 3 });
    expect(server.applied.size).toBe(3); // still three: no double entries
    expect(store.get().queue).toEqual([]);
  });

  it("stops quietly when the network drops mid-upload and carries on later", async () => {
    const { store, server, engine } = await setup();
    await queueMorning(store);
    server.failNext.push("network");
    expect((await engine.run()).status).toBe("offline");
    expect(store.get().queue).toHaveLength(3);
    expect(store.get().photos[Object.keys(store.get().photos)[0]!]?.uploaded).toBe(false);
    expect(await engine.run()).toMatchObject({ status: "done", applied: 3 });
  });

  it("keeps a rejected action visible with the reason, and still sends the rest", async () => {
    const { store, engine } = await setup({
      rejectType: { "trip.start": { code: "inspection_required" } },
    });
    await queueMorning(store);
    const result = await engine.run();
    expect(result).toMatchObject({ status: "done", applied: 2, rejected: 1 });
    const stuck = store.get().queue;
    expect(stuck).toHaveLength(1);
    expect(stuck[0]).toMatchObject({
      type: "trip.start",
      status: "rejected",
      code: "inspection_required",
    });
    await store.retry(stuck[0]!.id);
    expect(store.get().queue[0]?.status).toBe("queued");
    await store.discard(stuck[0]!.id);
    expect(store.get().queue).toEqual([]);
  });

  it("retries a retryable rejection a few times and then gives up", async () => {
    const { store, engine } = await setup({
      rejectType: { "fuel.add": { code: "photo_invalid", retryable: true } },
    });
    await store.enqueue({
      type: "fuel.add",
      payload: { client_id: "f1" },
      capturedAt: "2026-10-02T06:00:00Z",
      photoIds: [],
    });
    for (let i = 0; i < 4; i++) {
      await engine.run();
      expect(store.get().queue[0]).toMatchObject({ status: "queued", attempts: i + 1 });
    }
    await engine.run();
    expect(store.get().queue[0]).toMatchObject({ status: "rejected", code: "photo_invalid" });
  });

  it("marks a record rejected when the server refuses its photo, without blocking others", async () => {
    const { store, server, engine } = await setup();
    await queueMorning(store);
    server.photoFailure = new ApiFailure(422, "photo_blank", "That photo is blank or too dark.");
    await engine.run();
    const stuck = store.get().queue.find((i) => i.type === "trip.start");
    expect(stuck).toMatchObject({ status: "rejected", code: "photo_blank" });
    expect(stuck?.message).toContain("blank");
    expect(store.get().queue.filter((i) => i.status === "queued")).toHaveLength(0); // the other two were sent
  });

  it("keeps everything on the phone when the account is read-only (402), photos included, and sends it once paid", async () => {
    const { store, server, engine } = await setup();
    await queueMorning(store);
    server.photoFailure = new ApiFailure(402, "subscription_read_only", "Read-only until paid.");
    const held = await engine.run();
    expect(held.status).toBe("offline");
    expect(store.get().queue.every((i) => i.status === "queued")).toBe(true);
    expect(store.get().queue).toHaveLength(3);
    server.photoFailure = null; // paid
    await engine.run();
    expect(store.get().queue).toEqual([]);
  });

  it("reports a signed-out session and leaves the queue alone", async () => {
    const { store, server, engine } = await setup();
    await queueMorning(store);
    server.failNext.push("401");
    // photo upload succeeds, the sync call is refused
    const result = await engine.run();
    expect(result.status).toBe("signed_out");
    expect(store.get().queue).toHaveLength(3);
  });

  it("sends large queues in batches of 50", async () => {
    const { store, server, engine } = await setup();
    for (let i = 0; i < 120; i++) {
      await store.enqueue({
        type: "trip.deliver",
        payload: { trip_id: `t${i}` },
        capturedAt: "2026-10-02T06:00:00Z",
        photoIds: [],
      });
    }
    await engine.run();
    expect(server.syncCalls.map((c) => c.length)).toEqual([50, 50, 20]);
    expect(store.get().queue).toEqual([]);
  });

  it("does not replace the phone's own view with the server's while work is still waiting", async () => {
    const { store, server, engine } = await setup({
      rejectType: { "fuel.add": { code: "x", retryable: true } },
    });
    await store.enqueue({
      type: "fuel.add",
      payload: { client_id: "f1" },
      capturedAt: "2026-10-02T06:00:00Z",
      photoIds: [],
    });
    await engine.run({ refresh: true });
    expect(server.refreshes).toBe(0);
  });

  it("shares one run between callers instead of starting two", async () => {
    const { store, server, engine } = await setup();
    await queueMorning(store);
    await Promise.all([engine.run(), engine.run(), engine.run()]);
    expect(server.syncCalls).toHaveLength(1);
  });

  it("reports the device with each sync and clears the mock-location sighting once reported", async () => {
    const { store, server, engine } = await setup();
    await store.update((s) => ({ ...s, mockSeen: true }));
    await queueMorning(store);
    await engine.run();
    expect(server.devices[0]?.device_id).toBe("pixel-1");
    expect(store.get().mockSeen).toBe(false);
  });
});
