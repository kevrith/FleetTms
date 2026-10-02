import { formatKes, kesToCents } from "@fleettms/business-rules";
import { useState } from "react";
import { ScrollView, Text, View } from "react-native";
import { CaptureScreen } from "../capture";
import type { LocalPhoto } from "../offline/types";
import { useOffline } from "../offline/runtime";
import { Body, Button, ErrorText, errorMessage, Input, Title, useTheme } from "../ui";
import { SyncBadge } from "./SyncStatus";

/** Float balance and fuel entries. Fuel is saved on the phone first, so a station with no signal is no problem. */
export default function ExpensesScreen() {
  const t = useTheme();
  const offline = useOffline();
  const { vehicle, trip, float, fuel } = offline.state.cache;
  const [form, setForm] = useState({ litres: "", price: "", total: "", station: "", code: "" });
  const [receipt, setReceipt] = useState<LocalPhoto | null>(null);
  const [capturing, setCapturing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);

  if (capturing) {
    return (
      <View style={{ flex: 1, padding: 16 }}>
        <ScrollView>
          <CaptureScreen
            kind="receipt"
            title="Photo of the receipt"
            hint="The whole receipt, flat and in focus."
            onCancel={() => setCapturing(false)}
            onDone={(photo) => {
              setReceipt(photo);
              setCapturing(false);
            }}
          />
        </ScrollView>
      </View>
    );
  }

  const litres = Number(form.litres);
  const price = Number(form.price);
  const total = Number(form.total);
  const ready = vehicle && litres > 0 && price > 0 && total > 0;

  async function save() {
    if (!vehicle) return;
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      await offline.addFuel({
        vehicleId: vehicle.vehicle.id,
        tripId: trip && trip.status !== "scheduled" && trip.status !== "completed" ? trip.id : null,
        litres: litres.toFixed(2),
        priceCents: kesToCents(price),
        amountCents: kesToCents(total),
        station: form.station,
        mpesaCode: form.code,
        receipt,
      });
      setForm({ litres: "", price: "", total: "", station: "", code: "" });
      setReceipt(null);
      setSaved(true);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <ScrollView
      style={{ backgroundColor: t.bg }}
      contentContainerStyle={{ padding: 16, gap: 14 }}
      keyboardShouldPersistTaps="handled"
    >
      <Title>Expenses</Title>
      <SyncBadge />
      <View style={{ padding: 16, borderRadius: 12, backgroundColor: t.surface, gap: 4 }}>
        <Body muted>Float balance</Body>
        <Text style={{ color: t.text, fontSize: 28, fontWeight: "700" }}>
          {float ? formatKes(float.balance_cents) : "Not downloaded yet"}
        </Text>
        {float?.recent.slice(0, 3).map((f) => (
          <Body key={f.id} muted>
            {new Date(f.sent_at).toLocaleDateString("en-KE")}: {formatKes(f.amount_cents)}
            {f.note ? `, ${f.note}` : ""}
          </Body>
        ))}
      </View>

      <Text style={{ color: t.text, fontSize: 20, fontWeight: "600" }}>Record fuel</Text>
      {!vehicle && <Body muted>You have no vehicle yet. Connect once to download it.</Body>}
      <Input
        label="Litres"
        value={form.litres}
        onChangeText={(v) => setForm({ ...form, litres: v })}
        keyboardType="decimal-pad"
      />
      <Input
        label="Price per litre (KES)"
        value={form.price}
        onChangeText={(v) => setForm({ ...form, price: v })}
        keyboardType="decimal-pad"
      />
      <Input
        label="Total paid (KES)"
        value={form.total}
        onChangeText={(v) => setForm({ ...form, total: v })}
        keyboardType="decimal-pad"
      />
      <Input
        label="Station"
        value={form.station}
        onChangeText={(v) => setForm({ ...form, station: v })}
      />
      <Input
        label="M-Pesa code"
        value={form.code}
        onChangeText={(v) => setForm({ ...form, code: v })}
        autoCapitalize="characters"
        maxLength={10}
      />
      <Button
        label={receipt ? "Receipt photo taken. Retake" : "Photo of the receipt"}
        kind="secondary"
        onPress={() => setCapturing(true)}
      />
      <ErrorText message={error} />
      {saved && <Body>Saved on this phone. It will be sent when there is a connection.</Body>}
      <Button label="Save fuel entry" onPress={save} busy={busy} disabled={!ready} />

      {fuel.length > 0 && (
        <Text style={{ color: t.text, fontSize: 20, fontWeight: "600" }}>Recent fuel</Text>
      )}
      {fuel.map((f) => (
        <View
          key={f.clientId}
          style={{ padding: 12, borderRadius: 12, backgroundColor: t.surface, gap: 2 }}
        >
          <Body>
            {f.litres} L, {formatKes(f.amount_cents)}
            {f.station ? `, ${f.station}` : ""}
          </Body>
          <Body muted>
            {f.synced ? "Sent" : "Waiting to send"}
            {f.flags.includes("no_receipt") ? ". No receipt photo" : ""}
            {f.flags.includes("amount_mismatch")
              ? ". Litres times price does not match the total"
              : ""}
          </Body>
        </View>
      ))}
    </ScrollView>
  );
}
