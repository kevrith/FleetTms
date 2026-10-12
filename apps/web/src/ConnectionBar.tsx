import { Loader2, WifiOff } from "lucide-react";
import { useEffect, useState, useSyncExternalStore } from "react";
import { connection } from "./connection";

const SHOW_AFTER_MS = 400; // a quick request never flashes the bar

function subscribeOnline(listener: () => void) {
  window.addEventListener("online", listener);
  window.addEventListener("offline", listener);
  return () => {
    window.removeEventListener("online", listener);
    window.removeEventListener("offline", listener);
  };
}
export const useBrowserOnline = () => useSyncExternalStore(subscribeOnline, () => navigator.onLine);

/** A thin bar across the top while the server is being asked for something that is slow to come. */
export function LoadingBar() {
  const { pending } = useSyncExternalStore(connection.subscribe, connection.get);
  const [show, setShow] = useState(false);
  useEffect(() => {
    if (pending === 0) {
      setShow(false);
      return;
    }
    const timer = setTimeout(() => setShow(true), SHOW_AFTER_MS);
    return () => clearTimeout(timer);
  }, [pending > 0]); // eslint-disable-line react-hooks/exhaustive-deps
  return show ? <div className="loading-bar" role="progressbar" aria-label="Loading" /> : null;
}

/** Says so when the browser has no network, and how old the information on screen is. */
export function OfflineNotice() {
  const online = useBrowserOnline();
  const { staleSince } = useSyncExternalStore(connection.subscribe, connection.get);
  if (online && !staleSince) return null;
  const when = staleSince
    ? new Date(staleSince).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })
    : null;
  return (
    <p className="offline-notice" role="status">
      <WifiOff size={16} />
      {when
        ? `You are offline. Showing what was saved on ${when}. Changes cannot be made until you are back online.`
        : "You are offline. Changes cannot be made until you are back online."}
    </p>
  );
}

/** Full-page wait shown while the app starts. */
export function Splash({ label = "Loading..." }: { label?: string }) {
  return (
    <div className="splash" role="status" aria-live="polite">
      <img src="/logo.png" alt="" width={64} height={64} />
      <Loader2 className="spin" size={28} />
      <p className="muted">{label}</p>
    </div>
  );
}
