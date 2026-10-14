import {
  formatKes,
  insideShape,
  isBelowMinimum,
  minimumReading,
  nairobiDay,
  odometerProblem,
  parseOdometer,
} from "@fleettms/business-rules";
import { useEffect, useState } from "react";
import { Linking, Platform, ScrollView, Text, View } from "react-native";
import { api } from "../api";
import { useAuth } from "../auth";
import { CaptureScreen } from "../capture";
import type { LocalPhoto } from "../offline/types";
import { useOffline } from "../offline/runtime";
import { Body, Button, ErrorText, errorMessage, Input, useTheme } from "../ui";
import { ClientPicker, hasClient, noClient, type ClientChoice } from "./ClientPicker";
import Delivery from "./Delivery";
import InspectionFlow from "./InspectionFlow";
import Loading from "./Loading";
import RenewLicence from "./RenewLicence";
import { SaveSiteChoice, siteToSave, useSaveSite } from "./SaveSite";
import { useTrackingStatus } from "../tracking/status";
import { currentPlace } from "./Delivery";
import type { Trip, TripSite } from "@fleettms/types";

type Mode =
  | { kind: "idle" }
  | { kind: "inspection" }
  | { kind: "odometer"; phase: "start" | "end" }
  | { kind: "reading"; phase: "start" | "end"; photo: LocalPhoto }
  | { kind: "cargo" }
  | { kind: "delivery" }
  | { kind: "place" }
  | { kind: "renew" };

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
  const { me } = useAuth();
  // Only the owner or a manager says what a trip pays; for a hired driver the fields are not offered.
  const canPrice = me?.permissions.includes("jobs.manage") ?? false;
  const [open, setOpen] = useState(false);
  const [origin, setOrigin] = useState("");
  const [destination, setDestination] = useState("");
  const [cargo, setCargo] = useState("");
  const [client, setClient] = useState<ClientChoice>(noClient);
  const [price, setPrice] = useState("");
  const priceCents = Math.round(Number(price) * 100);
  // A price needs someone to pay it.
  const halfPriced = canPrice && price.trim().length > 0 && !hasClient(client);
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
        ...(client.clientId
          ? { client_id: client.clientId, ...(client.siteId ? { site_id: client.siteId } : {}) }
          : client.newName
            ? { new_client_name: client.newName }
            : {}),
        ...(canPrice && hasClient(client) && priceCents > 0 ? { price_cents: priceCents } : {}),
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
      <ClientPicker value={client} onChange={setClient} />
      {canPrice && (
        <>
          <Input
            label="What the trip pays, in KES (optional)"
            value={price}
            onChangeText={setPrice}
            keyboardType="decimal-pad"
            placeholder="12000"
          />
          {halfPriced && <Body muted>Choose who is paying, or leave the price out.</Body>}
        </>
      )}
      <Body muted>Needs an internet connection.</Body>
      <ErrorText message={error} />
      <Button
        label="Make the trip"
        onPress={make}
        busy={busy}
        disabled={
          origin.trim().length < 2 ||
          destination.trim().length < 2 ||
          halfPriced ||
          (canPrice && price.trim().length > 0 && !(priceCents > 0))
        }
      />
      <Button label="Cancel" kind="secondary" onPress={() => setOpen(false)} disabled={busy} />
    </View>
  );
}

/** True when the trip has delivered, a depot is mapped, and the phone is somewhere else (an unknown position counts as not away). */
async function notAtDepot(trip: Trip | null): Promise<boolean> {
  if (!trip?.delivered_at || !trip.depots?.length) return false;
  const where = await currentPlace();
  if (!where) return false;
  return !trip.depots.some((d) => insideShape(d.shape, where.lat, where.lng));
}

/**
 * After the delivery: where the lorry goes home to, and "you are back" when the phone is inside a depot. Only a reminder: the trip is
 * ended with the closing odometer photo, and nothing here ends it by itself.
 */
