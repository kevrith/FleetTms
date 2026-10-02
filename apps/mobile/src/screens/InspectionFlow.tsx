import { positionLabel } from "@fleettms/business-rules";
import type { ChecklistItem } from "@fleettms/types";
import { useState } from "react";
import { Text, View } from "react-native";
import { CaptureScreen } from "../capture";
import type { LocalPhoto } from "../offline/types";
import { useOffline } from "../offline/runtime";
import { Body, Button, ErrorText, errorMessage, Input, useTheme } from "../ui";

interface Answer {
  ok: boolean;
  note: string;
  photo: LocalPhoto | null;
}

/**
 * The daily pre-trip checklist, done entirely on the phone. Every item is answered; a fault needs a note and, where
 * set, a photo. The result is queued and sent when there is a network.
 */
export default function InspectionFlow({
  vehicleId,
  onDone,
  onCancel,
}: {
  vehicleId: string;
  onDone: (outcome: "passed" | "passed_with_defects" | "blocked") => void;
  onCancel: () => void;
}) {
  const t = useTheme();
  const offline = useOffline();
  const items = offline.state.cache.checklist;
  const [answers, setAnswers] = useState<Record<string, Answer>>({});
  const [photoFor, setPhotoFor] = useState<ChecklistItem | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const positions = offline.state.cache.tyrePositions;
  const [serials, setSerials] = useState<Record<string, string>>({});

  const answer = (id: string): Answer => answers[id] ?? { ok: true, note: "", photo: null };
  const set = (id: string, patch: Partial<Answer>) =>
    setAnswers((a) => ({ ...a, [id]: { ...answer(id), ...patch } }));

  if (items.length === 0) {
    return (
      <View style={{ gap: 12 }}>
        <Text style={{ color: t.text, fontSize: 22, fontWeight: "700" }}>Pre-trip inspection</Text>
        <Body muted>
          The checklist has not been downloaded yet. Connect to the internet once, then try again.
        </Body>
        <Button label="Back" kind="secondary" onPress={onCancel} />
      </View>
    );
  }

  if (photoFor) {
    return (
      <CaptureScreen
        kind="defect"
        title={`Photo of the fault: ${photoFor.label}`}
        hint="Show the problem clearly."
        onDone={(photo) => {
          set(photoFor.id, { photo });
          setPhotoFor(null);
        }}
        onCancel={() => setPhotoFor(null)}
      />
    );
  }

  const incomplete = items.some((i) => {
    const a = answer(i.id);
    return !a.ok && (!a.note.trim() || (i.photo_on_fault && !a.photo));
  });

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      onDone(
        await offline.submitInspection(
          vehicleId,
          items.map((i) => ({
            itemId: i.id,
            label: i.label,
            critical: i.critical,
            ...answer(i.id),
          })),
          positions.map((position) => ({ position, serial: serials[position] ?? "" })),
        ),
      );
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <View style={{ gap: 12 }}>
      <Text style={{ color: t.text, fontSize: 22, fontWeight: "700" }}>Pre-trip inspection</Text>
      <Body muted>Check each item. Tap "Fault" if something is wrong.</Body>
      {items.map((i) => {
        const a = answer(i.id);
        return (
          <View
            key={i.id}
            style={{ padding: 12, borderRadius: 12, backgroundColor: t.surface, gap: 8 }}
          >
            <Body>
              {i.label}
              {i.critical ? " (critical)" : ""}
            </Body>
            <View style={{ flexDirection: "row", gap: 8 }}>
              <View style={{ flex: 1 }}>
                <Button
                  label="OK"
                  kind={a.ok ? "primary" : "secondary"}
                  onPress={() => set(i.id, { ok: true })}
                />
              </View>
              <View style={{ flex: 1 }}>
                <Button
                  label="Fault"
                  kind={a.ok ? "secondary" : "danger"}
                  onPress={() => set(i.id, { ok: false })}
                />
              </View>
            </View>
            {!a.ok && (
              <>
                <Input
                  label="What is wrong?"
                  value={a.note}
                  onChangeText={(v) => set(i.id, { note: v })}
                />
                {i.photo_on_fault && (
                  <Button
                    label={a.photo ? "Photo taken. Retake" : "Take photo of the fault"}
                    kind="secondary"
                    onPress={() => setPhotoFor(i)}
                  />
                )}
              </>
            )}
          </View>
        );
      })}
      {positions.length > 0 && (
        <View style={{ padding: 12, borderRadius: 12, backgroundColor: t.surface, gap: 8 }}>
          <Body>Tyre serial numbers</Body>
          <Body muted>Read the number printed on each tyre and type it in.</Body>
          {positions.map((position) => (
            <Input
              key={position}
              label={positionLabel(position)}
              value={serials[position] ?? ""}
              autoCapitalize="characters"
              onChangeText={(v) => setSerials((s) => ({ ...s, [position]: v }))}
            />
          ))}
        </View>
      )}
      <ErrorText message={error} />
      <Button label="Submit inspection" onPress={submit} busy={busy} disabled={incomplete} />
      <Button label="Cancel" kind="secondary" onPress={onCancel} disabled={busy} />
    </View>
  );
}
