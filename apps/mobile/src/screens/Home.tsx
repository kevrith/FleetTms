import { formatKes, ROLE_LABELS } from "@fleettms/business-rules";
import { ScrollView, Text, View } from "react-native";
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
  const { float } = useOffline().state.cache;
  if (!float) return null;
  return (
    <View style={{ padding: 16, borderRadius: 12, backgroundColor: t.surface, gap: 4 }}>
      <Body muted>Float balance</Body>
      <Text style={{ color: t.text, fontSize: 24, fontWeight: "600" }}>
        {formatKes(float.balance_cents)}
      </Text>
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
  return (
    <>
      <Title>{me?.business?.name}</Title>
      <Body>How is my business doing right now?</Body>
      <Body muted>
        Today's numbers, alerts and the live map appear here as your fleet data comes in.
      </Body>
    </>
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
