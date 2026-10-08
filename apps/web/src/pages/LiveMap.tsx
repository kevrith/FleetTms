import type { LiveMap as LiveMapData, MapVehicle, TripTrack } from "@fleettms/types";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { MapView } from "../MapView";
import { Card, ErrorBanner, errorMessage } from "../ui";

const SOS_SUFFIX = ":sos";

const STATE_LABEL: Record<string, string> = {
  moving: "Moving",
  idle: "Standing on a trip",
  offline: "Not reporting",
  parked: "Parked",
  unknown: "Never seen",
};
const STATE_COLOUR: Record<string, string> = {
  moving: "#16a34a",
  idle: "#d97706",
  offline: "#dc2626",
  parked: "#475569",
  unknown: "#94a3b8",
};

export function ago(seconds: number | null): string {
  if (seconds === null) return "";
  if (seconds < 90) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} days ago`;
}

/** Where every lorry is: moving, standing on a trip, not reporting, or parked. Refreshes by itself. */
export default function LiveMap() {
  const [data, setData] = useState<LiveMapData | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [track, setTrack] = useState<TripTrack | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setData(await api.liveMap());
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => {
    void load();
    const timer = setInterval(load, 15000);
    return () => clearInterval(timer);
  }, [load]);

  const chosen: MapVehicle | undefined = data?.vehicles.find((v) => v.vehicle_id === selected);
  useEffect(() => {
    setTrack(null);
    if (chosen?.trip) {
      api
        .tripTrack(chosen.trip.id)
        .then(setTrack)
        .catch(() => undefined);
    }
  }, [chosen?.trip?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const emergencies = useMemo(() => (data?.vehicles ?? []).filter((v) => v.sos), [data]);
  const markers = useMemo(
    () => [
      ...(data?.vehicles ?? [])
        .filter((v) => v.position)
        .map((v) => ({
          id: v.vehicle_id,
          lat: v.position!.lat,
          lng: v.position!.lng,
          colour: STATE_COLOUR[v.state] ?? "#475569",
          label: `${v.registration}: ${STATE_LABEL[v.state]}${v.age_seconds !== null ? `, ${ago(v.age_seconds)}` : ""}`,
        })),
      // An open SOS is drawn where the driver pressed it, even for a lorry the map has not heard from.
      ...emergencies
        .filter((v) => v.sos!.lat != null && v.sos!.lng != null)
        .map((v) => ({
          id: `${v.vehicle_id}${SOS_SUFFIX}`,
          lat: v.sos!.lat!,
          lng: v.sos!.lng!,
          colour: "#dc2626",
          big: true,
          pulse: true,
          label: `SOS: ${v.registration}${v.sos!.driver ? `, ${v.sos!.driver}` : ""}`,
        })),
    ],
    [data, emergencies],
  );
  const lines = useMemo(
    () =>
      track && track.points.length > 1
        ? [{ points: track.points.map((p) => [p.lat, p.lng] as [number, number]) }]
        : [],
    [track],
  );
  const counts = (data?.vehicles ?? []).reduce<Record<string, number>>(
    (a, v) => ({ ...a, [v.state]: (a[v.state] ?? 0) + 1 }),
    {},
  );
  return (
    <>
      <h2>Live map</h2>
      <ErrorBanner message={error} />
      <p className="muted">
        {Object.entries(STATE_LABEL)
          .filter(([k]) => counts[k])
          .map(([k, label]) => `${counts[k]} ${label.toLowerCase()}`)
          .join(", ") || "No vehicles yet."}{" "}
        Phones report only while a trip is running, so a parked lorry shows where its last trip
        ended.
      </p>
      {emergencies.length > 0 && (
        <div className="banner bad" role="alert">
          <strong>SOS:</strong>{" "}
          {emergencies
            .map((v) => `${v.registration}${v.sos!.driver ? ` (${v.sos!.driver})` : ""}`)
            .join(", ")}
          {emergencies.some((v) => v.sos!.lat == null) &&
            ". Where the driver is is not known yet; the pin appears when the phone sends it."}{" "}
          <Link to="/incidents/sos">Answer it</Link>
        </div>
      )}
      <MapView
        markers={markers}
        lines={lines}
        selected={selected}
        onSelect={(id) => setSelected(id.replace(SOS_SUFFIX, ""))}
        height={460}
      />
      <Card title="Vehicles">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Vehicle</th>
                <th>State</th>
                <th>Trip</th>
                <th>Last heard</th>
              </tr>
            </thead>
            <tbody>
              {(data?.vehicles ?? []).map((v) => (
                <tr
                  key={v.vehicle_id}
                  onClick={() => setSelected(v.vehicle_id)}
                  style={{
                    cursor: "pointer",
                    fontWeight: v.vehicle_id === selected ? 700 : undefined,
                  }}
                >
                  <td>{v.registration}</td>
                  <td>
                    {v.sos && <span className="status bad">SOS </span>}
                    <span style={{ color: STATE_COLOUR[v.state] }}>{STATE_LABEL[v.state]}</span>
                    {v.going_dark && <span className="status bad"> went dark</span>}
                    {v.position?.speed_kmh != null &&
                      v.state === "moving" &&
                      ` ${Math.round(v.position.speed_kmh)} km/h`}
                  </td>
                  <td>
                    {v.trip ? (
                      <Link to={`/trips/${v.trip.id}`}>
                        {[v.trip.origin, v.trip.destination].filter(Boolean).join(" to ") || "Trip"}
                      </Link>
                    ) : (
                      ""
                    )}
                    {v.trip?.driver && <span className="muted"> {v.trip.driver}</span>}
                  </td>
                  <td>{ago(v.age_seconds)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
