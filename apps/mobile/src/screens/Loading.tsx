import { overloadKg } from "@fleettms/business-rules";
import { useState } from "react";
import { Text, View } from "react-native";
import { CaptureScreen } from "../capture";
import { useOffline } from "../offline/runtime";
import type { LocalPhoto } from "../offline/types";
import { Body, Button, ErrorText, errorMessage, Input, useTheme } from "../ui";

/**
 * Loads and weighs the cargo: a photo of the cargo and, from the weighbridge ticket, its photo and net weight. Done before
 * the lorry leaves where possible; an overload is shown at once, before departure. A per-tonne job needs the ticket.
 */
export default function Loading({
  onDone,
  onCancel,
}: {
  onDone: () => void;
  onCancel: () => void;
}) {
  const t = useTheme();
  const offline = useOffline();
  const { trip, vehicle } = offline.state.cache;
  const needsTicket = trip?.job?.billing_method === "per_tonne";
  const [taking, setTaking] = useState<"cargo" | "ticket" | null>(null);
  const [cargo, setCargo] = useState<LocalPhoto | null>(null);
  const [ticket, setTicket] = useState<LocalPhoto | null>(null);
  const [kg, setKg] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (taking) {
    return (
      <CaptureScreen
        kind={taking === "cargo" ? "cargo" : "weighbridge"}
        title={taking === "cargo" ? "Photo of the cargo" : "Photo of the weighbridge ticket"}
        hint={
          taking === "cargo"
            ? "Show the load on the vehicle."
            : "The whole ticket, flat and in focus."
        }
        onCancel={() => setTaking(null)}
        onDone={(photo) => {
          if (taking === "cargo") setCargo(photo);
          else setTicket(photo);
          setTaking(null);
        }}
      />
    );
  }

  const weight = Number(kg.replace(/,/g, ""));
  const v = vehicle?.vehicle;
  const over =
    weight > 0
      ? overloadKg({
          cargo_kg: weight,
          tare_kg: v?.tare_kg ?? null,
          gvw_limit_kg: v?.gvw_limit_kg ?? null,
          capacity_tonnes: v?.capacity_tonnes ? Number(v.capacity_tonnes) : null,
        })
      : null;
  const weighed = ticket !== null && weight > 0;
  const ready = cargo !== null && (needsTicket ? weighed : ticket === null || weight > 0);

  async function save() {
    if (!cargo) return;
    setBusy(true);
    setError(null);
    try {
      await offline.recordLoading(
        cargo,
        ticket && weight > 0 ? { weightKg: Math.round(weight), ticket } : undefined,
      );
      onDone();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <View style={{ gap: 12 }}>
      <Text style={{ color: t.text, fontSize: 22, fontWeight: "700" }}>Load and weigh</Text>
      {needsTicket && (
        <Body muted>This job is billed per tonne, so the weighbridge ticket is needed.</Body>
      )}
      <Button
        label={cargo ? "Cargo photo taken. Retake" : "Photo of the cargo"}
        kind="secondary"
        onPress={() => setTaking("cargo")}
      />
      <Button
        label={ticket ? "Weighbridge ticket taken. Retake" : "Photo of the weighbridge ticket"}
        kind="secondary"
        onPress={() => setTaking("ticket")}
      />
      <Input
        label="Net weight on the ticket (kg)"
        value={kg}
        onChangeText={setKg}
        keyboardType="number-pad"
      />
      {over !== null && over > 0 && (
        <Text style={{ color: "#d92d20", fontSize: 18, fontWeight: "700" }}>
          OVERLOADED by {over.toLocaleString()} kg. Offload the excess before you leave.
        </Text>
      )}
      {over === 0 && <Body>Within the legal limit.</Body>}
      <ErrorText message={error} />
      <Button label="Save" onPress={save} busy={busy} disabled={!ready} />
      <Button label="Cancel" kind="secondary" onPress={onCancel} disabled={busy} />
    </View>
  );
}
