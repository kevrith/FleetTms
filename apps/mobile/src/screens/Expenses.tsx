import { formatKes, kesToCents, litresFromTotal } from "@fleettms/business-rules";
import type { ExpenseCategory } from "@fleettms/types";
import { useState } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";
import { CaptureScreen } from "../capture";
import type { LocalPhoto } from "../offline/types";
import { useOffline } from "../offline/runtime";
import { Body, Button, ErrorText, errorMessage, Input, Title, useTheme } from "../ui";
import { SyncBadge } from "./SyncStatus";

const CATEGORIES: { key: ExpenseCategory; label: string }[] = [
  { key: "toll", label: "Toll" },
  { key: "parking", label: "Parking" },
  { key: "food", label: "Food" },
  { key: "loading", label: "Loading" },
  { key: "police_county", label: "Police / county" },
  { key: "other", label: "Other" },
];
const STATUS_TEXT: Record<string, string> = {
  waiting: "Waiting to send",
  recorded: "Sent",
  approved: "Approved",
  awaiting_approval: "Sent. Waiting for the owner to approve",
  rejected: "The owner rejected it",
};

/** Float balance in big type, then expenses (a category and an amount), fuel, and the end-of-day report. */
export default function ExpensesScreen() {
  const t = useTheme();
  const offline = useOffline();
  const { vehicle, trip, float, fuel, expenses, sheet } = offline.state.cache;
  const balance = offline.balanceCents();
  const [category, setCategory] = useState<ExpenseCategory | null>(null);
  const [amount, setAmount] = useState("");
  const [more, setMore] = useState(false);
  const [note, setNote] = useState("");
  const [code, setCode] = useState("");
  const [receipt, setReceipt] = useState<LocalPhoto | null>(null);
  const [capturing, setCapturing] = useState<"receipt" | "fuel-receipt" | null>(null);
  const [fuelOpen, setFuelOpen] = useState(false);
  const [fuelForm, setFuelForm] = useState({
    litres: "",
    price: "",
    total: "",
    station: "",
    code: "",
  });
  const [litresTyped, setLitresTyped] = useState(false); // once the driver types litres, stop working them out
  const [fuelReceipt, setFuelReceipt] = useState<LocalPhoto | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (capturing) {
    return (
      <View style={{ flex: 1, padding: 16 }}>
        <ScrollView>
          <CaptureScreen
            kind="receipt"
            title="Photo of the receipt"
            hint="The whole receipt, flat and in focus."
            onCancel={() => setCapturing(null)}
            onDone={(photo) => {
              if (capturing === "receipt") setReceipt(photo);
              else setFuelReceipt(photo);
              setCapturing(null);
            }}
          />
        </ScrollView>
      </View>
    );
  }

  const cents = amount.trim() ? kesToCents(Number(amount)) : 0;

  async function save() {
    if (!category || cents <= 0) return;
    setBusy(true);
    setError(null);
    setSaved(null);
    try {
      await offline.addExpense({ category, amountCents: cents, note, mpesaCode: code, receipt });
      setSaved(
        `${formatKes(cents)} saved on this phone. It will be sent when there is a connection.`,
      );
      setCategory(null);
      setAmount("");
      setNote("");
      setCode("");
      setReceipt(null);
      setMore(false);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const litres = Number(fuelForm.litres);
  const price = Number(fuelForm.price);
  const total = Number(fuelForm.total);
  /** Price or total changed: the litres follow (total paid divided by price) unless the driver typed their own. */
  function changeFuel(change: { price?: string; total?: string }) {
    const next = { ...fuelForm, ...change };
    if (!litresTyped) next.litres = litresFromTotal(Number(next.total), Number(next.price));
    setFuelForm(next);
  }
  async function saveFuel() {
    if (!vehicle) return;
    setBusy(true);
    setError(null);
    try {
      await offline.addFuel({
        vehicleId: vehicle.vehicle.id,
        tripId: trip && trip.status !== "scheduled" && trip.status !== "completed" ? trip.id : null,
        litres: litres.toFixed(2),
        priceCents: kesToCents(price),
        amountCents: kesToCents(total),
        station: fuelForm.station,
        mpesaCode: fuelForm.code,
        receipt: fuelReceipt,
      });
      setFuelForm({ litres: "", price: "", total: "", station: "", code: "" });
      setLitresTyped(false);
      setFuelReceipt(null);
      setFuelOpen(false);
      setSaved("Fuel saved on this phone. It will be sent when there is a connection.");
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const reportQueued = offline.state.queue.some(
    (i) => i.type === "reconciliation.submit" && i.status === "queued",
  );
  const reportStatus = reportQueued ? "waiting" : (sheet?.status ?? "open");
  const REPORT_TEXT: Record<string, string> = {
    open: "Not sent yet",
    waiting: "Saved on this phone. It will be sent when there is a connection.",
    submitted: "Sent. Waiting for approval",
    approved: "Approved",
    rejected: "Sent back. Fix it and send again",
  };

  return (
    <ScrollView
      style={{ backgroundColor: t.bg }}
      contentContainerStyle={{ padding: 16, gap: 14 }}
      keyboardShouldPersistTaps="handled"
    >
      <Title>Expenses</Title>
      <SyncBadge />
      <View style={{ padding: 18, borderRadius: 14, backgroundColor: t.surface, gap: 2 }}>
        <Body muted>Float balance</Body>
        <Text style={{ color: t.text, fontSize: 44, fontWeight: "800" }}>
          {balance === null ? "Not downloaded yet" : formatKes(balance)}
        </Text>
      </View>

      <Text style={{ color: t.text, fontSize: 20, fontWeight: "600" }}>Add an expense</Text>
      {!vehicle && <Body muted>You have no vehicle yet. Connect once to download it.</Body>}
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
        {CATEGORIES.map((c) => (
          <Pressable
            key={c.key}
            accessibilityRole="button"
            accessibilityState={{ selected: category === c.key }}
            onPress={() => setCategory(c.key)}
            style={{
              paddingVertical: 14,
              paddingHorizontal: 18,
              borderRadius: 12,
              borderWidth: 2,
              borderColor: category === c.key ? "#1d4ed8" : t.muted,
              backgroundColor: category === c.key ? "#1d4ed8" : "transparent",
            }}
          >
            <Text
              style={{
                color: category === c.key ? "#fff" : t.text,
                fontSize: 17,
                fontWeight: "600",
              }}
            >
              {c.label}
            </Text>
          </Pressable>
        ))}
      </View>
      <Input
        label="Amount (KES)"
        value={amount}
        onChangeText={setAmount}
        keyboardType="decimal-pad"
      />
      {more ? (
        <>
          <Input label="Note" value={note} onChangeText={setNote} />
          <Input
            label="M-Pesa code"
            value={code}
            onChangeText={setCode}
            autoCapitalize="characters"
            maxLength={10}
          />
          <Button
            label={receipt ? "Receipt photo taken. Retake" : "Photo of the receipt"}
            kind="secondary"
            onPress={() => setCapturing("receipt")}
          />
        </>
      ) : (
        <Button
          label="Add a receipt, note or M-Pesa code"
          kind="secondary"
          onPress={() => setMore(true)}
        />
      )}
      <ErrorText message={error} />
      {saved && <Body>{saved}</Body>}
      <Button
        label="Save expense"
        onPress={save}
        busy={busy}
        disabled={!category || cents <= 0 || !vehicle}
      />

      {expenses.length > 0 && (
        <Text style={{ color: t.text, fontSize: 20, fontWeight: "600" }}>Recent expenses</Text>
      )}
      {expenses.map((e) => (
        <View
          key={e.clientId}
          style={{ padding: 12, borderRadius: 12, backgroundColor: t.surface, gap: 2 }}
        >
          <Body>
            {CATEGORIES.find((c) => c.key === e.category)?.label ?? e.category},{" "}
            {formatKes(e.amount_cents)}
          </Body>
          <Body muted>{STATUS_TEXT[e.status] ?? e.status}</Body>
        </View>
      ))}

      <Text style={{ color: t.text, fontSize: 20, fontWeight: "600" }}>End of day</Text>
      <View style={{ padding: 14, borderRadius: 12, backgroundColor: t.surface, gap: 4 }}>
        {sheet && (
          <Body muted>
            Opening {formatKes(sheet.opening_cents)}, floats {formatKes(sheet.floats_cents)}, spent{" "}
            {formatKes(sheet.expenses_cents)}
          </Body>
        )}
        <Body>{REPORT_TEXT[reportStatus]}</Body>
        {sheet?.status === "rejected" && sheet.note && <Body muted>{sheet.note}</Body>}
      </View>
      <Button
        label="Send today's report for approval"
        kind="secondary"
        onPress={() => void offline.submitReconciliation()}
        disabled={reportQueued || sheet?.status === "approved"}
      />

      <Text style={{ color: t.text, fontSize: 20, fontWeight: "600" }}>Fuel</Text>
      {fuelOpen ? (
        <>
          <Input
            label="Litres"
            value={fuelForm.litres}
            onChangeText={(v) => {
              setLitresTyped(v !== "");
              setFuelForm({ ...fuelForm, litres: v });
            }}
            keyboardType="decimal-pad"
          />
          <Input
            label="Price per litre (KES)"
            value={fuelForm.price}
            onChangeText={(v) => changeFuel({ price: v })}
            keyboardType="decimal-pad"
          />
          <Input
            label="Total paid (KES)"
            value={fuelForm.total}
            onChangeText={(v) => changeFuel({ total: v })}
            keyboardType="decimal-pad"
          />
          <Input
            label="Station"
            value={fuelForm.station}
            onChangeText={(v) => setFuelForm({ ...fuelForm, station: v })}
          />
          <Input
            label="M-Pesa code"
            value={fuelForm.code}
            onChangeText={(v) => setFuelForm({ ...fuelForm, code: v })}
            autoCapitalize="characters"
            maxLength={10}
          />
          <Button
            label={fuelReceipt ? "Receipt photo taken. Retake" : "Photo of the receipt"}
            kind="secondary"
            onPress={() => setCapturing("fuel-receipt")}
          />
          <Button
            label="Save fuel entry"
            onPress={saveFuel}
            busy={busy}
            disabled={!vehicle || !(litres > 0 && price > 0 && total > 0)}
          />
          <Button label="Cancel" kind="secondary" onPress={() => setFuelOpen(false)} />
        </>
      ) : (
        <Button label="Record fuel" kind="secondary" onPress={() => setFuelOpen(true)} />
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
          </Body>
        </View>
      ))}
      {float && float.recent.length > 0 && (
        <Text style={{ color: t.text, fontSize: 20, fontWeight: "600" }}>Floats you received</Text>
      )}
      {float?.recent.slice(0, 5).map((f) => (
        <Body key={f.id} muted>
          {new Date(f.sent_at).toLocaleDateString("en-KE")}: {formatKes(f.amount_cents)}
          {f.note ? `, ${f.note}` : ""}
        </Body>
      ))}
    </ScrollView>
  );
}
