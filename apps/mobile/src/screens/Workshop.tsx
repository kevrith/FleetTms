import type { Part, WorkOrder } from "@fleettms/types";
import { formatKes } from "@fleettms/business-rules";
import { useCallback, useEffect, useState } from "react";
import { RefreshControl, ScrollView, Text, View } from "react-native";
import { api } from "../api";
import { Body, Button, ErrorText, errorMessage, Screen, Title, useTheme } from "../ui";

const PRIORITY: Record<string, string> = {
  urgent: "Urgent",
  high: "High",
  normal: "Normal",
  low: "Low",
};
const STATUS: Record<string, string> = {
  open: "Open",
  in_progress: "In progress",
  waiting_parts: "Waiting for parts",
};

function WorkOrderCard({
  wo,
  stock,
  onChanged,
}: {
  wo: WorkOrder;
  stock: Part[];
  onChanged: () => Promise<void>;
}) {
  const t = useTheme();
  const [open, setOpen] = useState(false);
  const [picking, setPicking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const store = wo.parts.filter((p) => p.part_id);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      await onChanged();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <View
      style={{
        padding: 14,
        borderRadius: 12,
        backgroundColor: t.surface,
        gap: 8,
        borderLeftWidth: 5,
        borderLeftColor:
          wo.priority === "urgent" ? "#d92d20" : wo.priority === "high" ? "#f79009" : "#12b76a",
      }}
    >
      <Text style={{ color: t.text, fontSize: 18, fontWeight: "600" }}>
        {wo.registration}: {wo.title}
      </Text>
      <Body muted>
        {PRIORITY[wo.priority]}, {STATUS[wo.status] ?? wo.status}
        {wo.total_cents > 0 ? `, ${formatKes(wo.total_cents)} so far` : ""}
      </Body>
      <Button label={open ? "Close" : "Open"} kind="secondary" onPress={() => setOpen(!open)} />
      {open && (
        <>
          {wo.description ? <Body>{wo.description}</Body> : null}
          {store.map((p) => (
            <View key={p.id} style={{ gap: 6 }}>
              <Body>
                {p.quantity} x {p.name}: {p.fitted ? "fitted" : "not yet confirmed as fitted"}
              </Body>
              <View style={{ flexDirection: "row", gap: 8 }}>
                <View style={{ flex: 1 }}>
                  <Button
                    label={p.fitted ? "Not fitted" : "Mark fitted"}
                    kind="secondary"
                    disabled={busy}
                    onPress={() => run(() => api.markPartFitted(wo.id, p.id, !p.fitted))}
                  />
                </View>
                <View style={{ flex: 1 }}>
                  <Button
                    label="Return"
                    kind="secondary"
                    disabled={busy}
                    onPress={() => run(() => api.returnPart(wo.id, p.id))}
                  />
                </View>
              </View>
            </View>
          ))}
          {picking ? (
            <>
              <Body muted>Which part?</Body>
              {stock.length === 0 && <Body muted>The store has no parts yet.</Body>}
              {stock.map((p) => (
                <Button
                  key={p.id}
                  label={`${p.name} (${p.quantity} in stock)`}
                  kind="secondary"
                  disabled={busy || p.quantity === 0}
                  onPress={() =>
                    run(async () => {
                      await api.issuePart(wo.id, p.id, 1);
                      setPicking(false);
                    })
                  }
                />
              ))}
              <Button label="Cancel" kind="secondary" onPress={() => setPicking(false)} />
            </>
          ) : (
            <Button label="Issue a part (1)" kind="secondary" onPress={() => setPicking(true)} />
          )}
          {wo.status !== "in_progress" && (
            <Button
              label="Start work"
              kind="secondary"
              disabled={busy}
              onPress={() => run(() => api.updateWorkOrder(wo.id, { status: "in_progress" }))}
            />
          )}
          <Button
            label="Job finished"
            busy={busy}
            onPress={() => run(() => api.completeWorkOrder(wo.id, {}))}
          />
          <ErrorText message={error} />
        </>
      )}
    </View>
  );
}

/** The workshop's open work orders, with parts issued from the store. */
export function WorkOrdersScreen() {
  const [orders, setOrders] = useState<WorkOrder[]>([]);
  const [stock, setStock] = useState<Part[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    setRefreshing(true);
    try {
      const [o, s] = await Promise.all([api.workOrders({ openOnly: true }), api.parts()]);
      setOrders(o);
      setStock(s);
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setRefreshing(false);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  return (
    <Screen>
      <Title>Work orders</Title>
      <ErrorText message={error} />
      <ScrollView
        contentContainerStyle={{ gap: 12, paddingVertical: 8 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={load} />}
      >
        {orders.length === 0 && !refreshing && <Body muted>No open work orders.</Body>}
        {orders.map((wo) => (
          <WorkOrderCard
            key={wo.id + wo.status + wo.parts.length}
            wo={wo}
            stock={stock}
            onChanged={load}
          />
        ))}
      </ScrollView>
    </Screen>
  );
}

/** What is in the store, with low stock first. */
export function PartsScreen() {
  const t = useTheme();
  const [parts, setParts] = useState<Part[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    setRefreshing(true);
    try {
      setParts(await api.parts());
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setRefreshing(false);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  const sorted = [...parts].sort(
    (a, b) => Number(b.low_stock) - Number(a.low_stock) || a.name.localeCompare(b.name),
  );
  return (
    <Screen>
      <Title>Parts store</Title>
      <ErrorText message={error} />
      <ScrollView
        contentContainerStyle={{ gap: 10, paddingVertical: 8 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={load} />}
      >
        {sorted.length === 0 && !refreshing && <Body muted>No parts in the store yet.</Body>}
        {sorted.map((p) => (
          <View
            key={p.id}
            style={{
              padding: 14,
              borderRadius: 12,
              backgroundColor: t.surface,
              borderLeftWidth: 5,
              borderLeftColor: p.low_stock ? "#d92d20" : "#12b76a",
              gap: 2,
            }}
          >
            <Text style={{ color: t.text, fontSize: 18, fontWeight: "600" }}>{p.name}</Text>
            <Body>
              {p.quantity} {p.unit} in stock
              {p.low_stock ? " (low, time to order)" : ""}
            </Body>
            <Body muted>{formatKes(p.unit_cost_cents)} each</Body>
          </View>
        ))}
      </ScrollView>
    </Screen>
  );
}
