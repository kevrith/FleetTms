import type { PendingDocument } from "@fleettms/types";
import { useState } from "react";
import { ScrollView } from "react-native";
import { api } from "../api";
import { useAuth } from "../auth";
import { Body, Button, ErrorText, errorMessage, Screen, Title } from "../ui";

const TITLES: Record<string, string> = {
  terms: "Terms of Service",
  privacy: "Privacy Policy",
  dpa: "Data Processing Agreement",
  monitoring_notice: "How FleetTms tracks your work",
};

// Plain-language summary shown to drivers before they can use the app (masterplan Section 11.2).
const MONITORING_TEXT =
  "FleetTms records your phone's location (position, speed and direction) while a trip is running, your odometer photos, and the fuel and expenses you enter. " +
  "Tracking starts when you start a trip and stops when you end it, and a notification shows while it is on. It does not run outside work. " +
  "Your employer and supervisors can see it, and a client can follow only that delivery's progress on a link the office sends. " +
  "Location points are deleted after 12 months. You can ask your employer to see, correct or delete your data.";

export default function NoticesScreen({ docs }: { docs: PendingDocument[] }) {
  const { reload } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function accept() {
    setBusy(true);
    setError(null);
    try {
      for (const d of docs) await api.acceptDocument(d);
      await reload();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen>
      <ScrollView contentContainerStyle={{ gap: 16, flexGrow: 1, justifyContent: "center" }}>
        <Title>Please read and accept</Title>
        {docs.map((d) => (
          <Body key={d.document}>
            {TITLES[d.document] ?? d.document} (version {d.version})
            {d.document === "monitoring_notice" ? `\n\n${MONITORING_TEXT}` : ""}
          </Body>
        ))}
        <Body muted>These documents are drafts pending legal review.</Body>
        <ErrorText message={error} />
        <Button label="I have read and accept" onPress={accept} busy={busy} />
      </ScrollView>
    </Screen>
  );
}
