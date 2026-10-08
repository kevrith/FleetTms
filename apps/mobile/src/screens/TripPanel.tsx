import {
  isBelowMinimum,
  minimumReading,
  nairobiDay,
  odometerProblem,
  parseOdometer,
} from "@fleettms/business-rules";
import { useState } from "react";
import { ScrollView, Text, View } from "react-native";
import { api } from "../api";
import { CaptureScreen } from "../capture";
import type { LocalPhoto } from "../offline/types";
import { useOffline } from "../offline/runtime";
import { Body, Button, ErrorText, errorMessage, Input, useTheme } from "../ui";
import Delivery from "./Delivery";
import InspectionFlow from "./InspectionFlow";
import Loading from "./Loading";
import { useTrackingStatus } from "../tracking/status";

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

/**
 * For a driver nobody has made a trip for: say where from and where to, and the trip is made on the vehicle they are assigned to. It
 * needs a connection (the trip is made on the server); the usual steps follow, starting with the inspection.
 */
function NewTrip({ onMade }: { onMade: () => Promise<unknown> }) {
  const [open, setOpen] = useState(false);
  const [origin, setOrigin] = useState("");
  const [destination, setDestination] = useState("");
  const [cargo, setCargo] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function make() {
    setBusy(true);
    setError(null);
    try {
      await api.startMyTrip({
        origin: origin.trim(),
        destination: destination.trim(),
        cargo_description: cargo.trim() || null,
      });
      await onMade();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  if (!open) return <Button label="Start a new trip" onPress={() => setOpen(true)} />;
  return (
    <View style={{ gap: 8 }}>
      <Input label="From" value={origin} onChangeText={setOrigin} placeholder="Mombasa" />
      <Input label="To" value={destination} onChangeText={setDestination} placeholder="Nairobi" />
      <Input
        label="What are you carrying? (optional)"
        value={cargo}
        onChangeText={setCargo}
        placeholder="Cement, 400 bags"
      />
      <Body muted>Needs an internet connection.</Body>
      <ErrorText message={error} />
      <Button
        label="Make the trip"
        onPress={make}
        busy={busy}
        disabled={origin.trim().length < 2 || destination.trim().length < 2}
      />
      <Button label="Cancel" kind="secondary" onPress={() => setOpen(false)} disabled={busy} />
    </View>
  );
}

export default function TripPanel() {
  const t = useTheme();
  const offline = useOffline();
  const { trip, vehicle, inspection } = offline.state.cache;
  const [mode, setMode] = useState<Mode>({ kind: "idle" });
  const [typed, setTyped] = useState("");
  const [suggested, setSuggested] = useState<number | null>(null); // what the server read from the photo, if it could
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const finish = () => {
    setMode({ kind: "idle" });
    setTyped("");
    setSuggested(null);
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
        {vehicle ? (
          <NewTrip onMade={() => offline.syncNow()} />
        ) : (
          <Body muted>Ask your employer to put you on a vehicle, then you can start a trip.</Body>
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
          const initial = mode.phase === "start" && lastKnown > 0 ? String(lastKnown) : "";
          setTyped(initial);
          setSuggested(null);
          setMode({ kind: "reading", phase: mode.phase, photo });
          // With a connection, the server reads the photo and offers the number. It only fills the box if the driver has not typed anything, and
          // the driver still confirms it; with no connection nothing changes.
          void offline
            .suggestOdometer(photo)
            .then((value) => {
              if (value === null) return;
              setSuggested(value);
              setTyped((current) => (current === initial ? String(value) : current));
            })
            .catch(() => undefined);
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
        {suggested !== null && typed === String(suggested) && (
          <Body muted>Read from the photo. Check it matches what the odometer shows.</Body>
        )}
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
      {(trip.status === "in_progress" || trip.status === "delivered") && <TrackingNotice />}
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

const PROBLEMS: Record<string, string> = {
  denied:
    "Location is switched off for FleetTms, so the office cannot see this trip. Turn it on in the phone's settings.",
  background_denied:
    'FleetTms needs location set to "Allow all the time" so tracking keeps working with the screen off. Change it in the phone\'s settings.',
  failed: "Location tracking could not start. Restart the app.",
};

/** Tells the driver, plainly, whether their location is being shared right now. */
function TrackingNotice() {
  const t = useTheme();
  const s = useTrackingStatus();
  const bad = s.problem !== null;
  return (
    <View
      style={{
        padding: 12,
        borderRadius: 12,
        backgroundColor: t.surface,
        borderLeftWidth: 6,
        borderLeftColor: bad ? "#dc2626" : s.on ? "#16a34a" : "#94a3b8",
        gap: 2,
      }}
    >
      <Text style={{ color: t.text, fontWeight: "700" }}>
        {bad ? "Location is off" : s.on ? "Location is on" : "Location is starting"}
      </Text>
      <Body muted>
        {bad
          ? PROBLEMS[s.problem!]
          : "Your phone shares its position with your employer until you end the trip. It stops by itself then."}
        {s.waiting > 0 && !bad ? ` ${s.waiting} waiting to send.` : ""}
      </Body>
    </View>
  );
}
