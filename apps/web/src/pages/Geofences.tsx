import type { Geofence, GeofenceEvent, GeofenceKind, GeofenceShape } from "@fleettms/types";
import { Eraser, Save, Trash2, Undo2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { GEOFENCE_COLOUR, GEOFENCE_KIND, nairobiTime } from "../labels";
import { MapView, type MapShape } from "../MapView";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

interface Draft {
  id: string | null;
  name: string;
  kind: GeofenceKind;
  mode: "circle" | "polygon";
  centre: [number, number] | null;
  radius: string;
  corners: [number, number][];
  enter: boolean;
  exit: boolean;
}

const BLANK: Draft = {
  id: null,
  name: "",
  kind: "client_site",
  mode: "circle",
  centre: null,
  radius: "300",
  corners: [],
  enter: true,
  exit: true,
};

function fromGeofence(g: Geofence): Draft {
  return {
    id: g.id,
    name: g.name,
    kind: g.kind,
    mode: g.shape.type,
    centre: g.shape.type === "circle" ? [g.shape.lat, g.shape.lng] : null,
    radius: g.shape.type === "circle" ? String(Math.round(g.shape.radius_m)) : "300",
    corners: g.shape.type === "polygon" ? g.shape.points : [],
    enter: g.alert_on.includes("enter"),
    exit: g.alert_on.includes("exit"),
  };
}

function shapeOf(d: Draft): GeofenceShape | null {
  if (d.mode === "circle") {
    const r = Number(d.radius);
    return d.centre && r >= 20
      ? { type: "circle", lat: d.centre[0], lng: d.centre[1], radius_m: r }
      : null;
  }
  return d.corners.length >= 3 ? { type: "polygon", points: d.corners } : null;
}

/** Areas on the map: depots, client sites, fuel stations and places lorries must not go. Draw one by clicking the map. */
export default function Geofences() {
  const { can } = useAuth();
  const [rows, setRows] = useState<Geofence[]>([]);
  const [events, setEvents] = useState<GeofenceEvent[]>([]);
  const [draft, setDraft] = useState<Draft>(BLANK);
  const [error, setError] = useState<string | null>(null);
  const manage = can("geofences.manage");
  const load = useCallback(async () => {
    try {
      setRows(await api.geofences());
      setEvents(await api.geofenceEvents({ limit: 30 }));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const preview = shapeOf(draft);
  const shapes: MapShape[] = useMemo(
    () => [
      ...rows
        .filter((g) => g.id !== draft.id)
        .map((g) => ({
          id: g.id,
          shape: g.shape,
          colour: GEOFENCE_COLOUR[g.kind] ?? "#475569",
          label: g.name,
        })),
      ...(preview
        ? [{ id: "draft", shape: preview, colour: "#7c3aed", label: "New area", draft: true }]
        : []),
    ],
    [rows, draft.id, preview],
  );
  const click = manage
    ? (lat: number, lng: number) => {
        const at: [number, number] = [Number(lat.toFixed(6)), Number(lng.toFixed(6))];
        setDraft((d) =>
          d.mode === "circle" ? { ...d, centre: at } : { ...d, corners: [...d.corners, at] },
        );
      }
    : undefined;
  async function save(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const shape = shapeOf(draft);
    if (!shape) {
      setError(
        draft.mode === "circle"
          ? "Click the map to place the centre, and give a radius of at least 20 metres."
          : "Click at least three corners on the map.",
      );
      return;
    }
    const body = {
      name: draft.name.trim(),
      kind: draft.kind,
      shape,
      alert_on: [
        ...(draft.enter ? ["enter" as const] : []),
        ...(draft.exit ? ["exit" as const] : []),
      ],
      vehicle_ids: draft.id ? (rows.find((g) => g.id === draft.id)?.vehicle_ids ?? null) : null,
      is_active: true,
    };
    try {
      if (draft.id) await api.updateGeofence(draft.id, body);
      else await api.addGeofence(body);
      setDraft(BLANK);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }
  async function remove(g: Geofence) {
    if (!window.confirm(`Delete the area "${g.name}"? Its history stays.`)) return;
    setError(null);
    try {
      await api.deleteGeofence(g.id);
      if (draft.id === g.id) setDraft(BLANK);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }
  return (
    <>
      <ErrorBanner message={error} />
      <MapView
        markers={[]}
        shapes={shapes}
        draft={draft.mode === "polygon" && draft.corners.length < 3 ? draft.corners : []}
        onMapClick={click}
        fitKey={rows.length > 0 ? "areas" : undefined}
        height={420}
      />
      {manage && (
        <Card title={draft.id ? "Change this area" : "Draw a new area"}>
          <p className="muted">
            {draft.mode === "circle"
              ? "Click the map to place the centre, then set the radius."
              : "Click the corners of the area in order, at least three."}
          </p>
          <form className="form-grid" onSubmit={save}>
            <Field label="Name">
              <input
                value={draft.name}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                required
                minLength={2}
              />
            </Field>
            <Field label="What is it?">
              <select
                value={draft.kind}
                onChange={(e) => setDraft({ ...draft, kind: e.target.value as GeofenceKind })}
              >
                {Object.entries(GEOFENCE_KIND).map(([k, label]) => (
                  <option key={k} value={k}>
                    {label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Shape">
              <select
                value={draft.mode}
                onChange={(e) => setDraft({ ...draft, mode: e.target.value as Draft["mode"] })}
              >
                <option value="circle">Circle (centre and radius)</option>
                <option value="polygon">Outline (click the corners)</option>
              </select>
            </Field>
            {draft.mode === "circle" && (
              <Field label="Radius (metres)">
                <input
                  type="number"
                  min={20}
                  max={100000}
                  value={draft.radius}
                  onChange={(e) => setDraft({ ...draft, radius: e.target.value })}
                />
              </Field>
            )}
            <label className="check">
              <input
                type="checkbox"
                checked={draft.enter}
                onChange={(e) => setDraft({ ...draft, enter: e.target.checked })}
              />
              <span>Alert when a vehicle goes in</span>
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={draft.exit}
                onChange={(e) => setDraft({ ...draft, exit: e.target.checked })}
              />
              <span>Alert when a vehicle leaves</span>
            </label>
            <p className="actions">
              <button className="btn primary" type="submit">
                <Save size={16} /> {draft.id ? "Save changes" : "Save area"}
              </button>
              {draft.mode === "polygon" && draft.corners.length > 0 && (
                <button
                  className="btn"
                  type="button"
                  onClick={() => setDraft({ ...draft, corners: draft.corners.slice(0, -1) })}
                >
                  <Undo2 size={16} /> Undo corner
                </button>
              )}
              <button className="btn" type="button" onClick={() => setDraft(BLANK)}>
                <Eraser size={16} /> Start again
              </button>
            </p>
          </form>
          <p className="muted">
            A red area (must not enter) texts the owner when a lorry goes in. The other kinds only
            show in the history.
          </p>
        </Card>
      )}
      <Card title="Areas">
        {rows.length === 0 && <p className="muted">No areas drawn yet.</p>}
        <ul className="list">
          {rows.map((g) => (
            <li key={g.id}>
              <span>
                <span style={{ color: GEOFENCE_COLOUR[g.kind] }}>{g.name}</span>{" "}
                <span className="muted">
                  {GEOFENCE_KIND[g.kind]}
                  {g.alert_on.length > 0 && `, alerts on ${g.alert_on.join(" and ")}`}
                  {g.vehicle_ids && `, ${g.vehicle_ids.length} vehicle(s)`}
                </span>
              </span>
              {manage && (
                <span className="actions">
                  <button className="btn" type="button" onClick={() => setDraft(fromGeofence(g))}>
                    Change
                  </button>
                  <button className="btn" type="button" onClick={() => remove(g)}>
                    <Trash2 size={16} /> Delete
                  </button>
                </span>
              )}
            </li>
          ))}
        </ul>
      </Card>
      <Card title="Recent entries and exits">
        {events.length === 0 && <p className="muted">Nothing yet.</p>}
        <ul className="list">
          {events.map((e) => (
            <li key={e.id}>
              <span>
                <strong>{e.registration}</strong> {e.kind === "enter" ? "entered" : "left"}{" "}
                {e.geofence ?? "an area"}
              </span>
              <span className="muted">{nairobiTime(e.at)}</span>
            </li>
          ))}
        </ul>
      </Card>
    </>
  );
}
