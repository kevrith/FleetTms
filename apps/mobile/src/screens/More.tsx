import { ROLE_LABELS } from "@fleettms/business-rules";
import { useState } from "react";
import { ScrollView } from "react-native";
import { api } from "../api";
import { useAuth } from "../auth";
import { Body, Button, ErrorText, errorMessage, Screen, Title } from "../ui";

export function Placeholder({ title }: { title: string }) {
  return (
    <Screen>
      <Title>{title}</Title>
      <Body muted>Coming soon</Body>
    </Screen>
  );
}

export default function MoreScreen() {
  const { me, views, view, setView, reload, signOut } = useAuth();
  const [error, setError] = useState<string | null>(null);

  async function switchCompany(id: string) {
    setError(null);
    try {
      await api.switchCompany(id);
      await reload();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  async function signOutEverywhere() {
    try {
      await api.logoutAll();
    } catch (e) {
      setError(errorMessage(e));
      return;
    }
    await reload();
  }

  return (
    <Screen>
      <ScrollView contentContainerStyle={{ gap: 12, flexGrow: 1, justifyContent: "center" }}>
        <Title>{me?.user.name}</Title>
        <Body muted>{me?.roles.map((r) => ROLE_LABELS[r]).join(", ")}</Body>
        <ErrorText message={error} />

        {views.length > 1 && (
          <>
            <Body>You are in the {view === "owner" ? "Owner" : "Driver"} view.</Body>
            <Button
              kind="secondary"
              label={view === "owner" ? "Switch to Driver view" : "Switch to Owner view"}
              onPress={() => setView(view === "owner" ? "driver" : "owner")}
            />
          </>
        )}

        {(me?.companies.length ?? 0) > 1 && (
          <>
            <Body>Company: {me?.business?.name}</Body>
            {me?.companies
              .filter((c) => c.business_id !== me.business?.id)
              .map((c) => (
                <Button
                  key={c.business_id}
                  kind="secondary"
                  label={`Switch to ${c.name}`}
                  onPress={() => switchCompany(c.business_id)}
                />
              ))}
          </>
        )}

        <Button kind="secondary" label="Sign out" onPress={signOut} />
        <Button kind="danger" label="Sign out of all devices" onPress={signOutEverywhere} />
      </ScrollView>
    </Screen>
  );
}
