import { colors } from "@fleettms/design-tokens";
import { useNetInfo } from "@react-native-community/netinfo";
import { useEffect, useState, useSyncExternalStore } from "react";
import { ActivityIndicator, Text, View } from "react-native";
import { useAuth } from "./auth";
import { connection } from "./connection";
import { useTheme } from "./ui";

const SHOW_AFTER_MS = 400; // a quick request never flashes the spinner

/** A thin strip under the header while the server is being asked for something that is slow to come. */
export function LoadingStrip() {
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
  if (!show) return null;
  return (
    <View
      accessibilityRole="progressbar"
      accessibilityLabel="Loading"
      style={{ position: "absolute", top: 8, right: 12, zIndex: 10 }}
    >
      <ActivityIndicator color={colors.brand} />
    </View>
  );
}

/** Says so when there is no network, and how old the information on screen is. */
export function OfflineBanner() {
  const { view } = useAuth();
  const net = useNetInfo();
  const { staleSince } = useSyncExternalStore(connection.subscribe, connection.get);
  const offline = net.isConnected === false || net.isInternetReachable === false;
  if (!offline && !staleSince) return null;
  const when = staleSince
    ? new Date(staleSince).toLocaleString([], {
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      })
    : null;
  return (
    <View
      accessibilityRole="alert"
      style={{ backgroundColor: colors.warning, paddingVertical: 6, paddingHorizontal: 12 }}
    >
      <Text style={{ color: "#1f1300", fontSize: 14, fontWeight: "600" }}>
        {when
          ? `Offline. Showing what was saved on ${when}.`
          : view === "driver"
            ? "Offline. Your work is kept and sent when you are back online."
            : "Offline. Changes cannot be made until you are back online."}
      </Text>
    </View>
  );
}

/** Full-screen wait shown while the app starts. */
export function Splash({ label = "Loading..." }: { label?: string }) {
  const t = useTheme();
  return (
    <View
      accessibilityLiveRegion="polite"
      style={{
        flex: 1,
        justifyContent: "center",
        alignItems: "center",
        gap: 12,
        backgroundColor: t.bg,
      }}
    >
      <ActivityIndicator size="large" color={colors.brand} />
      <Text style={{ color: t.muted, fontSize: 16 }}>{label}</Text>
    </View>
  );
}
