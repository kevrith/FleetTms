import { ROLE_LABELS } from "@fleettms/business-rules";
import { Text, View } from "react-native";
import { useAuth } from "../auth";
import { Body, Button, Screen, Title, useTheme } from "../ui";

function DriverHome() {
  const { me } = useAuth();
  const t = useTheme();
  return (
    <>
      <Title>Hello, {me?.user.name.split(" ")[0]}</Title>
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
