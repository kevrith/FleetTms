import { odometerProblem, parseOdometer } from "@fleettms/business-rules";
import type { Inspection, MyVehicle, Trip } from "@fleettms/types";
import { useCallback, useEffect, useState } from "react";
import { Image, ScrollView, Text, View } from "react-native";
import { api } from "../api";
import { CaptureScreen } from "../capture";
import { Body, Button, ErrorText, errorMessage, Input, useTheme } from "../ui";
import InspectionFlow from "./InspectionFlow";

type Mode =
  | { kind: "idle" }
  | { kind: "inspection" }
  | { kind: "odometer"; phase: "start" | "end" }
  | { kind: "reading"; phase: "start" | "end"; photoId: string; uri: string }
  | { kind: "cargo" };

/** The driver's current trip and the one next step. Everything the trip needs is done from here. */
export default function TripPanel() {
  const t = useTheme();
  const [trip, setTrip] = useState<Trip | null | undefined>(undefined);
  const [mine, setMine] = useState<MyVehicle | null>(null);
  const [today, setToday] = useState<{
    inspection: Inspection | null;
    can_start_trip: boolean;
  } | null>(null);
  const [mode, setMode] = useState<Mode>({ kind: "idle" });
  const [typed, setTyped] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [trips, vehicle] = await Promise.all([api.myTrips(), api.myVehicle()]);
      const current = trips[0] ?? null;
      setTrip(current);
      setMine(vehicle);
      setToday(current ? await api.inspectionToday(current.vehicle_id) : null);
    } catch (e) {
      setError(errorMessage(e));
      setTrip(null);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const finish = () => {
    setMode({ kind: "idle" });
    setTyped("");
    void load();
  };

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      finish();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  if (trip === undefined) return <Body muted>Loading...</Body>;
  if (trip === null) {
    return (
      <View style={{ padding: 16, borderRadius: 12, backgroundColor: t.surface, gap: 4 }}>
        <Body muted>Today's trip</Body>
        <Text style={{ color: t.text, fontSize: 20 }}>No trip assigned yet</Text>
        <ErrorText message={error} />
      </View>
    );
  }

  const lastKnown = mine?.vehicle.odometer_km ?? 0;

  if (mode.kind === "inspection") {
    return (
      <InspectionFlow
        vehicleId={trip.vehicle_id}
        onCancel={() => setMode({ kind: "idle" })}
        onDone={(result) => {
          setMode({ kind: "idle" });
          setToday({ inspection: result, can_start_trip: result.status !== "blocked" });
          void load();
        }}
      />
    );
  }
  if (mode.kind === "odometer") {
    return (
      <CaptureScreen
        kind="odometer"
        title={mode.phase === "start" ? "Odometer at the start" : "Odometer at the end"}
        hint="Line the odometer up in the frame. Avoid glare, and keep the numbers sharp."
        guide
        onCancel={() => setMode({ kind: "idle" })}
        onDone={(photo, uri) =>
          setMode({ kind: "reading", phase: mode.phase, photoId: photo.id, uri })
        }
      />
    );
  }
  if (mode.kind === "cargo") {
    return (
      <CaptureScreen
        kind="cargo"
        title="Photo of the cargo"
        hint="Show the load on the vehicle."
        onCancel={() => setMode({ kind: "idle" })}
        onDone={(photo) => run(() => api.recordLoading(trip.id, photo.id))}
      />
    );
  }
  if (mode.kind === "reading") {
    const startValue = trip.start_reading?.value;
    const problem = typed
      ? odometerProblem(
          typed,
          mode.phase === "start" ? lastKnown : (startValue ?? lastKnown),
          mode.phase === "end" ? startValue : undefined,
        )
      : null;
    const value = parseOdometer(typed);
    const submit = () =>
      run(() => {
        const reading = { photo_id: mode.photoId, value: value as number };
        return mode.phase === "start"
          ? api.startTrip(trip.id, reading)
          : api.endTrip(trip.id, reading);
      });
    return (
      <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ gap: 12 }}>
        <Text style={{ color: t.text, fontSize: 22, fontWeight: "700" }}>Confirm the odometer</Text>
        <Image
          source={{ uri: mode.uri }}
          style={{ width: "100%", height: 200, borderRadius: 12 }}
          resizeMode="cover"
        />
        <Input
          label="Type the number you see (km)"
          value={typed}
          onChangeText={setTyped}
          keyboardType="number-pad"
          autoFocus
        />
        {problem && <Body muted>{problem}</Body>}
        <ErrorText message={error} />
        <Button
          label={mode.phase === "start" ? "Start trip" : "End trip"}
          onPress={submit}
          busy={busy}
          disabled={value === null}
        />
        <Button
          label="Cancel"
          kind="secondary"
          onPress={() => setMode({ kind: "idle" })}
          disabled={busy}
        />
      </ScrollView>
    );
  }

  const inspection = today?.inspection ?? null;
  const blocked = inspection?.status === "blocked";
  return (
    <View style={{ gap: 12 }}>
      <View style={{ padding: 16, borderRadius: 12, backgroundColor: t.surface, gap: 4 }}>
        <Body muted>Today's trip</Body>
        <Text style={{ color: t.text, fontSize: 20, fontWeight: "600" }}>
          {[trip.origin, trip.destination].filter(Boolean).join(" to ") || trip.registration}
        </Text>
        {trip.cargo_description && <Body>{trip.cargo_description}</Body>}
        <Body muted>
          {trip.status === "scheduled"
            ? "Not started"
            : trip.status === "in_progress"
              ? "In progress"
              : "Delivered"}
          {trip.start_reading ? `, started at ${trip.start_reading.value.toLocaleString()} km` : ""}
        </Body>
      </View>
      <ErrorText message={error} />
      {trip.status === "scheduled" && (
        <>
          {blocked && (
            <Body>
              The inspection found a critical fault. A manager must clear it before you can start.
            </Body>
          )}
          {!inspection && <Body muted>Do the pre-trip inspection first.</Body>}
          {today?.can_start_trip ? (
            <Button
              label="Start trip"
              onPress={() => setMode({ kind: "odometer", phase: "start" })}
            />
          ) : (
            <Button
              label={inspection ? "Redo inspection" : "Pre-trip inspection"}
              onPress={() => setMode({ kind: "inspection" })}
            />
          )}
        </>
      )}
      {trip.status === "in_progress" && (
        <>
          {!trip.cargo_photo && (
            <Button
              label="Photograph the cargo"
              kind="secondary"
              onPress={() => setMode({ kind: "cargo" })}
            />
          )}
          <Button
            label="Mark delivered"
            kind="secondary"
            onPress={() => run(() => api.deliverTrip(trip.id))}
            busy={busy}
          />
          <Button label="End trip" onPress={() => setMode({ kind: "odometer", phase: "end" })} />
        </>
      )}
      {trip.status === "delivered" && (
        <Button label="End trip" onPress={() => setMode({ kind: "odometer", phase: "end" })} />
      )}
    </View>
  );
}
