import {
  isBelowMinimum,
  minimumReading,
  nairobiDay,
  odometerProblem,
  parseOdometer,
} from "@fleettms/business-rules";
import { useState } from "react";
import { ScrollView, Text, View } from "react-native";
import { CaptureScreen } from "../capture";
import type { LocalPhoto } from "../offline/types";
import { useOffline } from "../offline/runtime";
import { Body, Button, ErrorText, errorMessage, Input, useTheme } from "../ui";
import Delivery from "./Delivery";
import InspectionFlow from "./InspectionFlow";
import Loading from "./Loading";

type Mode =
  | { kind: "idle" }
  | { kind: "inspection" }
  | { kind: "odometer"; phase: "start" | "end" }
  | { kind: "reading"; phase: "start" | "end"; photo: LocalPhoto }
  | { kind: "cargo" }
  | { kind: "delivery" };

/**
 * The driver's current trip and the one next step. Everything works with no network: each step is saved on the phone
 * at once and sent later, with the time the driver did it.
 */
/** A moment in Nairobi time, like "Fri 3 Oct, 06:00". */
const formatWhen = (iso: string) =>
  new Date(iso).toLocaleString("en-KE", {
    timeZone: "Africa/Nairobi",
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });

export default function TripPanel() {
  const t = useTheme();
  const offline = useOffline();
  const { trip, vehicle, inspection } = offline.state.cache;
  const [mode, setMode] = useState<Mode>({ kind: "idle" });
  const [typed, setTyped] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const finish = () => {
    setMode({ kind: "idle" });
    setTyped("");
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

  if (!offline.ready) return <Body muted>Loading...</Body>;
  if (trip === null) {
    return (
      <View style={{ padding: 16, borderRadius: 12, backgroundColor: t.surface, gap: 4 }}>
        <Body muted>Today's trip</Body>
        <Text style={{ color: t.text, fontSize: 20 }}>No trip assigned yet</Text>
        {offline.state.cache.refreshedAt === null && (
          <Body muted>Connect once to download today's trip.</Body>
        )}
      </View>
    );
  }

  const lastKnown = vehicle?.vehicle.odometer_km ?? 0;
  const today =
    inspection &&
    inspection.vehicleId === trip.vehicle_id &&
    inspection.day === nairobiDay(new Date());
  const status = today ? inspection.status : null;
  const blocked = status === "blocked";
  const cleared = status !== null && !blocked;

  if (mode.kind === "inspection") {
    return <InspectionFlow vehicleId={trip.vehicle_id} onCancel={finish} onDone={finish} />;
  }
  if (mode.kind === "odometer") {
    return (
      <CaptureScreen
        kind="odometer"
        title={mode.phase === "start" ? "Odometer at the start" : "Odometer at the end"}
        hint="Line the odometer up in the frame. Avoid glare, and keep the numbers sharp."
        guide
        onCancel={finish}
        onDone={(photo) => {
          // A trip starts where the last one ended, so the vehicle's last reading is filled in; it can only be raised.
          setTyped(mode.phase === "start" && lastKnown > 0 ? String(lastKnown) : "");
          setMode({ kind: "reading", phase: mode.phase, photo });
        }}
      />
    );
  }
  if (mode.kind === "cargo") return <Loading onDone={finish} onCancel={finish} />;
  if (mode.kind === "delivery") return <Delivery onDone={finish} onCancel={finish} />;
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
    const minimum = minimumReading(lastKnown, mode.phase === "end" ? startValue : undefined);
    const tooLow = isBelowMinimum(typed, minimum);
    const submit = () =>
      run(() =>
        mode.phase === "start"
          ? offline.startTrip(mode.photo, value as number)
          : offline.endTrip(mode.photo, value as number),
      );
    return (
      <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ gap: 12 }}>
        <Text style={{ color: t.text, fontSize: 22, fontWeight: "700" }}>Confirm the odometer</Text>
        <Body muted>
          {mode.phase === "start" && lastKnown > 0
            ? `The last reading, ${lastKnown.toLocaleString()} km, is filled in. If the odometer shows more, change it. It cannot be lower.`
            : `Type the number you see on the odometer. It cannot be lower than ${minimum.toLocaleString()} km.`}
        </Body>
        <Input
          label="Odometer (km)"
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
          disabled={value === null || tooLow}
        />
        <Button label="Cancel" kind="secondary" onPress={finish} disabled={busy} />
      </ScrollView>
    );
  }

  const waiting = offline.pending > 0;
  const stateText =
    trip.status === "scheduled"
      ? "Not started"
      : trip.status === "in_progress"
        ? "In progress"
        : trip.status === "delivered"
          ? "Delivered"
          : "Completed";
  return (
    <View style={{ gap: 12 }}>
      <View style={{ padding: 16, borderRadius: 12, backgroundColor: t.surface, gap: 4 }}>
        <Body muted>Today's trip</Body>
        <Text style={{ color: t.text, fontSize: 20, fontWeight: "600" }}>
          {[trip.origin, trip.destination].filter(Boolean).join(" to ") || trip.registration}
        </Text>
        {trip.job && (
          <Body muted>
            Job {trip.job.number} for {trip.job.client_name}
          </Body>
        )}
        {trip.cargo_description && <Body>{trip.cargo_description}</Body>}
        {trip.job?.pickup_at && (
          <Body muted>
            Pickup {formatWhen(trip.job.pickup_at)}
            {trip.job.deliver_by ? `, deliver by ${formatWhen(trip.job.deliver_by)}` : ""}
          </Body>
        )}
        {trip.job?.instructions ? <Body>{trip.job.instructions}</Body> : null}
        {trip.loaded_weight_kg ? (
          <Body muted>Loaded {trip.loaded_weight_kg.toLocaleString()} kg</Body>
        ) : null}
        {trip.overload_kg ? (
          <Text style={{ color: "#d92d20", fontSize: 16, fontWeight: "700" }}>
            Overloaded by {trip.overload_kg.toLocaleString()} kg
          </Text>
        ) : null}
        <Body muted>
          {stateText}
          {trip.start_reading ? `, started at ${trip.start_reading.value.toLocaleString()} km` : ""}
          {trip.distance_km != null ? `, ${trip.distance_km.toLocaleString()} km driven` : ""}
        </Body>
        {waiting && (
          <Body muted>Saved on this phone. It will be sent when there is a connection.</Body>
        )}
      </View>
      <ErrorText message={error} />
      {trip.status === "scheduled" && (
        <>
          {blocked && (
            <Body>
              The inspection found a critical fault. A manager must clear it before you can start.
            </Body>
          )}
          {!status && <Body muted>Do the pre-trip inspection first.</Body>}
          {!trip.loaded_at && (
            <Button
              label="Load and weigh the cargo"
              kind="secondary"
              onPress={() => setMode({ kind: "cargo" })}
            />
          )}
          {cleared ? (
            <Button
              label="Start trip"
              onPress={() => setMode({ kind: "odometer", phase: "start" })}
            />
          ) : (
            <Button
              label={status ? "Redo inspection" : "Pre-trip inspection"}
              onPress={() => setMode({ kind: "inspection" })}
            />
          )}
        </>
      )}
      {trip.status === "in_progress" && (
        <>
          {!trip.loaded_at && (
            <Button
              label="Load and weigh the cargo"
              kind="secondary"
              onPress={() => setMode({ kind: "cargo" })}
            />
          )}
          <Button
            label="Mark delivered"
            kind="secondary"
            onPress={() =>
              trip.job ? setMode({ kind: "delivery" }) : void run(() => offline.markDelivered())
            }
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
