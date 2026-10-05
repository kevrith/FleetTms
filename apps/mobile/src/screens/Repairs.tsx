import { positionLabel } from "@fleettms/business-rules";
import type { RepairKind, RepairRequest } from "@fleettms/types";
import { useCallback, useEffect, useState } from "react";
import { Text, View } from "react-native";
import { api } from "../api";
import { CaptureScreen } from "../capture";
import { useOffline } from "../offline/runtime";
import type { LocalPhoto } from "../offline/types";
import { Body, Button, ErrorText, errorMessage, Input, useTheme } from "../ui";

const KINDS: { kind: RepairKind; label: string }[] = [
  { kind: "tyre", label: "Tyre" },
  { kind: "engine", label: "Engine" },
  { kind: "brakes", label: "Brakes" },
  { kind: "electrical", label: "Electrical" },
  { kind: "body", label: "Body or cab" },
  { kind: "other", label: "Something else" },
];
const STATUS = {
  open: "Sent. Waiting for the workshop",
  in_progress: "The workshop is on it",
  waiting_parts: "Waiting for parts",
  done: "Done",
  cancelled: "Cancelled",
} as const;

/** Ask the workshop to see to the vehicle, and see how it is getting on. Works with no signal: the request waits on the phone. */
export function RepairCard() {
  const t = useTheme();
  const offline = useOffline();
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<RepairKind | null>(null);
  const [position, setPosition] = useState<string | null>(null);
  const [canDrive, setCanDrive] = useState(true);
  const [description, setDescription] = useState("");
  const [photo, setPhoto] = useState<LocalPhoto | null>(null);
  const [taking, setTaking] = useState(false);
  const [rows, setRows] = useState<RepairRequest[]>([]);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const positions = offline.state.cache.tyrePositions;
  const waiting = offline.state.queue.filter((i) => i.type === "repair.request" && i.status === "queued").length;

  const load = useCallback(async () => {
    try {
      setRows(await api.myRepairRequests());
    } catch {
      /* offline: the list comes back next time */
    }
  }, []);
  // Reloads when a waiting request has gone through.
  useEffect(() => {
    void load();
  }, [load, waiting]);

  function close() {
    setOpen(false);
    setKind(null);
    setPosition(null);
    setCanDrive(true);
    setDescription("");
    setPhoto(null);
    setTaking(false);
  }

  async function send() {
    if (!kind) return;
    setBusy(true);
    setError(null);
    try {
      await offline.requestRepair({ kind, position, canDrive, description, photo });
      close();
      setSaved(true);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  if (taking) {
    return (
      <CaptureScreen
        kind="repair"
        title="Photo of the problem"
        hint="Show the part that needs seeing to, close up and in focus."
        onDone={(p) => {
          setPhoto(p);
          setTaking(false);
        }}
        onCancel={() => setTaking(false)}
      />
    );
  }

  const recent = rows.filter((r) => r.status !== "done" && r.status !== "cancelled").slice(0, 3);
  return (
    <View style={{ padding: 16, borderRadius: 12, backgroundColor: t.surface, gap: 10 }}>
      {!open ? (
        <>
          <Button label="Request a repair" kind="secondary" onPress={() => setOpen(true)} />
          {waiting > 0 && (
            <Body muted>
              {waiting} request{waiting === 1 ? "" : "s"} saved on this phone, sent when there is a
              signal.
            </Body>
          )}
          {saved && waiting === 0 && <Body muted>Request sent to the workshop.</Body>}
          {recent.map((r) => (
            <View key={r.id}>
              <Body>{r.title}</Body>
              <Body muted>{STATUS[r.status]}</Body>
            </View>
          ))}
        </>
      ) : (
        <>
          <Text style={{ color: t.text, fontSize: 22, fontWeight: "700" }}>Request a repair</Text>
          <Body muted>What needs seeing to?</Body>
          {KINDS.map((k) => (
            <Button
              key={k.kind}
              label={k.label}
              kind={kind === k.kind ? "primary" : "secondary"}
              onPress={() => {
                setKind(k.kind);
                setPosition(null);
              }}
            />
          ))}
          {kind === "tyre" && positions.length > 0 && (
            <>
              <Body muted>Which tyre?</Body>
              {positions.map((p) => (
                <Button
                  key={p}
                  label={positionLabel(p)}
                  kind={position === p ? "primary" : "secondary"}
                  onPress={() => setPosition(p)}
                />
              ))}
            </>
          )}
          <Body muted>Can the vehicle keep going?</Body>
          <Button
            label="Yes, I can keep driving"
            kind={canDrive ? "primary" : "secondary"}
            onPress={() => setCanDrive(true)}
          />
          <Button
            label="No, do not drive it"
            kind={canDrive ? "secondary" : "danger"}
            onPress={() => setCanDrive(false)}
          />
          <Input
            label="What is wrong? (optional)"
            value={description}
            onChangeText={setDescription}
            multiline
            maxLength={1000}
          />
          <Button
            label={photo ? "Photo taken. Retake" : "Add a photo"}
            kind="secondary"
            onPress={() => setTaking(true)}
          />
          <ErrorText message={error} />
          <Button label="Send request" onPress={send} busy={busy} disabled={!kind} />
          <Button label="Cancel" kind="secondary" onPress={close} disabled={busy} />
        </>
      )}
    </View>
  );
}
