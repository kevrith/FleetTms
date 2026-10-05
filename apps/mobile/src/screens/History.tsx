import { formatKes } from "@fleettms/business-rules";
import type { MyPayLine, Trip } from "@fleettms/types";
import { useState } from "react";
import { View } from "react-native";
import { api } from "../api";
import { Body, Button, ErrorText, errorMessage, useTheme } from "../ui";

const day = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" }) : "";
const month = (iso: string) =>
  new Date(iso).toLocaleDateString(undefined, { month: "long", year: "numeric" });

/** What the driver has done and been paid: finished trips, and each month's pay once the owner has approved it. Needs a connection. */
export function HistoryCard() {
  const t = useTheme();
  const [view, setView] = useState<"closed" | "trips" | "pay">("closed");
  const [trips, setTrips] = useState<Trip[] | null>(null);
  const [pay, setPay] = useState<MyPayLine[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function show(next: "trips" | "pay") {
    setView(next);
    setError(null);
    setBusy(true);
    try {
      if (next === "trips") setTrips(await api.myTripHistory());
      else setPay(await api.myPay());
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  if (view === "closed") {
    return <Button kind="secondary" label="My trips and my pay" onPress={() => void show("trips")} />;
  }
  return (
    <View style={{ padding: 16, borderRadius: 12, backgroundColor: t.surface, gap: 10 }}>
      <Button
        label="My trips"
        kind={view === "trips" ? "primary" : "secondary"}
        onPress={() => void show("trips")}
        disabled={busy}
      />
      <Button
        label="My pay"
        kind={view === "pay" ? "primary" : "secondary"}
        onPress={() => void show("pay")}
        disabled={busy}
      />
      <ErrorText message={error} />
      {view === "trips" && trips?.length === 0 && <Body muted>No finished trips yet.</Body>}
      {view === "trips" &&
        trips?.map((trip) => (
          <View key={trip.id}>
            <Body>
              {[trip.origin, trip.destination].filter(Boolean).join(" to ") ||
                trip.cargo_description ||
                "Trip"}
            </Body>
            <Body muted>
              {day(trip.ended_at)}, {trip.registration}
              {trip.distance_km ? `, ${trip.distance_km.toLocaleString()} km` : ""}
            </Body>
          </View>
        ))}
      {view === "pay" && pay?.length === 0 && (
        <Body muted>No pay to show yet. A month appears here once the owner has approved it.</Body>
      )}
      {view === "pay" &&
        pay?.map((p) => (
          <View key={p.month}>
            <Body>
              {month(p.month)}: {formatKes(p.net_cents)}
            </Body>
            <Body muted>
              Pay {formatKes(p.gross_cents)}
              {p.advances_cents > 0 ? `, advances taken ${formatKes(p.advances_cents)}` : ""}
              {p.fines_cents > 0 ? `, fines taken ${formatKes(p.fines_cents)}` : ""}.{" "}
              {p.status === "paid" ? `Paid ${day(p.paid_on)}.` : "Approved, not yet paid."}
            </Body>
          </View>
        ))}
      <Button label="Close" kind="secondary" onPress={() => setView("closed")} />
    </View>
  );
}
