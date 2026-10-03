import { describe, expect, it } from "vitest";
import { createVault } from "../offline/vault";
import { ApiFailure, memoryFiles, memoryKeys, random } from "../offline/testkit";
import { BATCH_SIZE, createTracker, MAX_POINTS, type Fix } from "./tracker";

const NOW = new Date("2026-10-02T08:00:00Z");
const fix = (seconds: number, extra: Partial<Fix> = {}): Fix => ({
  recorded_at: new Date(NOW.getTime() + seconds * 1000).toISOString(),
  lat: -1.29 + seconds * 0.00001,
  lng: 36.82,
  speed_kmh: 50,
  heading: 90,
  accuracy_m: 10,
  ...extra,
});

function rig(now = () => NOW) {
  const files = memoryFiles();
  const keys = memoryKeys();
  const vault = createVault(keys, random);
  const sent: { tripId: string; points: Fix[] }[] = [];
  const server = {
    fail: [] as (Error | ApiFailure)[],
    sendLocations: async (tripId: string, points: Fix[]) => {
      const next = server.fail.shift();
      if (next) throw next;
      sent.push({ tripId, points });
      return {};
    },
  };
  const make = () => createTracker({ files, vault, api: server, now });
  return { files, keys, vault, sent, server, make, tracker: make() };
}

describe("collecting", () => {
  it("keeps nothing when no trip has begun", async () => {
    const { tracker, files } = rig();
    expect(await tracker.add([fix(0), fix(10)])).toBe(0);
    expect(tracker.waiting()).toBe(0);
    expect(tracker.isTracking()).toBe(false);
    expect(files.disk.size).toBe(0);
  });

  it("collects fixes for the trip that has begun, in time order, once each", async () => {
    const { tracker } = rig();
    await tracker.begin("trip-1");
    expect(tracker.isTracking()).toBe(true);
    expect(await tracker.add([fix(20), fix(0), fix(10)])).toBe(3);
    expect(await tracker.add([fix(10), fix(30)])).toBe(1); // the one it already had is not kept twice
    expect(tracker.waiting()).toBe(4);
  });

  it("drops fixes that are too vague or not on the globe", async () => {
    const { tracker } = rig();
    await tracker.begin("trip-1");
    expect(
      await tracker.add([
        fix(0, { accuracy_m: 250 }),
        fix(1, { lat: 99 }),
        fix(2, { accuracy_m: 100 }),
        fix(3, { accuracy_m: null }),
      ]),
    ).toBe(2);
  });

  it("stops keeping fixes the moment the trip ends", async () => {
    const times = [new Date("2026-10-02T08:05:00Z")];
    const { tracker } = rig(() => times[0]!);
    await tracker.begin("trip-1");
    await tracker.add([fix(0), fix(120)]);
    await tracker.end();
    expect(tracker.isTracking()).toBe(false);
    expect(await tracker.add([fix(299), fix(301), fix(900)])).toBe(1); // only the one taken before 08:05:00
    expect(tracker.waiting()).toBe(3);
  });

  it("keeps fixes waiting for the same trip if it begins again, but starts clean for another trip", async () => {
    const { tracker } = rig();
    await tracker.begin("trip-1");
    await tracker.add([fix(0)]);
    await tracker.begin("trip-1");
    expect(tracker.waiting()).toBe(1);
    await tracker.begin("trip-2");
    expect(tracker.waiting()).toBe(0);
  });

  it("holds no more than the cap, dropping the oldest, and nothing older than three days", async () => {
    const { tracker } = rig();
    await tracker.begin("trip-1");
    await tracker.add(Array.from({ length: MAX_POINTS + 50 }, (_, i) => fix(i)));
    expect(tracker.waiting()).toBe(MAX_POINTS);
    await tracker.add([fix(-4 * 86400)]);
    expect(tracker.waiting()).toBe(MAX_POINTS); // too old to be worth sending
  });
});

