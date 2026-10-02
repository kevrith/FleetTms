import { ROLE_LABELS } from "@fleettms/business-rules";
import { useState } from "react";
import { Alert, ScrollView } from "react-native";
import { api } from "../api";
import { useAuth } from "../auth";
import { clearQuick } from "../quick";
import { useOffline } from "../offline/runtime";
import { QuickSignInCard } from "./QuickSignIn";
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
  const offline = useOffline();
  const [error, setError] = useState<string | null>(null);

  /** Signing out wipes the phone's saved work, so send what is waiting first and warn if some cannot go. */
  async function confirmLeave(): Promise<boolean> {
    await offline.syncNow();
    const left = offline.unsent();
    if (left === 0) return true;
    return new Promise((resolve) =>
      Alert.alert(
        "Some records have not been sent",
        `${left} record${left === 1 ? " has" : "s have"} not reached the office. If you sign out now, ${left === 1 ? "it" : "they"} will be deleted from this phone.`,
        [
          { text: "Stay signed in", style: "cancel", onPress: () => resolve(false) },
          { text: "Delete and sign out", style: "destructive", onPress: () => resolve(true) },
        ],
      ),
    );
  }

  async function leave() {
    if (!(await confirmLeave())) return;
    await signOut();
    await offline.wipe();
  }

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
    if (!(await confirmLeave())) return;
    try {
      await api.logoutAll();
    } catch (e) {
      setError(errorMessage(e));
      return;
    }
    await clearQuick(); // a lost phone must not keep a way back in
    await reload();
    await offline.wipe();
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

        <QuickSignInCard />
        <Button kind="secondary" label="Sign out" onPress={leave} />
        <Button kind="danger" label="Sign out of all devices" onPress={signOutEverywhere} />
      </ScrollView>
    </Screen>
  );
}
