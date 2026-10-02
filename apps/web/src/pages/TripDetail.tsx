import type { Inspection, Invoice, OdometerReadingOut, PhotoKind, Trip } from "@fleettms/types";
import { odometerProblem, parseOdometer } from "@fleettms/business-rules";
import { Camera, CheckCircle2, Flag, PackageCheck, Play, Square } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { FLAG_TEXT, fmtTime, kes, POD_FLAG, TRIP_STATUS } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";
import InspectionCard from "./InspectionCard";

function Reading({ title, r }: { title: string; r: OdometerReadingOut | null }) {
  if (!r) return null;
  return (
    <div>
      <h4>{title}</h4>
      <p>
        <strong>{r.value.toLocaleString()} km</strong>{" "}
        <span className="muted">{fmtTime(r.recorded_at)}</span>
      </p>
      {r.flags.map((f) => (
        <p key={f} className="status warn">
          <Flag size={16} /> {FLAG_TEXT[f] ?? f}
        </p>
      ))}
      {r.photo && (
        <a href={api.mediaUrl(r.photo.url)} target="_blank" rel="noreferrer">
          <img src={api.mediaUrl(r.photo.url)} alt={`${title} odometer photo`} width={260} />
        </a>
      )}
      {r.photo && (
        <p className="muted">
          Photo taken {fmtTime(r.photo.captured_at)}
          {r.photo.lat != null && r.photo.lng != null
            ? ` at ${r.photo.lat.toFixed(4)}, ${r.photo.lng.toFixed(4)}`
            : ", no GPS location"}
          {r.photo.source === "web" ? ", uploaded from the web" : ""}
        </p>
      )}
    </div>
  );
}

/** Picks a photo, uploads it, and returns its id. The browser's own metadata decides whether it is fresh enough. */
async function uploadFresh(file: File, kind: PhotoKind): Promise<string> {
  const photo = await api.uploadPhoto(file, { kind, source: "web" });
  return photo.id;
}

function CapturePanel({
  trip,
  today,
  vehicleKm,
  onChanged,
}: {
  trip: Trip;
  today: boolean;
  vehicleKm: number | null;
  onChanged: () => Promise<void>;
}) {
  const { can } = useAuth();
  const [file, setFile] = useState<File | null>(null);
  const [value, setValue] = useState("");
  const [weight, setWeight] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const startValue = trip.start_reading?.value;
  const phase = trip.status === "scheduled" ? "start" : trip.status === "completed" ? null : "end";

  // A trip starts where the last one ended, so the vehicle's last reading is filled in once. It can only be raised.
  const prefilled = useRef(false);
  useEffect(() => {
    if (phase === "start" && vehicleKm && !prefilled.current) {
      prefilled.current = true;
      setValue(String(vehicleKm));
    }
  }, [phase, vehicleKm]);

  if (!can("trips.manage")) return null;

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      setFile(null);
      setValue("");
      setWeight("");
      await onChanged();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  // The start reading is compared with the vehicle's last reading; the end reading with this trip's start.
  const lastKnown = phase === "end" ? (startValue ?? 0) : vehicleKm;
  const problem =
    value && lastKnown !== null ? odometerProblem(value, lastKnown, startValue) : null;
  const readingReady = file && parseOdometer(value) !== null && !problem;

  const submitReading = () =>
    run(async () => {
      const photoId = await uploadFresh(file as File, "odometer");
      const reading = { photo_id: photoId, value: parseOdometer(value) as number };
      if (phase === "start") await api.startTrip(trip.id, reading);
      else await api.endTrip(trip.id, reading);
    });

  if (trip.status === "cancelled" || trip.status === "completed") return null;
  return (
    <Card title="Record from the web">
      <p className="muted">
        For when the driver cannot. The photo must be taken with a phone camera in the last 10
        minutes; its own capture time is checked.
      </p>
      <ErrorBanner message={error} />
      {phase === "start" && !today && (
        <p className="status warn">Today's inspection must pass before the trip can start.</p>
      )}
      <div className="form-grid">
        <Field label={`Odometer photo (${phase})`}>
          <input
            type="file"
            accept="image/*"
            capture="environment"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </Field>
        <Field label={`Odometer ${phase} reading (km)`}>
          <input value={value} onChange={(e) => setValue(e.target.value)} inputMode="numeric" />
        </Field>
        <button className="btn primary" disabled={!readingReady || busy} onClick={submitReading}>
          {phase === "start" ? <Play size={16} /> : <Square size={16} />}{" "}
          {phase === "start" ? "Start trip" : "End trip"}
        </button>
      </div>
      {problem && <p className="status warn">{problem}</p>}
      {trip.status === "in_progress" && (
        <div className="form-grid">
          <Field label="Cargo photo">
            <input
              type="file"
              accept="image/*"
              capture="environment"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </Field>
          <Field label="Loaded weight (kg, optional)">
            <input value={weight} onChange={(e) => setWeight(e.target.value)} inputMode="numeric" />
          </Field>
          <button
            className="btn"
            disabled={!file || busy}
            onClick={() =>
              run(async () => {
                const id = await uploadFresh(file as File, "cargo");
                await api.recordLoading(trip.id, id, weight ? Number(weight) : null);
              })
            }
          >
            <Camera size={16} /> Record loading
          </button>
          <button
            className="btn"
            disabled={busy}
            onClick={() => run(() => api.deliverTrip(trip.id))}
          >
            <PackageCheck size={16} /> Mark delivered
          </button>
        </div>
      )}
      {trip.status === "scheduled" && (
        <p>
          <button
            className="btn danger"
            disabled={busy}
            onClick={() => run(() => api.cancelTrip(trip.id))}
          >
            Cancel trip
          </button>
        </p>
      )}
    </Card>
  );
}

