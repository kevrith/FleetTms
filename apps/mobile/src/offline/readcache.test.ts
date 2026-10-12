import { describe, expect, it } from "vitest";
import { createReadCache } from "./readcache";
import { makeStore } from "./testkit";
import { createVault } from "./vault";
import { random } from "./testkit";

function setup() {
  const { files, keys } = makeStore();
  const vault = createVault(keys, random);
  return { files, keys, vault, cache: createReadCache({ files, vault }) };
}
const entry = (n: number) => ({ at: "2026-10-12T08:00:00Z", data: { n } });

describe("saved replies", () => {
  it("returns what was saved, and survives the app restarting", async () => {
    const { files, vault, cache } = setup();
    await cache.set("/vehicles", entry(1));
    expect(await cache.get("/vehicles")).toEqual(entry(1));
    await cache.flush();
    const reopened = createReadCache({ files, vault });
    expect(await reopened.get("/vehicles")).toEqual(entry(1));
    expect(await reopened.get("/depots")).toBeNull();
  });

  it("is encrypted on disk", async () => {
    const { files, cache } = setup();
    await cache.set("/vehicles", { at: "2026-10-12T08:00:00Z", data: { reg: "KDA 123A" } });
    await cache.flush();
    const onDisk = files.disk.get("reads.enc") ?? "";
    expect(onDisk.length).toBeGreaterThan(0);
    expect(onDisk).not.toContain("KDA");
    expect(onDisk).not.toContain("vehicles");
  });

  it("forgets everything on clear, including what is on disk", async () => {
    const { files, vault, cache } = setup();
    await cache.set("/vehicles", entry(1));
    await cache.flush();
    await cache.clear();
    expect(await cache.get("/vehicles")).toBeNull();
    expect(files.disk.has("reads.enc")).toBe(false);
    expect(await createReadCache({ files, vault }).get("/vehicles")).toBeNull();
  });

  it("starts empty if the file cannot be opened (key lost)", async () => {
    const { files, cache } = setup();
    await cache.set("/vehicles", entry(1));
    await cache.flush();
    const other = createReadCache({ files, vault: createVault(makeStore().keys, random) });
    expect(await other.get("/vehicles")).toBeNull();
  });

  it("keeps the newest 80 and drops the oldest", async () => {
    const { cache } = setup();
    for (let i = 0; i < 85; i++) await cache.set(`/p/${i}`, entry(i));
    expect(await cache.get("/p/0")).toBeNull();
    expect(await cache.get("/p/4")).toBeNull();
    expect(await cache.get("/p/5")).toEqual(entry(5));
    expect(await cache.get("/p/84")).toEqual(entry(84));
  });

  it("does not keep an enormous reply", async () => {
    const { cache } = setup();
    await cache.set("/big", { at: "x", data: "a".repeat(1_100_000) });
    expect(await cache.get("/big")).toBeNull();
  });
});
