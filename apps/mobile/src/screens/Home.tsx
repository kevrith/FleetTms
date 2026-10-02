import { formatKes, ROLE_LABELS } from "@fleettms/business-rules";
import type { Dashboard } from "@fleettms/types";
import { useEffect, useState } from "react";
import { ScrollView, Text, View } from "react-native";
import { api } from "../api";
import { useAuth } from "../auth";
import { Body, Screen, Title, useTheme } from "../ui";
import { useOffline } from "../offline/runtime";
import { AttentionList, SyncBadge } from "./SyncStatus";
import TripPanel from "./TripPanel";

function MyVehicleCard() {
  const t = useTheme();
  const { vehicle: mine } = useOffline().state.cache;
  if (!mine) return null;
  return (
    <View style={{ padding: 16, borderRadius: 12, backgroundColor: t.surface, gap: 4 }}>
      <Body muted>My vehicle</Body>
      <Text style={{ color: t.text, fontSize: 24, fontWeight: "600" }}>
        {mine.vehicle.registration}
      </Text>
      <Body>{[mine.vehicle.make, mine.vehicle.model].filter(Boolean).join(" ")}</Body>
      <Body muted>
        {mine.vehicle.capacity_tonnes ? `${mine.vehicle.capacity_tonnes} t, ` : ""}
        {mine.vehicle.odometer_km.toLocaleString()} km
      </Body>
      {mine.crew.map((c) => (
        <Body key={`${c.role}-${c.name}`} muted>
          {c.role === "driver" ? "Driver" : "Turnboy"}: {c.name}
        </Body>
      ))}
    </View>
  );
}

function FloatCard() {
  const t = useTheme();
  const offline = useOffline();
  const balance = offline.balanceCents();
  if (balance === null) return null;
  return (
    <View style={{ padding: 16, borderRadius: 12, backgroundColor: t.surface, gap: 4 }}>
      <Body muted>Float balance</Body>
      <Text style={{ color: t.text, fontSize: 40, fontWeight: "800" }}>{formatKes(balance)}</Text>
    </View>
  );
}

function DriverHome() {
  const { me } = useAuth();
  return (
    <ScrollView
      contentContainerStyle={{ gap: 16, paddingVertical: 16 }}
      keyboardShouldPersistTaps="handled"
    >
      <Title>Hello, {me?.user.name.split(" ")[0]}</Title>
      <SyncBadge />
      <AttentionList />
      <MyVehicleCard />
      <FloatCard />
      <TripPanel />
    </ScrollView>
  );
}

function OwnerHome() {
  const { me } = useAuth();
  const t = useTheme();
  const [data, setData] = useState<Dashboard | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    api
      .dashboard()
      .then(setData)
      .catch(() => setFailed(true));
  }, []);

  const n = data?.numbers;
  return (
    <ScrollView contentContainerStyle={{ gap: 12, paddingVertical: 16 }}>
      <Title>{me?.business?.name}</Title>
      <Body>How is my business doing right now?</Body>
      {failed && (
        <Body muted>
          The dashboard needs an internet connection. Try again when you are online.
        </Body>
      )}
      {n && (
        <View style={{ padding: 14, borderRadius: 12, backgroundColor: t.surface, gap: 4 }}>
          <Body muted>Today</Body>
          {n.trips_active !== undefined && (
            <Body>
              {n.trips_active} trips running, {n.trips_completed_today ?? 0} completed
            </Body>
          )}
          {n.distance_today_km !== undefined && (
            <Body>{n.distance_today_km.toLocaleString()} km driven</Body>
          )}
          {n.fuel_today && <Body>Fuel {formatKes(n.fuel_today.amount_cents)}</Body>}
          {n.expenses_today_cents !== undefined && (
            <Body>Expenses {formatKes(n.expenses_today_cents)}</Body>
          )}
          {n.floats_sent_today_cents !== undefined && (
            <Body>Floats sent {formatKes(n.floats_sent_today_cents)}</Body>
          )}
        </View>
      )}
      {data && data.alerts.length === 0 && <Body>Nothing needs your attention right now.</Body>}
      {data?.alerts.slice(0, 12).map((a, i) => (
        <View
          key={`${a.kind}-${i}`}
          style={{
            padding: 12,
            borderRadius: 12,
            backgroundColor: t.surface,
            gap: 2,
            borderLeftWidth: 5,
            borderLeftColor: a.severity === "red" ? "#d92d20" : "#f79009",
          }}
        >
          <Body>{a.title}</Body>
          {a.detail ? <Body muted>{a.detail}</Body> : null}
        </View>
      ))}
    </ScrollView>
  );
}

export default function HomeScreen() {
  const { me, view } = useAuth();
  return (
    <Screen>
      {view === "driver" ? <DriverHome /> : <OwnerHome />}
      <Body muted>{me?.roles.map((r) => ROLE_LABELS[r]).join(", ")}</Body>
    </Screen>
  );
}
