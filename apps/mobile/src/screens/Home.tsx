import { ROLE_LABELS } from "@fleettms/business-rules";
import type { MyVehicle } from "@fleettms/types";
import { useEffect, useState } from "react";
import { ScrollView, Text, View } from "react-native";
import { api } from "../api";
import { useAuth } from "../auth";
import { Body, Screen, Title, useTheme } from "../ui";
import TripPanel from "./TripPanel";

function MyVehicleCard() {
  const t = useTheme();
  const [mine, setMine] = useState<MyVehicle | null | undefined>(undefined);

  useEffect(() => {
    api
      .myVehicle()
      .then(setMine)
      .catch(() => setMine(null));
  }, []);

  if (mine === undefined) return null;
  return (
    <View style={{ padding: 16, borderRadius: 12, backgroundColor: t.surface, gap: 4 }}>
      <Body muted>My vehicle</Body>
      {mine === null ? (
        <Text style={{ color: t.text, fontSize: 20 }}>No vehicle assigned yet</Text>
      ) : (
        <>
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
        </>
      )}
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
      <MyVehicleCard />
      <TripPanel />
      <Body muted>Expenses and float balance arrive in the next updates.</Body>
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
