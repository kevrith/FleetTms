import type { ComplianceCell, Vehicle, VehicleCompliance } from "@fleettms/types";
import { useCallback, useEffect, useState } from "react";
import { RefreshControl, ScrollView, Text, View } from "react-native";
import { api } from "../api";
import { daysPhrase, parseDateInput } from "../dates";
import { Body, Button, ErrorText, errorMessage, Input, Title, useTheme } from "../ui";

const OWNERSHIP: Record<Vehicle["ownership_type"], string> = {
  owned: "Owned",
  asset_financed: "Asset-financed",
  leased_in: "Leased-in",
  leased_out: "Leased-out",
};

const STATUS_COLOUR: Record<ComplianceCell["status"], string> = {
  ok: "#16a34a",
  due_soon: "#d97706",
  expired: "#dc2626",
  missing: "#dc2626",
};

/** One line of a vehicle's insurance or inspection, with a way to set or renew the date. */
function ComplianceLine({
  row,
  kind,
  label,
  onSaved,
}: {
  row: VehicleCompliance;
  kind: "insurance" | "inspection";
  label: string;
  onSaved: () => void;
}) {
  const cell = row[kind];
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const parsed = parseDateInput(text);

  async function save() {
    if (!parsed) return;
    setBusy(true);
    setError(null);
    try {
      await api.setVehicleExpiry(row.vehicle_id, kind, parsed);
      setEditing(false);
      setText("");
      onSaved();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <View style={{ gap: 6, paddingTop: 6 }}>
      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
        <View style={{ flex: 1 }}>
          <Body>{label}</Body>
          <Text style={{ color: STATUS_COLOUR[cell.status], fontSize: 16, fontWeight: "600" }}>
            {cell.status === "missing"
              ? "Not recorded: you will not be reminded"
              : `${daysPhrase(cell.days_left ?? 0)} (${cell.expires_on})`}
          </Text>
        </View>
        {!editing && (
          <Button
            label={cell.expires_on ? "Renew" : "Add date"}
            kind="secondary"
            onPress={() => setEditing(true)}
          />
        )}
      </View>
      {editing && (
        <View style={{ gap: 6 }}>
          <Input
            label={`When does the ${label.toLowerCase()} run out?`}
            value={text}
            onChangeText={setText}
            placeholder="31/12/2026"
            keyboardType="numbers-and-punctuation"
          />
          {text.trim() !== "" && !parsed && <Body muted>Type the date as day/month/year.</Body>}
          <ErrorText message={error} />
          <Button label="Save" onPress={save} busy={busy} disabled={!parsed} />
          <Button
            label="Cancel"
            kind="secondary"
            onPress={() => setEditing(false)}
            disabled={busy}
          />
        </View>
      )}
    </View>
  );
}

/** Owner view: the fleet at a glance, with insurance and inspection dates. The rest of editing happens on the web. */
export default function VehiclesScreen() {
  const t = useTheme();
  const [vehicles, setVehicles] = useState<Vehicle[] | null>(null);
  const [compliance, setCompliance] = useState<VehicleCompliance[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      setVehicles(await api.vehicles());
      setCompliance(await api.vehicleCompliance().catch(() => [])); // a role without the right to see these simply gets no lines
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  async function refresh() {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }

  return (
    <ScrollView
      style={{ backgroundColor: t.bg }}
      contentContainerStyle={{ padding: 16, gap: 12 }}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} />}
    >
      <Title>Vehicles</Title>
      <ErrorText message={error} />
      {vehicles?.length === 0 && <Body muted>No vehicles yet. Add them on the web dashboard.</Body>}
      {vehicles?.map((v) => (
        <View
          key={v.id}
          style={{ padding: 16, borderRadius: 12, backgroundColor: t.surface, gap: 4 }}
        >
          <Text style={{ color: t.text, fontSize: 20, fontWeight: "600" }}>{v.registration}</Text>
          <Body>{[v.make, v.model].filter(Boolean).join(" ") || "No make or model"}</Body>
          <Body muted>
            {OWNERSHIP[v.ownership_type]}, {v.odometer_km.toLocaleString()} km
          </Body>
          {compliance
            .filter((c) => c.vehicle_id === v.id)
            .map((c) => (
              <View key={c.vehicle_id} style={{ gap: 4 }}>
                <ComplianceLine row={c} kind="insurance" label="Insurance" onSaved={load} />
                <ComplianceLine row={c} kind="inspection" label="Inspection" onSaved={load} />
              </View>
            ))}
        </View>
      ))}
    </ScrollView>
  );
}
