import type { LiveMap, MapVehicle } from "@fleettms/types";
import { useCallback, useEffect, useState } from "react";
import { Linking, Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import { api } from "../api";
import { Body, ErrorText, errorMessage, Title, useTheme } from "../ui";

const STATE: Record<string, { label: string; colour: string }> = {
  moving: { label: "Moving", colour: "#16a34a" },
  idle: { label: "Standing on a trip", colour: "#d97706" },
  offline: { label: "Not reporting", colour: "#dc2626" },
  parked: { label: "Parked", colour: "#475569" },
  unknown: { label: "Never seen", colour: "#94a3b8" },
};

const ago = (s: number | null) =>
  s === null
    ? ""
    : s < 90
      ? "just now"
      : s < 3600
        ? `${Math.round(s / 60)} min ago`
        : s < 86400
          ? `${Math.round(s / 3600)} h ago`
          : `${Math.round(s / 86400)} days ago`;

/** Owner view: where every lorry is. Tapping one opens its position in the phone's maps app (the full map is on the web). */
export default function FleetScreen() {
  const t = useTheme();
  const [data, setData] = useState<LiveMap | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const load = useCallback(async () => {
    try {
      setData(await api.liveMap());
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => {
    void load();
    const timer = setInterval(load, 20000);
    return () => clearInterval(timer);
  }, [load]);
  const open = (v: MapVehicle) => {
    if (!v.position) return;
    const { lat, lng } = v.position;
    void Linking.openURL(
      `geo:${lat},${lng}?q=${lat},${lng}(${encodeURIComponent(v.registration)})`,
    );
  };
  return (
    <ScrollView
      contentContainerStyle={{ gap: 12, padding: 16 }}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={async () => {
            setRefreshing(true);
            await load();
            setRefreshing(false);
          }}
        />
      }
    >
      <Title>Where the lorries are</Title>
      <ErrorText message={error} />
      {(data?.vehicles ?? []).map((v) => (
        <Pressable
          key={v.vehicle_id}
          onPress={() => open(v)}
          accessibilityRole="button"
          style={{
            padding: 14,
            borderRadius: 12,
            backgroundColor: t.surface,
            borderLeftWidth: 6,
            borderLeftColor: STATE[v.state]?.colour,
            gap: 2,
          }}
        >
          <Text style={{ color: t.text, fontSize: 18, fontWeight: "700" }}>{v.registration}</Text>
          <Body>
            {STATE[v.state]?.label}
            {v.going_dark ? ", went dark" : ""}
            {v.position?.speed_kmh != null && v.state === "moving"
              ? `, ${Math.round(v.position.speed_kmh)} km/h`
              : ""}
          </Body>
          {v.trip && (
            <Body muted>{[v.trip.origin, v.trip.destination].filter(Boolean).join(" to ")}</Body>
          )}
          {v.position && <Body muted>Heard {ago(v.age_seconds)}. Tap to see it on the map.</Body>}
        </Pressable>
      ))}
      {data && data.vehicles.length === 0 && (
        <View>
          <Body muted>No vehicles yet.</Body>
        </View>
      )}
    </ScrollView>
  );
}
