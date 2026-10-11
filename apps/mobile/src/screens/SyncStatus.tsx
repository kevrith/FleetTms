import { useEffect, useState } from "react";
import { Text, View } from "react-native";
import { colors } from "@fleettms/design-tokens";
import { api } from "../api";
import { explainRejection, tripIdOf } from "../offline/explain";
import { useOffline } from "../offline/runtime";
import type { ActionType, QueueItem } from "../offline/types";
import { Body, Button, useTheme } from "../ui";

const TYPE_LABEL: Record<ActionType, string> = {
  "inspection.submit": "Pre-trip inspection",
  "trip.start": "Trip start",
  "trip.loading": "Cargo photo",
  "trip.deliver": "Delivery",
  "trip.end": "Trip end",
  "fuel.add": "Fuel entry",
  "expense.add": "Expense",
  "reconciliation.submit": "End-of-day report",
  "incident.report": "Problem report",
  "repair.request": "Repair request",
  "renewal.submit": "Licence renewal",
  "sos.send": "SOS",
};

/** One line that says whether the driver's work has reached the office: synced, waiting, offline or stuck. */
export function SyncBadge() {
  const t = useTheme();
  const { online, syncing, pending, attention } = useOffline();
  let text = "All synced";
  let color: string = colors.ok;
  if (attention.length > 0) {
    const what = [...new Set(attention.map((i) => TYPE_LABEL[i.type]))].join(", ");
    text = `${attention.length} need${attention.length === 1 ? "s" : ""} attention: ${what}`;
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

/** What the office shows for a trip, found out while the phone has a network (it asks only for items refused for being at the wrong step). */
function useServerTripStatus(attention: QueueItem[]): Record<string, string> {
  const [states, setStates] = useState<Record<string, string>>({});
  const wanted = attention
    .filter((i) => i.code === "wrong_status")
    .map((i) => tripIdOf(i.payload))
    .filter((id): id is string => id !== null);
  const key = [...new Set(wanted)].join(",");
  useEffect(() => {
    for (const id of key ? key.split(",") : []) {
      api
        .trip(id)
        .then((trip) => setStates((s) => ({ ...s, [id]: trip.status })))
        .catch(() => undefined); // offline: the explanation just says less
    }
  }, [key]);
  return states;
}

/** Records the office could not accept, with what happened, what to do, and the choice to try again or drop them. */
export function AttentionList() {
  const t = useTheme();
  const { attention, retry, discard, state } = useOffline();
  const states = useServerTripStatus(attention);
  if (attention.length === 0) return null;
  const mine = state.cache.trip;
  return (
    <View style={{ gap: 8 }}>
      <Body>These could not be sent:</Body>
      {attention.map((item) => {
        const tripId = tripIdOf(item.payload);
        const e = explainRejection(item, tripId ? (states[tripId] ?? null) : null);
        const where =
          tripId && mine?.id === tripId && (mine.origin || mine.destination)
            ? `${mine.origin ?? "?"} to ${mine.destination ?? "?"}`
            : null;
        return (
          <View
            key={item.id}
            style={{ padding: 12, borderRadius: 12, backgroundColor: t.surface, gap: 6 }}
          >
            <Text style={{ color: t.text, fontSize: 17, fontWeight: "600" }}>
              {TYPE_LABEL[item.type]}
              {where ? ` (${where})` : ""}
            </Text>
            <Body>{e.why}</Body>
            <Body muted>{e.hint}</Body>
            <View style={{ flexDirection: "row", gap: 8 }}>
              <View style={{ flex: 1 }}>
                <Button label="Try again" kind="secondary" onPress={() => void retry(item.id)} />
              </View>
              <View style={{ flex: 1 }}>
                <Button label="Delete" kind="danger" onPress={() => void discard(item.id)} />
              </View>
            </View>
          </View>
        );
      })}
    </View>
  );
}
