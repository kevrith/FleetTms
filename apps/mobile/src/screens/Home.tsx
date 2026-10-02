import { ROLE_LABELS } from "@fleettms/business-rules";
import type { MyVehicle } from "@fleettms/types";
import { useEffect, useState } from "react";
import { Text, View } from "react-native";
import { api } from "../api";
import { useAuth } from "../auth";
import { Body, Button, Screen, Title, useTheme } from "../ui";

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
  const t = useTheme();
  return (
    <>
      <Title>Hello, {me?.user.name.split(" ")[0]}</Title>
      <MyVehicleCard />
      <View style={{ padding: 16, borderRadius: 12, backgroundColor: t.surface, gap: 4 }}>
        <Body muted>Today's trip</Body>
        <Text style={{ color: t.text, fontSize: 20 }}>No trip assigned yet</Text>
      </View>
      <Button label="Start trip" onPress={() => {}} disabled />
      <Button label="Add expense" kind="secondary" onPress={() => {}} disabled />
      <Body muted>Trips, expenses and float balance arrive in the next updates.</Body>
    </>
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
