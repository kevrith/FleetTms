import type { Vehicle } from "@fleettms/types";
import { useCallback, useEffect, useState } from "react";
import { RefreshControl, ScrollView, Text, View } from "react-native";
import { api } from "../api";
import { Body, ErrorText, errorMessage, Title, useTheme } from "../ui";

const OWNERSHIP: Record<Vehicle["ownership_type"], string> = {
  owned: "Owned",
  asset_financed: "Asset-financed",
  leased_in: "Leased-in",
  leased_out: "Leased-out",
};

/** Owner view: the fleet at a glance. Editing happens on the web. */
export default function VehiclesScreen() {
  const t = useTheme();
  const [vehicles, setVehicles] = useState<Vehicle[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      setVehicles(await api.vehicles());
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
        </View>
      ))}
    </ScrollView>
  );
}
