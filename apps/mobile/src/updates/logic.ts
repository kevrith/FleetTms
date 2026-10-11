/** Deciding what to offer for updating the app. Pure, so it is tested without a phone. */

export interface Release {
  version: string;
  /** Android's versionCode of that build: only a higher one can be installed over this one. */
  version_code: number;
  apk_url: string;
  md5: string | null;
  size_bytes: number | null;
  notes: string;
}

export type Distribution = "sideload" | "play" | "dev";

/** What the release workflow publishes beside the APK (latest.json), checked before it is believed. */
export function parseRelease(raw: unknown): Release | null {
  if (typeof raw !== "object" || raw === null) return null;
  const r = raw as Record<string, unknown>;
  if (typeof r.version !== "string" || typeof r.apk_url !== "string") return null;
  const code = Number(r.version_code);
  if (!Number.isInteger(code) || code < 1) return null;
  if (!/^https:\/\//.test(r.apk_url)) return null;
  return {
    version: r.version,
    version_code: code,
    apk_url: r.apk_url,
    md5: typeof r.md5 === "string" && /^[0-9a-f]{32}$/i.test(r.md5) ? r.md5.toLowerCase() : null,
    size_bytes: typeof r.size_bytes === "number" && r.size_bytes > 0 ? r.size_bytes : null,
    notes: typeof r.notes === "string" ? r.notes.slice(0, 500) : "",
  };
}

/**
 * Only a phone with the app installed from the download link updates itself that way. A Play Store install is updated by Play (and Google
 * does not allow an app to download its own APK), and a development build or Expo Go has nothing to install.
 */
export const canSelfInstall = (distribution: Distribution, platform: string) =>
  distribution === "sideload" && platform === "android";

/** The release if it is newer than the installed build, otherwise null. */
export function newerRelease(
  installedCode: number | null,
  release: Release | null,
): Release | null {
  if (!release || installedCode === null) return null;
  return release.version_code > installedCode ? release : null;
}

export const CHECK_EVERY_MS = 6 * 60 * 60 * 1000;

/** Whether enough time has passed to look again (a phone coming back to the app many times a day should not ask every time). */
export const dueForCheck = (lastCheckedAt: number | null, now: number) =>
  lastCheckedAt === null || now - lastCheckedAt >= CHECK_EVERY_MS || now < lastCheckedAt;

export const distributionOf = (value: string | undefined): Distribution =>
  value === "sideload" || value === "play" ? value : "dev";

export const megabytes = (bytes: number | null) =>
  bytes === null ? "" : `${(bytes / (1024 * 1024)).toFixed(0)} MB`;
