import * as FileSystem from "expo-file-system";
import * as IntentLauncher from "expo-intent-launcher";
import { parseRelease, type Release } from "./logic";

/** Where the release workflow publishes the description of the newest APK, beside the APK itself. */
export const RELEASE_URL =
  process.env.EXPO_PUBLIC_UPDATE_URL ??
  "https://github.com/kevrith/FleetTms/releases/download/mobile-latest/latest.json";

const apkPath = (release: Release) =>
  `${FileSystem.cacheDirectory}fleettms-${release.version_code}.apk`;

/** The newest release, or null when it cannot be read (offline, or no release published yet). Never throws. */
export async function fetchRelease(): Promise<Release | null> {
  try {
    const res = await fetch(`${RELEASE_URL}?t=${Date.now()}`, {
      headers: { "Cache-Control": "no-cache" },
    });
    return res.ok ? parseRelease(await res.json()) : null;
  } catch {
    return null;
  }
}

export class DownloadError extends Error {}

/** True when the file already on the phone is this release, whole. */
async function isWhole(release: Release, uri: string): Promise<boolean> {
  const info = await FileSystem.getInfoAsync(uri, { md5: true });
  if (!info.exists) return false;
  if (release.size_bytes !== null && info.size !== release.size_bytes) return false;
  return release.md5 === null || info.md5 === release.md5;
}

/** Downloads the APK to the app's own cache and checks it is whole. Android itself checks that it is signed by the same key as the app. */
export async function downloadApk(
  release: Release,
  onProgress: (share: number) => void,
): Promise<string> {
  const uri = apkPath(release);
  if (await isWhole(release, uri)) {
    onProgress(1);
    return uri;
  }
  const job = FileSystem.createDownloadResumable(release.apk_url, uri, {}, (p) => {
    const total =
      p.totalBytesExpectedToWrite > 0 ? p.totalBytesExpectedToWrite : (release.size_bytes ?? 0);
    if (total > 0) onProgress(Math.min(1, p.totalBytesWritten / total));
  });
  const result = await job.downloadAsync();
  if (!result || result.status !== 200) {
    await FileSystem.deleteAsync(uri, { idempotent: true });
    throw new DownloadError("The download did not finish. Check your connection and try again.");
  }
  if (!(await isWhole(release, uri))) {
    await FileSystem.deleteAsync(uri, { idempotent: true });
    throw new DownloadError("The downloaded file was damaged. Try again.");
  }
  return uri;
}

/** Opens Android's installer for the downloaded APK. The person still taps Install, and may first be asked to allow installs from this app. */
export async function installApk(uri: string): Promise<void> {
  const contentUri = await FileSystem.getContentUriAsync(uri);
  await IntentLauncher.startActivityAsync("android.intent.action.VIEW", {
    data: contentUri,
    flags: 1, // FLAG_GRANT_READ_URI_PERMISSION
    type: "application/vnd.android.package-archive",
  });
}

/** Removes APKs left in the cache by an update that has since been installed. */
export async function forgetOldDownloads(installedCode: number): Promise<void> {
  try {
    const names = await FileSystem.readDirectoryAsync(FileSystem.cacheDirectory ?? "");
    for (const name of names) {
      const code = /^fleettms-(\d+)\.apk$/.exec(name)?.[1];
      if (code && Number(code) <= installedCode) {
        await FileSystem.deleteAsync(`${FileSystem.cacheDirectory}${name}`, { idempotent: true });
      }
    }
  } catch {
    /* the cache is cleaned by Android anyway */
  }
}