function Photo({
  photo,
  title,
}: {
  photo: { url: string; captured_at: string } | null | undefined;
  title: string;
}) {
  if (!photo) return null;
  return (
    <figure style={{ margin: 8, display: "inline-block" }}>
      <a href={api.mediaUrl(photo.url)} target="_blank" rel="noreferrer">
        <img src={api.mediaUrl(photo.url)} alt={title} width={220} />
      </a>
      <figcaption className="muted">{title}</figcaption>
    </figure>
  );
}

function Delivery({ trip, onChanged }: { trip: Trip; onChanged: () => void }) {
  const { can } = useAuth();
  const [invoice, setInvoice] = useState<Invoice | null>(null);
  const [weight, setWeight] = useState("");
  const [error, setError] = useState<string | null>(null);
  const loadInvoice = useCallback(async () => {
    try {
      setInvoice((await api.tripInvoice(trip.id)).invoice);
    } catch {
      setInvoice(null);
    }
  }, [trip.id]);
  useEffect(() => {
    void loadInvoice();
  }, [loadInvoice, trip.status]);
  const pod = trip.pod;
  const delivered = trip.status === "delivered" || trip.status === "completed";
  if (!pod && !delivered && !trip.overload_kg && !trip.weighbridge_photo) return null;
  return (
    <>
      {trip.overload_kg != null && trip.overload_kg > 0 && (
        <p className="banner bad" role="alert">
          <Flag size={18} /> Loaded {trip.overload_kg.toLocaleString()} kg over the legal limit.
        </p>
      )}
      {(pod || trip.weighbridge_photo) && (
        <Card title="Proof of delivery">
          <ErrorBanner message={error} />
          {trip.weighbridge_photo && (
            <>
              <h4>Weighbridge ticket</h4>
              <Photo photo={trip.weighbridge_photo} title="Weighbridge ticket" />
              <p className="muted">
                {trip.loaded_weight_kg
                  ? `${trip.loaded_weight_kg.toLocaleString()} kg of cargo`
                  : ""}
                {trip.overload_kg === 0 ? ", within the legal limit" : ""}
              </p>
            </>
          )}
          {pod && (
            <>
              <p>
                Received by <strong>{pod.recipient_name}</strong>, {fmtTime(pod.captured_at)}.
                Confirmed by{" "}
                {pod.method === "code" ? "a one-time code sent to the client's phone" : "signature"}
                .
              </p>
              {pod.lat != null && pod.lng != null && (
                <p>
                  <a
                    href={`https://maps.google.com/?q=${pod.lat},${pod.lng}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Where it was delivered
                  </a>
                </p>
              )}
              {pod.flags.map((f) => (
                <p key={f} className="status warn">
                  <Flag size={16} /> {POD_FLAG[f] ?? f}
                </p>
              ))}
              {pod.shortage_qty != null && (
                <p>
                  Shortage: {pod.shortage_qty} {pod.shortage_unit}
                </p>
              )}
              {pod.damage_notes && <p>Damage: {pod.damage_notes}</p>}
              <Photo photo={pod.note_photo} title="Signed delivery note" />
              <Photo photo={pod.cargo_photo} title="Cargo delivered" />
              {pod.damage_photos.map((p) => (
                <Photo key={p.id} photo={p} title="Damage" />
              ))}
            </>
          )}
        </Card>
      )}
      {delivered && can("invoices.manage") && (
        <Card title="Invoice">
          <ErrorBanner message={error} />
          {invoice ? (
            <p>
              <Link to={`/clients/invoices/${invoice.id}`}>{invoice.number}</Link>:{" "}
              {kes(invoice.total_cents)}, {invoice.status.replace("_", " ")}.
            </p>
          ) : (
            <>
              <p className="muted">
                No invoice yet. A per-tonne trip is billed from the weighbridge weight; if the
                ticket was not recorded, enter the weight from the paper ticket.
              </p>
              <div className="form-grid">
                <Field label="Weight (kg)">
                  <input
                    type="number"
                    min="0"
                    value={weight}
                    onChange={(e) => setWeight(e.target.value)}
                  />
                </Field>
                <button
                  className="btn primary"
                  onClick={async () => {
                    setError(null);
                    try {
                      await api.invoiceTrip(trip.id, weight ? Number(weight) : undefined);
                      await loadInvoice();
                      onChanged();
                    } catch (e) {
                      setError(errorMessage(e));
                    }
                  }}
                >
                  Invoice this trip
                </button>
              </div>
            </>
          )}
        </Card>
      )}
    </>
  );
}

export default function TripDetail() {
  const { id = "" } = useParams();
  const [trip, setTrip] = useState<Trip | null>(null);
  const [inspection, setInspection] = useState<Inspection | null>(null);
  const [todayOk, setTodayOk] = useState(false);
  const [vehicleKm, setVehicleKm] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const t = await api.trip(id);
      setTrip(t);
      setVehicleKm((await api.vehicle(t.vehicle_id).catch(() => null))?.odometer_km ?? null);
      const today = await api.inspectionToday(t.vehicle_id).catch(() => null);
      setTodayOk(today?.can_start_trip ?? false);
      if (today?.inspection) setInspection(today.inspection);
      else if (t.inspection) {
        const all = await api.inspections(t.vehicle_id).catch(() => []);
        setInspection(all.find((i) => i.id === t.inspection?.id) ?? null);
      } else setInspection(null);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [id]);
  useEffect(() => {
    void load();
  }, [load]);

  if (!trip) return error ? <ErrorBanner message={error} /> : <p>Loading...</p>;
  return (
    <>
      <p>
        <Link to="/trips">Back to trips</Link>
      </p>
      <h2>
        {trip.registration} <span className="muted">{TRIP_STATUS[trip.status]}</span>
      </h2>
      <ErrorBanner message={error} />
      <Card title="Trip">
        <p>
          {[trip.origin, trip.destination].filter(Boolean).join(" to ") || "No route set"}
          {trip.cargo_description ? `, ${trip.cargo_description}` : ""}
        </p>
        <p className="muted">
          Started {fmtTime(trip.started_at) || "not yet"}
          {trip.ended_at ? `, ended ${fmtTime(trip.ended_at)}` : ""}
        </p>
        {trip.distance_km != null && (
          <p className="status ok">
            <CheckCircle2 size={16} /> {trip.distance_km.toLocaleString()} km driven (end reading
            minus start reading)
          </p>
        )}
      </Card>
      <Card title="Pre-trip inspection">
        {inspection ? (
          <InspectionCard inspection={inspection} onChanged={load} />
        ) : (
          <p className="muted">No inspection has been done for this vehicle today.</p>
        )}
      </Card>
      <Card title="Odometer">
        <Reading title="Start" r={trip.start_reading} />
        <Reading title="End" r={trip.end_reading} />
        {!trip.start_reading && <p className="muted">Recorded when the driver starts the trip.</p>}
      </Card>
      {trip.cargo_photo && (
        <Card title="Loading">
          <a href={api.mediaUrl(trip.cargo_photo.url)} target="_blank" rel="noreferrer">
            <img src={api.mediaUrl(trip.cargo_photo.url)} alt="Cargo photo" width={260} />
          </a>
          <p className="muted">
            Loaded {fmtTime(trip.loaded_at)}
            {trip.loaded_weight_kg ? `, ${trip.loaded_weight_kg.toLocaleString()} kg` : ""}
          </p>
        </Card>
      )}
      <Delivery trip={trip} onChanged={load} />
      <CapturePanel trip={trip} today={todayOk} vehicleKm={vehicleKm} onChanged={load} />
    </>
  );
}
