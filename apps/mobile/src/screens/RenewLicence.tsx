import * as DocumentPicker from "expo-document-picker";
import { useState } from "react";
import { ScrollView, Text, View } from "react-native";
import { CaptureScreen } from "../capture";
import type { LocalPhoto } from "../offline/types";
import { useOffline } from "../offline/runtime";
import { Body, Button, ErrorText, errorMessage, Input, useTheme } from "../ui";

const DATE = /^\d{4}-\d{2}-\d{2}$/;
const PROOFS = [
  {
    value: "receipt",
    label: "Payment receipt",
    help: "The 3-year renewal: NTSA renews it when you pay, and the card comes later.",
  },
  {
    value: "digital_licence",
    label: "Digital licence",
    help: "The 1-year renewal: the licence NTSA sends you.",
  },
] as const;

/**
 * The driver's own licence renewal: a photo of the receipt or of the digital licence on a screen, the new expiry date, and a reference. It goes to
 * the owner or a manager, who checks the proof; until they approve it nothing changes, so a date typed here cannot unblock a trip by itself.
 */
const MAX_BYTES = 8 * 1024 * 1024; // the server's limit for one file

export default function RenewLicence({
  onDone,
  onCancel,
}: {
  onDone: () => void;
  onCancel: () => void;
}) {
  const t = useTheme();
  const offline = useOffline();
  const [proof, setProof] = useState<LocalPhoto | null>(null);
  const [capturing, setCapturing] = useState(true);
  const [kind, setKind] = useState<(typeof PROOFS)[number]["value"]>("receipt");
  const [date, setDate] = useState("");
  const [reference, setReference] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (capturing && !proof) {
    return (
      <View style={{ gap: 12 }}>
        <Button
          label="Choose a PDF or picture from my phone"
          kind="secondary"
          onPress={() => void pickFile()}
        />
        <ErrorText message={error} />
        <CaptureScreen
          kind="document"
          title="Photo of the proof"
          hint="The payment receipt, or the digital licence on a screen. The whole page, in focus."
          onCancel={onCancel}
          onDone={(photo) => {
            setProof(photo);
            setCapturing(false);
          }}
        />
      </View>
    );
  }
  if (sent) {
    return (
      <View style={{ gap: 12 }}>
        <Text style={{ color: t.text, fontSize: 22, fontWeight: "700" }}>Sent</Text>
        <Body>
          Your employer will check the proof and approve it. You will be told. Until then the trip
          stays stopped.
        </Body>
        <Button label="Done" onPress={onDone} />
      </View>
    );
  }
  // The digital licence NTSA sends arrives as a PDF in the phone's email or WhatsApp. A renewal paper is read for what it says and is not
  // evidence of an event, so (unlike the odometer or cargo photos) it may come from the phone's files instead of the live camera.
  async function pickFile() {
    setError(null);
    try {
      const result = await DocumentPicker.getDocumentAsync({
        type: ["application/pdf", "image/jpeg", "image/png", "image/webp"],
        copyToCacheDirectory: true,
        multiple: false,
      });
      const file = result.canceled ? null : result.assets[0];
      if (!file) return;
      if (file.size != null && file.size > MAX_BYTES) {
        setError("That file is too large. Choose one under 8 MB.");
        return;
      }
      setProof(
        await offline.capturePhoto({
          kind: "document",
          uri: file.uri,
          capturedAt: new Date().toISOString(),
          lat: null,
          lng: null,
        }),
      );
      setCapturing(false);
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  const valid = DATE.test(date) && !Number.isNaN(Date.parse(date)) && proof !== null;

  async function send() {
    if (!proof) return;
    setBusy(true);
    setError(null);
    try {
      await offline.submitLicenceRenewal({ proof, proofKind: kind, newExpiresOn: date, reference });
      setSent(true);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ gap: 12 }}>
      <Text style={{ color: t.text, fontSize: 22, fontWeight: "700" }}>Licence renewal</Text>
      <Body muted>Photo taken. What does it show?</Body>
      {PROOFS.map((p) => (
        <Button
          key={p.value}
          label={p.label}
          kind={kind === p.value ? "primary" : "secondary"}
          onPress={() => setKind(p.value)}
        />
      ))}
      <Body muted>{PROOFS.find((p) => p.value === kind)?.help}</Body>
      <Input
        label="New expiry date (YYYY-MM-DD)"
        value={date}
        onChangeText={setDate}
        placeholder="2029-10-15"
        keyboardType="numbers-and-punctuation"
      />
      <Input
        label="Receipt number (optional)"
        value={reference}
        onChangeText={setReference}
        autoCapitalize="characters"
      />
      <ErrorText message={error} />
      <Button label="Send for approval" onPress={() => void send()} busy={busy} disabled={!valid} />
      <Button
        label="Take the photo again"
        kind="secondary"
        onPress={() => {
          setProof(null);
          setCapturing(true);
        }}
      />
      <Button label="Cancel" kind="secondary" onPress={onCancel} />
    </ScrollView>
  );
}
