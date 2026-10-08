import { Ionicons } from "@expo/vector-icons";
import { colors, tapTarget } from "@fleettms/design-tokens";
import type {
  Dashboard,
  DashboardAlert,
  DashboardDeadline,
  DashboardEmergency,
} from "@fleettms/types";
import { useNavigation, type NavigationProp, type ParamListBase } from "@react-navigation/native";
import { useCallback, useEffect, useState } from "react";
import { Alert, Linking, Pressable, RefreshControl, ScrollView, Text, View } from "react-native";
import { api } from "../api";
import { useAuth } from "../auth";
import { daysPhrase } from "../dates";
import { registerForPush } from "../push";
import { ago, fleetLine, kesShort, tabForLink, tripsLine, visibleAlerts } from "../dashboard";
import { Body, Title, useTheme } from "../ui";

type IconName = React.ComponentProps<typeof Ionicons>["name"];

function EmergencyBanner({
  e,
  now,
  onChanged,
}: {
  e: DashboardEmergency;
  now: number;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  async function answer(work: () => Promise<unknown>) {
    setBusy(true);
    try {
      await work();
      onChanged();
    } catch {
      Alert.alert("That did not work", "Check your connection and try again.");
    } finally {
      setBusy(false);
    }
  }
  const resolve = () =>
    Alert.alert(
      "Close this SOS?",
      "Only do this when the driver is safe and the matter is settled.",
      [
        { text: "Not yet", style: "cancel" },
        { text: "Yes, close it", onPress: () => void answer(() => api.resolveSos(e.id)) },
      ],
    );
  const who = e.driver ?? "A driver";
  const title = e.kind === "sos" ? `SOS: ${who} needs help` : `Breakdown: ${who}`;
  const where = [e.registration, ago(e.since, now)].filter(Boolean).join(" · ");
  const status =
    e.kind === "sos" ? (e.answered ? "Someone has answered." : "Nobody has answered yet.") : "";
  const action = (icon: IconName, label: string, onPress: () => void) => (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      style={{
        flex: 1,
        minHeight: tapTarget,
        borderRadius: 10,
        backgroundColor: "#fff",
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "center",
        gap: 8,
      }}
    >
      <Ionicons name={icon} size={22} color={colors.alert} />
      <Text style={{ color: colors.alert, fontSize: 18, fontWeight: "700" }}>{label}</Text>
    </Pressable>
  );
  return (
    <View style={{ padding: 14, borderRadius: 12, backgroundColor: colors.alert, gap: 8 }}>
      <Text style={{ color: "#fff", fontSize: 20, fontWeight: "800" }}>{title}</Text>
      <Text style={{ color: "#fff", fontSize: 16 }}>{where}</Text>
      {status ? <Text style={{ color: "#fff", fontSize: 16 }}>{status}</Text> : null}
      <View style={{ flexDirection: "row", gap: 8 }}>
        {e.phone ? action("call", "Call", () => void Linking.openURL(`tel:${e.phone}`)) : null}
        {e.lat != null && e.lng != null
          ? action(
              "location",
              "Location",
              () =>
                void Linking.openURL(
                  `geo:${e.lat},${e.lng}?q=${e.lat},${e.lng}(${encodeURIComponent(e.registration ?? who)})`,
                ),
            )
          : null}
      </View>
      {e.kind === "sos" ? (
        <View style={{ flexDirection: "row", gap: 8 }}>
          {!e.answered
            ? action(
                "hand-left",
                busy ? "..." : "I'm on it",
                () => void answer(() => api.acknowledgeSos(e.id)),
              )
            : null}
          {action("checkmark-circle", "Resolved", resolve)}
        </View>
      ) : null}
    </View>
  );
}

/**
 * An insurance or inspection that is close to running out or already has. Amber within 14 days, red once expired. Not an alarm like an
 * SOS (that must stay rare); it cannot be scrolled past, and the button goes to where the new date is set.
 */
function DeadlineBanner({ d, onRenew }: { d: DashboardDeadline; onRenew: (() => void) | null }) {
  const expired = d.level === "expired";
  const colour = expired ? colors.alert : "#b45309";
  return (
    <View style={{ padding: 14, borderRadius: 12, backgroundColor: colour, gap: 6 }}>
      <Text style={{ color: "#fff", fontSize: 18, fontWeight: "800" }}>
        {d.kind === "insurance" ? "Insurance" : "Inspection"}: {d.registration}
      </Text>
      <Text style={{ color: "#fff", fontSize: 16 }}>
        {daysPhrase(d.days_left)} ({d.expires_on})
      </Text>
      {onRenew ? (
        <Pressable
          accessibilityRole="button"
          onPress={onRenew}
          style={{
            minHeight: tapTarget,
            borderRadius: 10,
            backgroundColor: "#fff",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <Text style={{ color: colour, fontSize: 18, fontWeight: "700" }}>Set the new date</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

function Tile({
  label,
  value,
  sub,
  onPress,
}: {
  label: string;
  value: string;
  sub?: string;
  onPress: (() => void) | null;
}) {
  const t = useTheme();
  return (
    <Pressable
      accessibilityRole={onPress ? "button" : "text"}
      accessibilityLabel={`${label}: ${value}${sub ? `, ${sub}` : ""}`}
      disabled={!onPress}
      onPress={onPress ?? undefined}
      style={{ width: "48%", padding: 14, borderRadius: 12, backgroundColor: t.surface, gap: 2 }}
    >
      <Body muted>{label}</Body>
      <Text
        style={{ color: t.text, fontSize: 24, fontWeight: "800" }}
        numberOfLines={1}
        adjustsFontSizeToFit
      >
        {value}
      </Text>
      {sub ? <Body muted>{sub}</Body> : null}
    </Pressable>
  );
}

function Strip({
  icon,
  children,
  onPress,
}: {
  icon: IconName;
  children: React.ReactNode;
  onPress: (() => void) | null;
}) {
  const t = useTheme();
  return (
    <Pressable
      accessibilityRole={onPress ? "button" : "text"}
      disabled={!onPress}
      onPress={onPress ?? undefined}
      style={{
        padding: 14,
        borderRadius: 12,
        backgroundColor: t.surface,
        flexDirection: "row",
        alignItems: "center",
        gap: 10,
      }}
    >
      <Ionicons name={icon} size={22} color={t.muted} />
      <View style={{ flex: 1, gap: 2 }}>{children}</View>
      {onPress ? <Ionicons name="chevron-forward" size={20} color={t.muted} /> : null}
    </Pressable>
  );
}

function AlertCard({ a, onPress }: { a: DashboardAlert; onPress: (() => void) | null }) {
  const t = useTheme();
  return (
    <Pressable
      accessibilityRole={onPress ? "button" : "text"}
      disabled={!onPress}
      onPress={onPress ?? undefined}
      style={{
        padding: 12,
        borderRadius: 12,
        backgroundColor: t.surface,
        borderLeftWidth: 5,
        borderLeftColor: a.severity === "red" ? colors.alert : colors.warning,
        flexDirection: "row",
        alignItems: "center",
        gap: 8,
      }}
    >
      <View style={{ flex: 1, gap: 2 }}>
        <Body>{a.title}</Body>
        {a.detail ? <Body muted>{a.detail}</Body> : null}
      </View>
      {onPress ? <Ionicons name="chevron-forward" size={20} color={t.muted} /> : null}
    </Pressable>
  );
}

export default function OwnerHome() {
  const { me } = useAuth();
  const t = useTheme();
  const nav = useNavigation<NavigationProp<ParamListBase>>();
  const [data, setData] = useState<Dashboard | null>(null);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const [failed, setFailed] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [now, setNow] = useState(Date.now());

  const load = useCallback(async () => {
    try {
      setData(await api.dashboard());
      setUpdatedAt(Date.now());
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    void registerForPush(); // so an SOS reaches this phone with the app closed
  }, []);

  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), 15_000); // an SOS shows up here within seconds
    const clock = setInterval(() => setNow(Date.now()), 30_000); // keeps "Updated 2 min ago" honest
    return () => {
      clearInterval(timer);
      clearInterval(clock);
    };
  }, [load]);

  const tabs = nav.getState()?.routeNames ?? [];
  const goto = (tab: string | null) => (tab && tabs.includes(tab) ? () => nav.navigate(tab) : null);

  const n = data?.numbers;
  const money = data?.profit_vs_cash;
  const alerts = visibleAlerts(data?.alerts ?? [], showAll);
  const totalAlerts = alerts.urgent + alerts.watch;
  const tiles: React.ReactNode[] = [];
  if (n?.income_today_cents != null)
    tiles.push(
      <Tile
        key="billed"
        label="Billed today"
        value={kesShort(n.income_today_cents)}
        onPress={null}
      />,
    );
  if (n?.money_owed_cents != null)
    tiles.push(
      <Tile key="owed" label="Owed to me" value={kesShort(n.money_owed_cents)} onPress={null} />,
    );
  if (n?.expenses_today_cents !== undefined)
    tiles.push(
      <Tile
        key="expenses"
        label="Expenses today"
        value={kesShort(n.expenses_today_cents)}
        sub={n.fuel_today ? `Fuel ${kesShort(n.fuel_today.amount_cents)}` : undefined}
        onPress={goto("Money")}
      />,
    );
  if (n?.trips_active !== undefined)
    tiles.push(
      <Tile
        key="trips"
        label="Trips"
        value={`${n.trips_active} running`}
        sub={tripsLine(n.trips_active, n.trips_completed_today ?? 0).split(" · ")[1]}
        onPress={goto("Map")}
      />,
    );

  return (
    <ScrollView
      style={{ flex: 1 }}
      contentContainerStyle={{ gap: 12, paddingVertical: 16 }}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={async () => {
            setRefreshing(true);
            await load();
            setRefreshing(false);
          }}
        />
      }
    >
      <View style={{ gap: 2 }}>
        <Title>{me?.business?.name}</Title>
        <Body muted>
          {failed
            ? updatedAt
              ? `Could not refresh. Showing figures from ${ago(updatedAt, now)}.`
              : "The dashboard needs an internet connection. Pull down to try again."
            : updatedAt
              ? `Updated ${ago(updatedAt, now)}`
              : "Loading"}
        </Body>
      </View>

      {(data?.emergencies ?? []).map((e) => (
        <EmergencyBanner key={`${e.kind}-${e.id}`} e={e} now={now} onChanged={() => void load()} />
      ))}

      {(data?.deadlines ?? []).map((d) => (
        <DeadlineBanner key={d.id} d={d} onRenew={goto("Vehicles")} />
      ))}

      {tiles.length > 0 && (
        <View
          style={{
            flexDirection: "row",
            flexWrap: "wrap",
            gap: 12,
            justifyContent: "space-between",
          }}
        >
          {tiles}
        </View>
      )}

      {money && (
        <Strip icon="trending-up-outline" onPress={null}>
          <Body muted>This month</Body>
          <View style={{ flexDirection: "row", gap: 12 }}>
            {(
              [
                ["Profit", money.profit_cents],
                ["Cash", money.cash_cents],
              ] as const
            ).map(([label, cents]) => (
              <View key={label} style={{ flex: 1 }}>
                <Body muted>{label}</Body>
                <Text
                  style={{
                    fontSize: 20,
                    fontWeight: "800",
                    color: cents < 0 ? colors.alert : t.text,
                  }}
                  numberOfLines={1}
                  adjustsFontSizeToFit
                >
                  {kesShort(cents)}
                </Text>
              </View>
            ))}
          </View>
          <Body muted>Profit counts what you billed. Cash counts what clients have paid.</Body>
        </Strip>
      )}

      {data?.fleet && data.fleet.total > 0 && (
        <Strip icon="bus-outline" onPress={goto("Map")}>
          <Body>{fleetLine(data.fleet)}</Body>
        </Strip>
      )}

      {data && totalAlerts === 0 && (data.emergencies ?? []).length === 0 && (
        <Strip icon="checkmark-circle-outline" onPress={null}>
          <Body>Nothing needs your attention right now.</Body>
        </Strip>
      )}

      {totalAlerts > 0 && (
        <Body muted>
          Needs attention:{" "}
          {[
            alerts.urgent ? `${alerts.urgent} urgent` : "",
            alerts.watch ? `${alerts.watch} to watch` : "",
          ]
            .filter(Boolean)
            .join(", ")}
        </Body>
      )}
      {alerts.shown.map((a, i) => (
        <AlertCard key={`${a.kind}-${i}`} a={a} onPress={goto(tabForLink(a.link))} />
      ))}
      {(alerts.hidden > 0 || showAll) && totalAlerts > 3 && (
        <Pressable
          accessibilityRole="button"
          onPress={() => setShowAll(!showAll)}
          style={{ minHeight: tapTarget, alignItems: "center", justifyContent: "center" }}
        >
          <Text style={{ color: colors.brand, fontSize: 16, fontWeight: "600" }}>
            {showAll ? "Show fewer" : `See all ${totalAlerts}`}
          </Text>
        </Pressable>
      )}
    </ScrollView>
  );
}
