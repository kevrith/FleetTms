import type { ChecklistItem, Inspection, InspectionAnswer } from "@fleettms/types";
import { useEffect, useState } from "react";
import { Text, View } from "react-native";
import { api } from "../api";
import { CaptureScreen } from "../capture";
import { Body, Button, ErrorText, errorMessage, Input, useTheme } from "../ui";

interface Answer {
  ok: boolean;
  note: string;
  photoId: string | null;
}

/** The daily pre-trip checklist. Every item is answered; a fault needs a note and, where set, a photo. */
export default function InspectionFlow({
  vehicleId,
  onDone,
  onCancel,
}: {
  vehicleId: string;
  onDone: (result: Inspection) => void;
  onCancel: () => void;
}) {
  const t = useTheme();
  const [items, setItems] = useState<ChecklistItem[] | null>(null);
  const [answers, setAnswers] = useState<Record<string, Answer>>({});
  const [photoFor, setPhotoFor] = useState<ChecklistItem | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .checklist()
      .then((list) => {
        setItems(list);
        setAnswers(
          Object.fromEntries(list.map((i) => [i.id, { ok: true, note: "", photoId: null }])),
        );
      })
      .catch((e) => setError(errorMessage(e)));
  }, []);

  const set = (id: string, patch: Partial<Answer>) =>
    setAnswers((a) => ({ ...a, [id]: { ...a[id]!, ...patch } }));

  if (photoFor) {
    return (
      <CaptureScreen
        kind="defect"
        title={`Photo of the fault: ${photoFor.label}`}
        hint="Show the problem clearly."
        onDone={(photo) => {
          set(photoFor.id, { photoId: photo.id });
          setPhotoFor(null);
        }}
        onCancel={() => setPhotoFor(null)}
      />
    );
  }

  const incomplete = (items ?? []).some((i) => {
    const a = answers[i.id];
    return a && !a.ok && (!a.note.trim() || (i.photo_on_fault && !a.photoId));
  });

  async function submit() {
    setBusy(true);
    setError(null);
    const results: InspectionAnswer[] = (items ?? []).map((i) => {
      const a = answers[i.id]!;
      return {
        item_id: i.id,
        ok: a.ok,
        note: a.ok ? null : a.note.trim(),
        photo_id: a.ok ? null : a.photoId,
      };
    });
    try {
      onDone(await api.submitInspection(vehicleId, results));
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
      {items === null && !error && <Body muted>Loading the checklist...</Body>}
      {items?.map((i) => {
        const a = answers[i.id];
        if (!a) return null;
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
                    label={a.photoId ? "Photo taken. Retake" : "Take photo of the fault"}
                    kind="secondary"
                    onPress={() => setPhotoFor(i)}
                  />
                )}
              </>
            )}
          </View>
        );
      })}
      <ErrorText message={error} />
      <Button
        label="Submit inspection"
        onPress={submit}
        busy={busy}
        disabled={!items || incomplete}
      />
      <Button label="Cancel" kind="secondary" onPress={onCancel} disabled={busy} />
    </View>
  );
}