function ReturnNotice({ trip }: { trip: Trip }) {
  const depots = trip.depots ?? [];
  const [here, setHere] = useState<string | null>(null);
  useEffect(() => {
    if (depots.length === 0) return;
    let live = true;
    const look = async () => {
      const where = await currentPlace();
      if (!live) return;
      const found = where ? depots.find((d) => insideShape(d.shape, where.lat, where.lng)) : null;
      setHere(found ? found.name : null);
    };
    void look();
    const timer = setInterval(() => void look(), 30_000);
    return () => {
      live = false;
      clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trip.id, depots.length]);
  if (depots.length === 0) return null;
  return here ? (
    <Body>You are at {here}. Park, then end the trip with the closing odometer photo.</Body>
  ) : (
    <Body muted>
      Delivered. Take the lorry back to {depots.map((d) => d.name).join(" or ")}, then end the trip
      with the closing odometer photo.
    </Body>
  );
}

/** A map link for the place: the maps app opens with a pin on it. */
const mapsUrl = (s: TripSite) =>
  Platform.OS === "ios"
    ? `maps:?q=${encodeURIComponent(s.name ?? "Delivery")}&ll=${s.lat},${s.lng}`
    : `geo:${s.lat},${s.lng}?q=${s.lat},${s.lng}(${encodeURIComponent(s.name ?? "Delivery")})`;

/**
 * A trip for a client with no proof of delivery to take: asks whether to save this place as the client's delivery site, then marks it
 * delivered. Saved on the phone and sent when there is a network.
 */
function PlacePrompt({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const t = useTheme();
  const offline = useOffline();
  const trip = offline.state.cache.trip;
  const saveSite = useSaveSite(trip);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      const where = saveSite.offered && saveSite.save ? await currentPlace() : null;
      await offline.markDelivered(siteToSave(saveSite, where));
      onDone();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ gap: 12 }}>
      <Text style={{ color: t.text, fontSize: 22, fontWeight: "700" }}>Mark delivered</Text>
      {trip?.client ? <Body muted>Delivery for {trip.client.name}</Body> : null}
      <SaveSiteChoice trip={trip} state={saveSite} />
      <ErrorText message={error} />
      <Button label="Mark delivered" onPress={confirm} busy={busy} disabled={!saveSite.valid} />
      <Button label="Cancel" kind="secondary" onPress={onCancel} disabled={busy} />
    </ScrollView>
  );
}

/**
 * For the owner who drives: once the load is delivered, say what was paid (cash or M-Pesa), so profit has this trip's income without an
 * invoice. A hired driver never sees this. It needs a connection.
 */
function ReceivedCard({ tripId }: { tripId: string }) {
  const t = useTheme();
  const [amount, setAmount] = useState("");
  const [saved, setSaved] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .trip(tripId)
      .then((trip) => {
        if (trip.received_cents != null) {
          setSaved(trip.received_cents);
          setAmount(String(trip.received_cents / 100));
        }
      })
      .catch(() => undefined);
  }, [tripId]);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const cents = Math.round(Number(amount) * 100);
      await api.setTripReceived(tripId, cents);
      setSaved(cents);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const cents = Math.round(Number(amount) * 100);
  return (
    <View style={{ padding: 16, borderRadius: 12, backgroundColor: t.surface, gap: 8 }}>
      <Body muted>How much were you paid for this trip?</Body>
      <Input
        label="Amount received (KES)"
        value={amount}
        onChangeText={setAmount}
        keyboardType="decimal-pad"
        placeholder="12000"
      />
      {saved !== null && <Body muted>Recorded: {formatKes(saved)}</Body>}
      <ErrorText message={error} />
      <Button
        label={saved === null ? "Save what I was paid" : "Update"}
        onPress={save}
        busy={busy}
        disabled={amount.trim() === "" || !(cents >= 0)}
      />
    </View>
  );
}

