import type { IncidentType } from "@fleettms/types";
import * as Location from "expo-location";
import { useEffect, useRef, useState } from "react";
import { Alert, Text, View } from "react-native";
import { api } from "../api";
import { CaptureScreen } from "../capture";
import { useOffline } from "../offline/runtime";
import type { LocalPhoto } from "../offline/types";
import { Body, Button, ErrorText, errorMessage, Input, useTheme } from "../ui";

type Position = { lat: number; lng: number; accuracy_m: number | null };

/** Where the phone is, as fast as possible: the last known fix at once, a fresh one if it arrives within a few seconds. */
async function quickPosition(): Promise<Position | null> {
  try {
    const perm = await Location.getForegroundPermissionsAsync();
    if (!perm.granted && !(await Location.requestForegroundPermissionsAsync()).granted) return null;
    const fresh = await Promise.race([
      Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced }),
      new Promise<null>((resolve) => setTimeout(() => resolve(null), 4000)),
    ]);
    const fix = fresh ?? (await Location.getLastKnownPositionAsync());
    return fix
      ? {
          lat: fix.coords.latitude,
          lng: fix.coords.longitude,
          accuracy_m: fix.coords.accuracy ?? null,
        }
      : null;
  } catch {
    return null;
  }
}

const TYPES: { type: IncidentType; label: string }[] = [
  { type: "breakdown", label: "Breakdown" },
  { type: "accident", label: "Accident" },
  { type: "police_stop", label: "Police stop" },
  { type: "traffic_fine", label: "Traffic fine" },
  { type: "county_cess", label: "County cess" },
  { type: "cargo_theft", label: "Cargo theft" },
];

/** One-tap report from the road: what happened, an optional photo, and where. Works with no network. */
function ReportProblem({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const t = useTheme();
  const offline = useOffline();
  const [type, setType] = useState<IncidentType | null>(null);
  const [description, setDescription] = useState("");
  const [photo, setPhoto] = useState<LocalPhoto | null>(null);
  const [taking, setTaking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (taking) {
    return (
      <CaptureScreen
        kind="incident"
        title="Photo"
        hint="Show what happened: the vehicle, the damage, the ticket."
        onDone={(p) => {
          setPhoto(p);
          setTaking(false);
        }}
        onCancel={() => setTaking(false)}
      />
    );
  }

  async function send() {
    if (!type) return;
    setBusy(true);
    setError(null);
    try {
      const where = await quickPosition();
      await offline.reportIncident({
        type,
        description,
        photo,
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
    <View style={{ gap: 12 }}>
      <Text style={{ color: t.text, fontSize: 22, fontWeight: "700" }}>Report a problem</Text>
      <Body muted>What happened?</Body>
      {TYPES.map((x) => (
        <Button
          key={x.type}
          label={x.label}
          kind={type === x.type ? "primary" : "secondary"}
          onPress={() => setType(x.type)}
        />
      ))}
      <Input label="Tell us more (optional)" value={description} onChangeText={setDescription} />
      <Button
        label={photo ? "Photo taken. Retake" : "Add a photo"}
        kind="secondary"
        onPress={() => setTaking(true)}
      />
      <ErrorText message={error} />
      <Button label="Send report" onPress={send} busy={busy} disabled={!type} />
      <Button label="Cancel" kind="secondary" onPress={onCancel} disabled={busy} />
    </View>
  );
}

/**
 * SOS and Report a problem. The SOS button asks once, then sends your location to the owner and supervisors; with no
 * signal it waits on the phone and goes the moment there is one. While an alert is open the phone keeps sending where it is.
 */
export function HelpCard() {
  const t = useTheme();
  const offline = useOffline();
  const [reporting, setReporting] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const sos = offline.state.cache.sos;
  const waiting = offline.state.queue.some((i) => i.type === "sos.send" && i.status === "queued");
  const open = Boolean(sos) || waiting;
  const sosId = useRef<string | null>(null);
  sosId.current = sos?.id ?? null;

  // While the alert is open, keep the office posted on where the vehicle is.
  useEffect(() => {
    if (!open) return;
    const timer = setInterval(async () => {
      if (!sosId.current) return;
      const where = await quickPosition();
      if (where) await api.sosLocation(sosId.current, where).catch(() => undefined);
    }, 15_000);
    return () => clearInterval(timer);
  }, [open]);

  function confirmSos() {
    Alert.alert(
      "Send an SOS?",
      "This tells your owner and supervisors you need help, with your location, right now.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Send SOS",
          style: "destructive",
          onPress: async () => {
            setError(null);
            try {
              await offline.sendSos(await quickPosition());
              setSaved("SOS raised.");
            } catch (e) {
              setError(errorMessage(e));
            }
          },
        },
      ],
    );
  }

  if (reporting) {
    return (
      <ReportProblem
        onDone={() => {
          setReporting(false);
          setSaved("Report saved. It goes to the office as soon as there is a connection.");
        }}
        onCancel={() => setReporting(false)}
      />
    );
  }

  return (
    <View style={{ padding: 16, borderRadius: 12, backgroundColor: t.surface, gap: 10 }}>
      <Button label="SOS: I need help" kind="danger" onPress={confirmSos} />
      {open && (
        <Body>
          {sos?.acknowledged
            ? "Someone has seen your SOS and is on it."
            : waiting
              ? "SOS saved on this phone. It will be sent the moment there is a signal."
              : "SOS sent. Waiting for someone to answer. Stay where you are if it is safe."}
        </Body>
      )}
      <Button label="Report a problem" kind="secondary" onPress={() => setReporting(true)} />
      {saved && !open && <Body muted>{saved}</Body>}
      <ErrorText message={error} />
    </View>
  );
}
