import * as Location from "expo-location";
import { useState } from "react";
import { ScrollView, Text, View } from "react-native";
import { api } from "../api";
import { CaptureScreen } from "../capture";
import { useOffline } from "../offline/runtime";
import type { LocalPhoto } from "../offline/types";
import { Body, Button, ErrorText, errorMessage, Input, useTheme } from "../ui";
import { SignaturePad, type Strokes } from "./SignaturePad";

async function here(): Promise<{ lat: number; lng: number } | null> {
  try {
    const perm = await Location.getForegroundPermissionsAsync();
    if (!perm.granted) return null;
    const fix = await Promise.race([
      Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced }),
      new Promise<null>((resolve) => setTimeout(() => resolve(null), 4000)),
    ]);
    const use = fix ?? (await Location.getLastKnownPositionAsync());
    return use ? { lat: use.coords.latitude, lng: use.coords.longitude } : null;
  } catch {
    return null;
  }
}

type Taking = "cargo" | "note" | "damage" | null;

/**
 * Proof of delivery: photos of the offloaded cargo and the signed delivery note, who received it, and either their
 * signature or the code texted to the client's phone. Shortages and damage are recorded here too. Everything is saved on
 * the phone and sent when there is a network; only the code needs a network, to be texted.
 */
export default function Delivery({
  onDone,
  onCancel,
}: {
  onDone: () => void;
  onCancel: () => void;
}) {
  const t = useTheme();
  const offline = useOffline();
  const trip = offline.state.cache.trip;
  const [taking, setTaking] = useState<Taking>(null);
  const [cargo, setCargo] = useState<LocalPhoto | null>(null);
  const [note, setNote] = useState<LocalPhoto | null>(null);
  const [damagePhoto, setDamagePhoto] = useState<LocalPhoto | null>(null);
  const [name, setName] = useState("");
  const [method, setMethod] = useState<"signature" | "code">("signature");
  const [code, setCode] = useState("");
  const [codeSent, setCodeSent] = useState<string | null>(null);
  const [signature, setSignature] = useState<Strokes | null>(null);
  const [shortageQty, setShortageQty] = useState("");
  const [shortageUnit, setShortageUnit] = useState("");
  const [damage, setDamage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (taking) {
    const titles = {
      cargo: ["Photo of the cargo delivered", "Show the cargo offloaded at the client."],
      note: [
        "Photo of the signed delivery note",
        "The whole note, flat and in focus, with the signature on it.",
      ],
      damage: ["Photo of the damage", "Show what is damaged."],
    } as const;
    return (
      <CaptureScreen
        kind={taking === "cargo" ? "pod_cargo" : taking === "note" ? "delivery_note" : "damage"}
        title={titles[taking][0]}
        hint={titles[taking][1]}
        onCancel={() => setTaking(null)}
        onDone={(photo) => {
          if (taking === "cargo") setCargo(photo);
          else if (taking === "note") setNote(photo);
          else setDamagePhoto(photo);
          setTaking(null);
        }}
      />
    );
  }

  async function sendCode() {
    if (!trip) return;
    setError(null);
    try {
      const sent = await api.requestPodCode(trip.id);
      setCodeSent(`A code was texted to the client's phone ending ${sent.sent_to_last4}.`);
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  const ready =
    name.trim().length >= 2 &&
    cargo !== null &&
    note !== null &&
    (method === "signature" ? signature !== null : /^\d{6}$/.test(code.trim())) &&
    (!damage.trim() || damagePhoto !== null);

  async function confirm() {
    if (!cargo || !note) return;
    setBusy(true);
    setError(null);
    try {
      const where = await here();
      await offline.deliver({
        recipientName: name,
        method,
        code,
        signature,
        cargo,
        note,
        shortageQty,
        shortageUnit,
        damageNotes: damage,
        damagePhoto,
        lat: where?.lat ?? null,
        lng: where?.lng ?? null,
      });
      onDone();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <ScrollView
      keyboardShouldPersistTaps="handled"
      contentContainerStyle={{ gap: 12 }}
      scrollEnabled
    >
      <Text style={{ color: t.text, fontSize: 22, fontWeight: "700" }}>Proof of delivery</Text>
      {trip?.job && (
        <Body muted>
          Job {trip.job.number} for {trip.job.client_name}
        </Body>
      )}
      <Button
        label={cargo ? "Cargo photo taken. Retake" : "Photo of the cargo delivered"}
        kind="secondary"
        onPress={() => setTaking("cargo")}
      />
      <Button
        label={note ? "Delivery note photo taken. Retake" : "Photo of the signed delivery note"}
        kind="secondary"
        onPress={() => setTaking("note")}
      />
      <Input label="Name of the person who received it" value={name} onChangeText={setName} />
      <Body muted>How does the recipient confirm?</Body>
      <View style={{ flexDirection: "row", gap: 8 }}>
        <View style={{ flex: 1 }}>
          <Button
            label="Signature"
            kind={method === "signature" ? "primary" : "secondary"}
            onPress={() => setMethod("signature")}
          />
        </View>
        <View style={{ flex: 1 }}>
          <Button
            label="Code by SMS"
            kind={method === "code" ? "primary" : "secondary"}
            onPress={() => setMethod("code")}
          />
        </View>
      </View>
      {method === "signature" ? (
        <>
          <Body muted>Ask the recipient to sign in the box.</Body>
          <SignaturePad onChange={setSignature} />
        </>
      ) : (
        <>
          <Body muted>
            The code goes to the client's phone and needs a connection. If you have no signal, use
            the signature.
          </Body>
          <Button
            label={codeSent ? "Send the code again" : "Text the code to the client"}
            kind="secondary"
            onPress={sendCode}
          />
          {codeSent ? <Body>{codeSent}</Body> : null}
          <Input
            label="The 6-digit code the recipient gives you"
            value={code}
            onChangeText={setCode}
            keyboardType="number-pad"
            maxLength={6}
          />
        </>
      )}
      <Body muted>Anything short or damaged? (optional)</Body>
      <Input
        label="Shortage quantity"
        value={shortageQty}
        onChangeText={setShortageQty}
        keyboardType="decimal-pad"
      />
      <Input
        label="Shortage unit (bags, tonnes, pieces)"
        value={shortageUnit}
        onChangeText={setShortageUnit}
      />
      <Input label="What is damaged?" value={damage} onChangeText={setDamage} />
      {damage.trim() ? (
        <Button
          label={damagePhoto ? "Damage photo taken. Retake" : "Photo of the damage"}
          kind="secondary"
          onPress={() => setTaking("damage")}
        />
      ) : null}
      <ErrorText message={error} />
      <Button label="Confirm delivery" onPress={confirm} busy={busy} disabled={!ready} />
      <Button label="Cancel" kind="secondary" onPress={onCancel} disabled={busy} />
    </ScrollView>
  );
}
