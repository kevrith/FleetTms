import * as Application from "expo-application";
import * as Updates from "expo-updates";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { AppState, Platform } from "react-native";
import { downloadApk, fetchRelease, forgetOldDownloads, installApk } from "./apk";
import {
  canSelfInstall,
  distributionOf,
  dueForCheck,
  newerRelease,
  type Distribution,
  type Release,
} from "./logic";

type Phase = "idle" | "downloading" | "ready" | "installing" | "failed";

export interface AppUpdate {
  distribution: Distribution;
  /** The installed build's versionCode and name; null in Expo Go or when the phone does not say. */
  installedCode: number | null;
  installedVersion: string;
  /** An over-the-air update (a change to the app's screens and logic) is downloaded and waits for a restart. */
  otaReady: boolean;
  /** A newer APK exists and this phone may install it itself. */
  release: Release | null;
  phase: Phase;
  progress: number;
  error: string | null;
  /** The server has said this build is too old to be used. */
  required: boolean;
  checking: boolean;
  /** True once a check has finished and found nothing, so the person can be told they are up to date. */
  upToDate: boolean;
  checkNow: () => Promise<void>;
  download: () => Promise<void>;
  install: () => Promise<void>;
  restart: () => Promise<void>;
}

const Ctx = createContext<AppUpdate | null>(null);

let upgradeListener: () => void = () => {};
/** The API client calls this when the server answers 426 app_outdated. */
export const onUpgradeRequired = (fn: () => void) => {
  upgradeListener = fn;
};
export const signalUpgradeRequired = () => upgradeListener();

const distribution = distributionOf(process.env.EXPO_PUBLIC_DISTRIBUTION);
const installedCode = Number.isInteger(Number(Application.nativeBuildVersion))
  ? Number(Application.nativeBuildVersion)
  : null;

export function UpdatesProvider({ children }: { children: ReactNode }) {
  const { isUpdatePending } = Updates.useUpdates();
  const [release, setRelease] = useState<Release | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [required, setRequired] = useState(false);
  const [checking, setChecking] = useState(false);
  const [upToDate, setUpToDate] = useState(false);
  const lastChecked = useRef<number | null>(null);
  const file = useRef<string | null>(null);
  const selfInstall = canSelfInstall(distribution, Platform.OS);

  useEffect(() => {
    onUpgradeRequired(() => setRequired(true));
    if (installedCode !== null) void forgetOldDownloads(installedCode);
  }, []);

  const checkNow = useCallback(async () => {
    setChecking(true);
    setUpToDate(false);
    try {
      let found = false;
      if (Updates.isEnabled) {
        try {
          const result = await Updates.checkForUpdateAsync();
          if (result.isAvailable) {
            await Updates.fetchUpdateAsync(); // the Updates hook then reports it as pending
            found = true;
          }
        } catch {
          /* offline, or the update service is not reachable: the next check tries again */
        }
      }
      if (selfInstall) {
        const newer = newerRelease(installedCode, await fetchRelease());
        setRelease(newer);
        found = found || newer !== null;
      }
      lastChecked.current = Date.now();
      setUpToDate(!found);
    } finally {
      setChecking(false);
    }
  }, [selfInstall]);

  // Looks when the app opens and whenever it comes back, but not more than every few hours.
  useEffect(() => {
    const maybe = () => {
      if (dueForCheck(lastChecked.current, Date.now())) void checkNow();
    };
    maybe();
    const sub = AppState.addEventListener("change", (s) => s === "active" && maybe());
    return () => sub.remove();
  }, [checkNow]);

  const download = useCallback(async () => {
    if (!release) return;
    setPhase("downloading");
    setProgress(0);
    setError(null);
    try {
      file.current = await downloadApk(release, setProgress);
      setPhase("ready");
    } catch (e) {
      setError(e instanceof Error ? e.message : "The download did not finish.");
      setPhase("failed");
    }
  }, [release]);

  const install = useCallback(async () => {
    if (!file.current) return;
    setPhase("installing");
    setError(null);
    try {
      await installApk(file.current);
      setPhase("ready"); // back from the installer without installing: it can be opened again
    } catch {
      setError(
        "Android would not open the installer. Open the downloaded file from your Downloads, or use the download link.",
      );
      setPhase("failed");
    }
  }, []);

  const restart = useCallback(async () => {
    await Updates.reloadAsync();
  }, []);

  const value = useMemo<AppUpdate>(
    () => ({
      distribution,
      installedCode,
      installedVersion: Application.nativeApplicationVersion ?? "",
      otaReady: isUpdatePending,
      release,
      phase,
      progress,
      error,
      required,
      checking,
      upToDate,
      checkNow,
      download,
      install,
      restart,
    }),
    [
      isUpdatePending,
      release,
      phase,
      progress,
      error,
      required,
      checking,
      upToDate,
      checkNow,
      download,
      install,
      restart,
    ],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAppUpdate(): AppUpdate {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAppUpdate needs UpdatesProvider");
  return v;
}