describe("sending", () => {
  it("sends what is waiting in batches and clears it", async () => {
    const { tracker, sent } = rig();
    await tracker.begin("trip-1");
    await tracker.add(Array.from({ length: BATCH_SIZE + 20 }, (_, i) => fix(i)));
    const res = await tracker.flush();
    expect(res).toEqual({ status: "done", sent: BATCH_SIZE + 20 });
    expect(sent.map((s) => s.points.length)).toEqual([BATCH_SIZE, 20]);
    expect(sent.every((s) => s.tripId === "trip-1")).toBe(true);
    expect(tracker.waiting()).toBe(0);
    expect(tracker.isTracking()).toBe(true); // still on the trip
  });

  it("keeps the fixes when there is no network and sends them later", async () => {
    const { tracker, server, sent } = rig();
    await tracker.begin("trip-1");
    await tracker.add([fix(0), fix(10)]);
    server.fail.push(new TypeError("Network request failed"));
    expect(await tracker.flush()).toEqual({ status: "offline" });
    expect(tracker.waiting()).toBe(2);
    expect((await tracker.flush()).status).toBe("done");
    expect(sent).toHaveLength(1);
  });

  it("keeps the fixes when the server has not started the trip yet", async () => {
    const { tracker, server } = rig();
    await tracker.begin("trip-1");
    await tracker.add([fix(0)]);
    server.fail.push(new ApiFailure(409, "not_tracking"));
    expect(await tracker.flush()).toEqual({ status: "waiting" });
    expect(tracker.waiting()).toBe(1);
  });

  it("gives up on a trip the server says is not ours, and on a signed-out phone keeps them", async () => {
    const { tracker, server } = rig();
    await tracker.begin("trip-1");
    await tracker.add([fix(0)]);
    server.fail.push(new ApiFailure(401, "not_authenticated"));
    expect(await tracker.flush()).toEqual({ status: "signed_out" });
    expect(tracker.waiting()).toBe(1);
    server.fail.push(new ApiFailure(404, "not_found"));
    expect(await tracker.flush()).toEqual({ status: "idle" });
    expect(tracker.waiting()).toBe(0);
    expect(tracker.tripId()).toBeNull();
  });

  it("after the trip ends, hands in what is left and then forgets the trip", async () => {
    const { tracker, sent } = rig();
    await tracker.begin("trip-1");
    await tracker.add([fix(0), fix(10)]);
    await tracker.end();
    expect((await tracker.flush()).status).toBe("done");
    expect(sent[0]!.points).toHaveLength(2);
    expect(tracker.tripId()).toBeNull();
    expect(await tracker.add([fix(5)])).toBe(0); // nothing is kept once the trip is over
    expect((await tracker.flush()).status).toBe("idle");
  });

  it("a trip that ends with nothing waiting is forgotten at the next flush", async () => {
    const { tracker } = rig();
    await tracker.begin("trip-1");
    await tracker.end();
    expect((await tracker.flush()).status).toBe("idle");
    expect(tracker.tripId()).toBeNull();
  });

  it("calls made while a send is running share it", async () => {
    const { tracker, sent } = rig();
    await tracker.begin("trip-1");
    await tracker.add([fix(0)]);
    const [a, b] = await Promise.all([tracker.flush(), tracker.flush()]);
    expect(a).toBe(b);
    expect(sent).toHaveLength(1);
  });
});

describe("keeping safe", () => {
  it("survives the app being closed: a new tracker reads what the old one saved", async () => {
    const { tracker, make } = rig();
    await tracker.begin("trip-1");
    await tracker.add([fix(0), fix(10)]);
    const reopened = make();
    await reopened.load();
    expect(reopened.isTracking()).toBe(true);
    expect(reopened.tripId()).toBe("trip-1");
    expect(reopened.waiting()).toBe(2);
  });

  it("is stored encrypted, not as readable positions", async () => {
    const { tracker, files } = rig();
    await tracker.begin("trip-1");
    await tracker.add([fix(0, { lat: -1.2921, lng: 36.8219 })]);
    const raw = [...files.disk.values()].join("");
    expect(raw).not.toContain("-1.2921");
    expect(raw).not.toContain("trip-1");
  });

  it("starts clean when the saved file cannot be read", async () => {
    const { tracker, files, make } = rig();
    await tracker.begin("trip-1");
    files.disk.set("track.enc", "AAAA");
    const reopened = make();
    await reopened.load();
    expect(reopened.tripId()).toBeNull();
    expect(tracker.waiting()).toBe(0);
  });

  it("signing out removes everything", async () => {
    const { tracker, files } = rig();
    await tracker.begin("trip-1");
    await tracker.add([fix(0)]);
    await tracker.clear();
    expect(files.disk.size).toBe(0);
    expect(tracker.tripId()).toBeNull();
  });
});
