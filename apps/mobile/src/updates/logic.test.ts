import { describe, expect, it } from "vitest";
import {
  canSelfInstall,
  CHECK_EVERY_MS,
  distributionOf,
  dueForCheck,
  newerRelease,
  parseRelease,
} from "./logic";

const good = {
  version: "0.3.0",
  version_code: 12,
  apk_url: "https://example.com/fleettms.apk",
  md5: "0123456789abcdef0123456789ABCDEF",
  size_bytes: 61_000_000,
  notes: "Fuel use page",
};

describe("parseRelease", () => {
  it("accepts what the release workflow publishes", () => {
    expect(parseRelease(good)).toEqual({ ...good, md5: "0123456789abcdef0123456789abcdef" });
  });
  it("refuses anything that is not a whole, https release", () => {
    expect(parseRelease(null)).toBeNull();
    expect(parseRelease({ ...good, apk_url: "http://example.com/a.apk" })).toBeNull();
    expect(parseRelease({ ...good, version_code: "twelve" })).toBeNull();
    expect(parseRelease({ ...good, version_code: 0 })).toBeNull();
    expect(parseRelease({ ...good, version: undefined })).toBeNull();
  });
  it("ignores a checksum or size that is not usable instead of trusting it", () => {
    expect(parseRelease({ ...good, md5: "nope", size_bytes: -5 })).toMatchObject({
      md5: null,
      size_bytes: null,
    });
  });
});

describe("newerRelease", () => {
  const release = parseRelease(good);
  it("offers only a higher build", () => {
    expect(newerRelease(11, release)?.version_code).toBe(12);
    expect(newerRelease(12, release)).toBeNull();
    expect(newerRelease(13, release)).toBeNull();
  });
  it("offers nothing when the installed build or the release is unknown", () => {
    expect(newerRelease(null, release)).toBeNull();
    expect(newerRelease(11, null)).toBeNull();
  });
});

describe("where an app may update itself", () => {
  it("only from the download link on Android", () => {
    expect(canSelfInstall("sideload", "android")).toBe(true);
    expect(canSelfInstall("play", "android")).toBe(false);
    expect(canSelfInstall("dev", "android")).toBe(false);
    expect(canSelfInstall("sideload", "ios")).toBe(false);
  });
  it("reads the build setting, treating anything else as a development build", () => {
    expect(distributionOf("sideload")).toBe("sideload");
    expect(distributionOf("play")).toBe("play");
    expect(distributionOf(undefined)).toBe("dev");
    expect(distributionOf("beta")).toBe("dev");
  });
});

describe("dueForCheck", () => {
  it("checks the first time, after six hours, and if the clock went backwards", () => {
    expect(dueForCheck(null, 1000)).toBe(true);
    expect(dueForCheck(1000, 1000 + CHECK_EVERY_MS - 1)).toBe(false);
    expect(dueForCheck(1000, 1000 + CHECK_EVERY_MS)).toBe(true);
    expect(dueForCheck(5000, 1000)).toBe(true);
  });
});
