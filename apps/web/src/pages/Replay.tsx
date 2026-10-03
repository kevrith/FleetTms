import type { Replay, ReplayEvent } from "@fleettms/types";
import { Pause, Play } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { nairobiTime } from "../labels";
import { MapView, type MapMarker } from "../MapView";
import { Card, ErrorBanner, errorMessage } from "../ui";

const RANGES: [string, number][] = [
  ["Last 6 hours", 6],
  ["Last 24 hours", 24],
  ["Last 3 days", 72],
];

function colourOf(e: ReplayEvent): string {
  if (e.group === "alert") return e.severity === "red" ? "#dc2626" : "#d97706";
  if (e.group === "geofence") return "#2563eb";
  return e.kind === "speeding" ? "#dc2626" : "#7c3aed";
}

/** Plays back where a vehicle went, with speeding, hard stops, alerts and mapped-area crossings marked on the path. */
export function ReplayCard({ tripId, vehicleId }: { tripId?: string; vehicleId?: string }) {
  const { can } = useAuth();
  const [hours, setHours] = useState(24);
  const [replay, setReplay] = useState<Replay | null>(null);
  const [at, setAt] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const allowed = can("livemap.view");
  useEffect(() => {
    if (!allowed) return;
    setReplay(null);
    setAt(0);
    setPlaying(false);
    const end = new Date();
    const load = tripId
      ? api.tripReplay(tripId)
      : api.vehicleReplay(
          vehicleId ?? "",
          new Date(end.getTime() - hours * 3600_000).toISOString(),
          end.toISOString(),
        );
    load.then(setReplay).catch((e) => setError(errorMessage(e)));
  }, [tripId, vehicleId, hours, allowed]);
  const count = replay?.points.length ?? 0;
  useEffect(() => {
    if (!playing) return;
    const timer = setInterval(() => {
      setAt((i) => {
        if (i + 1 >= count) {
          setPlaying(false);
          return i;
        }
        return i + 1;
      });
    }, 150);
    return () => clearInterval(timer);
  }, [playing, count]);

  const line = useMemo(
    () =>
      replay ? [{ points: replay.points.map((p) => [p.lat, p.lng] as [number, number]) }] : [],
    [replay],
  );
  const markers: MapMarker[] = useMemo(() => {
    if (!replay) return [];
    const out: MapMarker[] = replay.events
      .filter((e) => e.lat != null && e.lng != null)
      .map((e, i) => ({
        id: `e${i}`,
        lat: e.lat as number,
        lng: e.lng as number,
        colour: colourOf(e),
        label: `${e.label}, ${nairobiTime(e.at)}`,
      }));
    const here = replay.points[at];
    if (here)
      out.push({
        id: "now",
        lat: here.lat,
        lng: here.lng,
        colour: "#16a34a",
        label: "Here",
        big: true,
      });
    return out;
  }, [replay, at]);
  if (!allowed) return null;
  const here = replay?.points[at];
  function jump(e: ReplayEvent) {
    if (!replay) return;
    const t = new Date(e.at).getTime();
    const i = replay.points.findIndex((p) => new Date(p.at).getTime() >= t);
    setAt(i < 0 ? replay.points.length - 1 : i);
    setPlaying(false);
  }
  return (
    <Card title="Replay">
      <ErrorBanner message={error} />
      {!tripId && (
        <label className="field">
          <span>Period</span>
          <select value={hours} onChange={(e) => setHours(Number(e.target.value))}>
            {RANGES.map(([label, h]) => (
              <option key={h} value={h}>
                {label}
              </option>
            ))}
          </select>
        </label>
      )}
      {replay && replay.fixes === 0 && <p className="muted">No locations were recorded.</p>}
      {replay && replay.fixes > 0 && (
        <>
          <MapView
            markers={markers}
            lines={line}
            height={340}
            fitKey={`${tripId ?? vehicleId}-${hours}`}
          />
          <p className="actions">
            <button
              className="btn"
              type="button"
              onClick={() => {
                if (at + 1 >= count) setAt(0);
                setPlaying(!playing);
              }}
            >
              {playing ? <Pause size={16} /> : <Play size={16} />} {playing ? "Pause" : "Play"}
            </button>
            <input
              type="range"
              min={0}
              max={Math.max(count - 1, 0)}
              value={at}
              onChange={(e) => {
                setAt(Number(e.target.value));
                setPlaying(false);
              }}
              aria-label="Position along the path"
              style={{ flex: 1 }}
            />
          </p>
          <p className="muted">
            {here && nairobiTime(here.at)}
            {here?.speed_kmh != null && `, ${Math.round(here.speed_kmh)} km/h`}. {replay.fixes}{" "}
            fixes from the {replay.source === "tracker" ? "tracker" : "driver's phone"}.
          </p>
          {replay.events.length > 0 && (
            <ul className="list">
              {replay.events.map((e, i) => (
                <li key={i} onClick={() => jump(e)} style={{ cursor: "pointer" }}>
                  <span style={{ color: colourOf(e) }}>{e.label}</span>
                  <span className="muted">{nairobiTime(e.at)}</span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </Card>
  );
}
