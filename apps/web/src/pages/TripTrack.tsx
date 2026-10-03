import type { TrackingLinkRow, Trip, TripTrack } from "@fleettms/types";
import { Link2, MapPinned, Send } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { MapView } from "../MapView";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

const CHECK: Record<string, string> = {
  ok: "The odometer and the GPS agree.",
  mismatch: "The odometer and the GPS disagree by more than they should. One of them is wrong.",
  no_gps: "Not enough GPS fixes to check the odometer.",
};

const SOURCE: Record<string, string> = {
  odometer: "Odometer",
  phone: "Phone GPS",
  tracker: "Tracker",
};

/** The path the lorry took, what the GPS says it drove, and the link a client can follow it on. */
export function TripTrackCard({ trip }: { trip: Trip }) {
  const { can } = useAuth();
  const [track, setTrack] = useState<TripTrack | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!can("livemap.view") || !trip.started_at) return;
    api
      .tripTrack(trip.id)
      .then(setTrack)
      .catch((e) => setError(errorMessage(e)));
  }, [trip.id, trip.started_at, trip.ended_at, can]);
  const line = useMemo(
    () => (track ? [{ points: track.points.map((p) => [p.lat, p.lng] as [number, number]) }] : []),
    [track],
  );
  const last = track?.points[track.points.length - 1];
  const markers = useMemo(
    () =>
      last
        ? [
            {
              id: "last",
              lat: last.lat,
              lng: last.lng,
              colour: trip.ended_at ? "#475569" : "#16a34a",
              label: trip.ended_at ? "Where it ended" : "Last position",
              big: true,
            },
          ]
        : [],
    [last, trip.ended_at],
  );
  if (!can("livemap.view") || !trip.started_at) return null;
  return (
    <Card title="Where it went">
      <ErrorBanner message={error} />
      {track && track.fixes === 0 && (
        <p className="muted">The phone has not reported any locations for this trip.</p>
      )}
      {track && track.fixes > 0 && (
        <>
          <MapView markers={markers} lines={line} height={320} />
          <p className="muted">
            {track.fixes.toLocaleString()} locations. GPS distance{" "}
            {track.gps_distance_km != null
              ? `${track.gps_distance_km.toLocaleString()} km`
              : "not worked out yet"}
            {track.odometer_distance_km != null
              ? `, odometer ${track.odometer_distance_km.toLocaleString()} km`
              : ""}
            .
          </p>
        </>
      )}
      {trip.distance_detail && Object.keys(trip.distance_detail.sources).length > 1 && (
        <p className="muted">
          {Object.entries(trip.distance_detail.sources)
            .map(([name, km]) => `${SOURCE[name] ?? name} ${km.toLocaleString()} km`)
            .join(", ")}
          .{" "}
          {trip.distance_detail.suspect &&
            `The ${SOURCE[trip.distance_detail.suspect]?.toLowerCase()} is the one that disagrees with the other two.`}
        </p>
      )}
      {track?.distance_check && (
        <p
          className={`status ${track.distance_check === "ok" ? "ok" : track.distance_check === "mismatch" ? "bad" : ""}`}
        >
          {CHECK[track.distance_check]}
        </p>
      )}
    </Card>
  );
}

/** Make a link for the client to follow this delivery, optionally texted to them; switch old ones off. */
export function TrackingLinksCard({ trip }: { trip: Trip }) {
  const { can } = useAuth();
  const [links, setLinks] = useState<TrackingLinkRow[]>([]);
  const [phone, setPhone] = useState("");
  const [fresh, setFresh] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const allowed = can("trips.manage") || can("jobs.manage");
  const open = trip.status === "scheduled" || trip.status === "in_progress";
  const load = useCallback(async () => {
    if (!allowed) return;
    try {
      setLinks(await api.trackingLinks(trip.id));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [trip.id, allowed]);
  useEffect(() => {
    void load();
  }, [load]);
  if (!allowed) return null;
  async function make(send: boolean) {
    setError(null);
    setMessage(null);
    try {
      const made = await api.createTrackingLink(trip.id, {
        send_sms: send,
        phone: send && phone ? phone : null,
      });
      setFresh(made.url ?? null);
      setMessage(
        send
          ? `Link texted to ${made.sent_to}.`
          : "Link made. Copy it below; it is shown only now.",
      );
      await load();
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  return (
    <Card title="Client tracking link">
      <ErrorBanner message={error} />
      {message && <p className="banner ok">{message}</p>}
      <p className="muted">
        The client sees where the lorry is and when it should arrive, and nothing else: no driver,
        no other trips. The link stops working when the delivery is made.
      </p>
      {open ? (
        <div className="form-grid">
          <Field label="Text it to (blank: the client's number)">
            <input value={phone} onChange={(e) => setPhone(e.target.value)} inputMode="tel" />
          </Field>
          <button className="btn" onClick={() => make(false)}>
            <Link2 size={16} /> Make a link
          </button>
          <button className="btn primary" onClick={() => make(true)}>
            <Send size={16} /> Make and text it
          </button>
        </div>
      ) : (
        <p className="muted">This delivery has been made, so there is nothing left to follow.</p>
      )}
      {fresh && (
        <p>
          <MapPinned size={16} />{" "}
          <input
            readOnly
            value={fresh}
            style={{ width: "100%" }}
            onFocus={(e) => e.target.select()}
          />
        </p>
      )}
      <ul className="list">
        {links.map((l) => (
          <li key={l.id}>
            <span>
              Made {new Date(l.created_at).toLocaleString("en-KE")}, {l.views} view
              {l.views === 1 ? "" : "s"}
              {l.sent_to ? `, texted to ${l.sent_to}` : ""}
            </span>
            <span>
              {l.state === "active" ? (
                <button
                  className="btn danger"
                  onClick={async () => {
                    await api.revokeTrackingLink(l.id);
                    await load();
                  }}
                >
                  Switch off
                </button>
              ) : (
                l.state
              )}
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}
