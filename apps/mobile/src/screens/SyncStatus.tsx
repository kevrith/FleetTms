import { Text, View } from "react-native";
import { colors } from "@fleettms/design-tokens";
import { useOffline } from "../offline/runtime";
import type { ActionType } from "../offline/types";
import { Body, Button, useTheme } from "../ui";

const TYPE_LABEL: Record<ActionType, string> = {
  "inspection.submit": "Pre-trip inspection",
  "trip.start": "Trip start",
  "trip.loading": "Cargo photo",
  "trip.deliver": "Delivery",
  "trip.end": "Trip end",
  "fuel.add": "Fuel entry",
};

/** One line that says whether the driver's work has reached the office: synced, waiting, offline or stuck. */
export function SyncBadge() {
  const t = useTheme();
  const { online, syncing, pending, attention } = useOffline();
  let text = "All synced";
  let color: string = colors.ok;
  if (attention.length > 0) {
    text = `${attention.length} need${attention.length === 1 ? "s" : ""} attention`;
    color = colors.alert;
  } else if (!online) {
    text = pending > 0 ? `Offline. ${pending} waiting to send` : "Offline";
    color = colors.warning;
  } else if (syncing) {
    text = "Syncing...";
    color = t.muted;
  } else if (pending > 0) {
    text = `${pending} waiting to send`;
    color = colors.warning;
  }
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
      <View style={{ width: 10, height: 10, borderRadius: 5, backgroundColor: color }} />
      <Text accessibilityRole="text" style={{ color: t.text, fontSize: 15 }}>
        {text}
      </Text>
    </View>
  );
}

/** Records the office could not accept, with the reason and the choice to try again or drop them. */
export function AttentionList() {
  const t = useTheme();
  const { attention, retry, discard } = useOffline();
  if (attention.length === 0) return null;
  return (
    <View style={{ gap: 8 }}>
      <Body>These could not be sent:</Body>
      {attention.map((item) => (
        <View
          key={item.id}
          style={{ padding: 12, borderRadius: 12, backgroundColor: t.surface, gap: 6 }}
        >
          <Text style={{ color: t.text, fontSize: 17, fontWeight: "600" }}>
            {TYPE_LABEL[item.type]}
          </Text>
          <Body muted>{item.message ?? "The office could not accept this."}</Body>
          <View style={{ flexDirection: "row", gap: 8 }}>
            <View style={{ flex: 1 }}>
              <Button label="Try again" kind="secondary" onPress={() => void retry(item.id)} />
            </View>
            <View style={{ flex: 1 }}>
              <Button label="Delete" kind="danger" onPress={() => void discard(item.id)} />
            </View>
          </View>
        </View>
      ))}
    </View>
  );
}
