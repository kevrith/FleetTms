import { formatKes } from "@fleettms/business-rules";
import { ScrollView, Text, View } from "react-native";
import { useAuth } from "../auth";
import { Body, Screen, Title, useTheme } from "../ui";
import { useOffline } from "../offline/runtime";
import { HelpCard } from "./Help";
import OwnerHome from "./OwnerHome";
import { RepairCard } from "./Repairs";
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
      <HelpCard />
      <RepairCard />
      <AttentionList />
      <MyVehicleCard />
      <FloatCard />
      <TripPanel />
    </ScrollView>
  );
}

export default function HomeScreen() {
  const { view } = useAuth();
  return <Screen>{view === "driver" ? <DriverHome /> : <OwnerHome />}</Screen>;
}