export default function TripPanel() {
  const t = useTheme();
  const { me } = useAuth();
  const offline = useOffline();
  const { trip, vehicle, inspection } = offline.state.cache;
  const [mode, setMode] = useState<Mode>({ kind: "idle" });
  const [typed, setTyped] = useState("");
  const [suggested, setSuggested] = useState<number | null>(null); // what the server read from the photo, if it could
  const [away, setAway] = useState(false); // ending a delivered trip away from the depot: the driver may say why
  const [awayReason, setAwayReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const finish = () => {
    setMode({ kind: "idle" });
    setTyped("");
    setSuggested(null);
    setAway(false);
    setAwayReason("");
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

  // A lorry that takes its distance from GPS has a dial that proves nothing, so the reading is not compared with anything.
  const gpsVehicle = vehicle?.vehicle.distance_source === "gps";
  const lastKnown = gpsVehicle ? 0 : (vehicle?.vehicle.odometer_km ?? 0);
  const today =
    inspection &&
    inspection.vehicleId === trip.vehicle_id &&
    inspection.day === nairobiDay(new Date());
  const status = today ? inspection.status : null;
  const blocked = status === "blocked";
  // The server decides when the trip starts; this only saves the driver doing the odometer photo first. It is as old as the last sync.
  const stoppedByDocuments = !!trip.compliance?.blocked && !trip.compliance_override;
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
          setAway(false);
          if (mode.phase === "end") void notAtDepot(trip).then(setAway);
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
  if (mode.kind === "renew") return <RenewLicence onDone={finish} onCancel={finish} />;
  if (mode.kind === "cargo") return <Loading onDone={finish} onCancel={finish} />;
  if (mode.kind === "delivery") return <Delivery onDone={finish} onCancel={finish} />;
  if (mode.kind === "place") return <PlacePrompt onDone={finish} onCancel={finish} />;
  if (mode.kind === "reading") {
    const startValue = trip.start_reading?.value;
    const problem = typed
      ? odometerProblem(
          typed,
          mode.phase === "start" || gpsVehicle ? lastKnown : (startValue ?? lastKnown),
          mode.phase === "end" && !gpsVehicle ? startValue : undefined,
        )
      : null;
    const value = parseOdometer(typed);
    const minimum = minimumReading(
      lastKnown,
      mode.phase === "end" && !gpsVehicle ? startValue : undefined,
    );
    const tooLow = isBelowMinimum(typed, minimum);
    const submit = () =>
      run(() =>
        mode.phase === "start"
          ? offline.startTrip(mode.photo, value as number)
          : offline.endTrip(mode.photo, value as number, away ? awayReason : null),
      );
    return (
      <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ gap: 12 }}>
        <Text style={{ color: t.text, fontSize: 22, fontWeight: "700" }}>Confirm the odometer</Text>
        <Body muted>
          {gpsVehicle
            ? "Type the number you see on the odometer, even if it is stuck or wrong. This lorry's distance is worked out from the phone's GPS."
            : mode.phase === "start" && lastKnown > 0
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
        {mode.phase === "end" && away && (
          <>
            <Body muted>
              You are not at the depot. You can still end the trip. If you like, say why, so the
              office knows.
            </Body>
            <Input
              label="Why is the lorry not at the depot? (optional)"
              value={awayReason}
              onChangeText={setAwayReason}
              placeholder="Waiting to offload, breakdown, slept at the client"
              maxLength={200}
            />
          </>
        )}
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
        {trip.job ? (
          <Body muted>
            Job {trip.job.number} for {trip.job.client_name}
          </Body>
        ) : trip.client ? (
          <Body muted>For {trip.client.name}</Body>
        ) : null}
        {trip.site && trip.status !== "completed" ? (
          <>
            <Body>
              Deliver to {trip.site.name ?? "the client's place"}
              {trip.site.status === "unconfirmed" ? " (saved by a driver)" : ""}
            </Body>
            <Button
              label="Open in maps"
              kind="secondary"
              onPress={() => void Linking.openURL(mapsUrl(trip.site as TripSite))}
            />
          </>
        ) : null}
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
          {trip.loaded_km != null && trip.empty_km != null
            ? ` (${trip.loaded_km.toLocaleString()} km loaded, ${trip.empty_km.toLocaleString()} km empty on the way back)`
            : ""}
        </Body>
        {trip.status === "delivered" && <ReturnNotice trip={trip} />}
        {waiting && (
          <Body muted>Saved on this phone. It will be sent when there is a connection.</Body>
        )}
      </View>
      <ErrorText message={error} />
      {trip.status === "scheduled" && (
        <>
          {trip.compliance?.issues.map((i) => (
            <Body key={`${i.doc_type}-${i.subject}`} muted={!i.blocking}>
              {i.text}
            </Body>
          ))}
          {stoppedByDocuments && (
            <Body>
              This trip cannot start until the date is updated, or the owner allows it. Tell your
              employer.
            </Body>
          )}
          {trip.compliance?.issues.some(
            (i) => i.subject === "driver" && i.status !== "ends_during_trip",
          ) && (
            <Button
              label="Send my licence renewal"
              kind="secondary"
              onPress={() => setMode({ kind: "renew" })}
            />
          )}
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
              disabled={stoppedByDocuments}
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
              trip.job
                ? setMode({ kind: "delivery" })
                : trip.client && !trip.site
                  ? setMode({ kind: "place" })
                  : void run(() => offline.markDelivered())
            }
            busy={busy}
          />
          <Button label="End trip" onPress={() => setMode({ kind: "odometer", phase: "end" })} />
        </>
      )}
      {trip.status === "delivered" && (
        <>
          {me?.roles.includes("owner") && <ReceivedCard tripId={trip.id} />}
          <Button label="End trip" onPress={() => setMode({ kind: "odometer", phase: "end" })} />
        </>
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
      {Platform.OS === "android" && (
        <>
          <Body muted>
            Many phones (Tecno, Infinix, Xiaomi, Samsung) stop apps that run with the screen off to
            save battery. In the phone's settings, set Battery for FleetTms to "Unrestricted" so the
            whole trip is recorded.
          </Body>
          <Button
            label="Open phone settings"
            kind="secondary"
            onPress={() => void Linking.openSettings()}
          />
        </>
      )}
    </View>
  );
}
