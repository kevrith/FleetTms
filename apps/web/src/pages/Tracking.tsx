import type { TrackerAlert, TrackerDevice, Vehicle } from "@fleettms/types";
import { Plus, Radio } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { ALERT_KIND, ALERT_STATUS, nairobiTime, ONLINE_STATE, quietFor } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";
import Behaviour from "./Behaviour";
import Geofences from "./Geofences";

const SEVERITY: Record<string, string> = { red: "bad", amber: "warn", info: "ok" };

function detail(a: TrackerAlert): string {
  const d = a.details ?? {};
  if (a.kind === "geofence")
    return `${d.event === "enter" ? "Entered" : "Left"} ${String(d.geofence ?? "an area")}`;
  if (a.kind === "device_offline" && typeof d.quiet_minutes === "number")
    return `Silent for ${d.quiet_minutes} minutes`;
  return "";
}

function Alerts() {
  const { can } = useAuth();
  const [rows, setRows] = useState<TrackerAlert[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setRows(await api.trackerAlerts());
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => {
    void load();
    const timer = setInterval(load, 30000);
    return () => clearInterval(timer);
  }, [load]);
  async function handle(a: TrackerAlert, outcome: "explained" | "confirmed") {
    setError(null);
    try {
      await api.handleTrackerAlert(a.id, { note, outcome });
      setOpen(null);
      setNote("");
      await load();
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  return (
    <Card title="Tracker alerts">
      <ErrorBanner message={error} />
      <p className="muted">
        A cut power line, jamming or a tampered tracker is red and the owner is texted at once. An
        alert stays open until someone explains it or confirms it was real.
      </p>
      {rows.length === 0 && <p className="muted">No alerts.</p>}
      <ul className="list">
        {rows.map((a) => (
          <li key={a.id} style={{ display: "block" }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
              <span>
                <span className={`status ${SEVERITY[a.severity] ?? "ok"}`}>
                  {ALERT_KIND[a.kind] ?? a.kind}
                </span>{" "}
                <strong>{a.registration}</strong>
                {detail(a) && <span className="muted"> {detail(a)}</span>}
              </span>
              <span className="muted">
                {nairobiTime(a.at)}, {ALERT_STATUS[a.status] ?? a.status}
              </span>
            </div>
            {a.note && <div className="muted">Note: {a.note}</div>}
            {a.status === "open" && can("alerts.manage") && open !== a.id && (
              <button className="btn" type="button" onClick={() => setOpen(a.id)}>
                Handle
              </button>
            )}
            {open === a.id && (
              <div className="form-grid">
                <Field label="What happened?">
                  <input
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    minLength={3}
                    maxLength={500}
                    placeholder="For example: the mechanic unplugged it for a repair"
                  />
                </Field>
                <p className="actions">
                  <button
                    className="btn"
                    type="button"
                    disabled={note.trim().length < 3}
                    onClick={() => handle(a, "explained")}
                  >
                    There is an explanation
                  </button>
                  <button
                    className="btn"
                    type="button"
                    disabled={note.trim().length < 3}
                    onClick={() => handle(a, "confirmed")}
                  >
                    It was real
                  </button>
                  <button className="btn" type="button" onClick={() => setOpen(null)}>
                    Cancel
                  </button>
                </p>
              </div>
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}

const BLANK = {
  vehicle_id: "",
  imei: "",
  brand: "",
  model: "",
  sim_phone: "",
  supports_immobiliser: false,
};

function Trackers() {
  const { can } = useAuth();
  const [rows, setRows] = useState<TrackerDevice[]>([]);
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [form, setForm] = useState(BLANK);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setRows(await api.trackers());
      if (can("vehicles.manage")) setVehicles(await api.vehicles());
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [can]);
  useEffect(() => {
    void load();
  }, [load]);
  async function add(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.addTracker({
        vehicle_id: form.vehicle_id,
        imei: form.imei.trim(),
        brand: form.brand || null,
        model: form.model || null,
        sim_phone: form.sim_phone || null,
        supports_immobiliser: form.supports_immobiliser,
      });
      setForm(BLANK);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }
  async function toggle(t: TrackerDevice) {
    setError(null);
    try {
      await api.updateTracker(t.id, {
        vehicle_id: t.vehicle_id,
        imei: t.imei,
        name: t.name,
        brand: t.brand,
        model: t.model,
        sim_phone: t.sim_phone,
        supports_immobiliser: t.supports_immobiliser,
        is_active: !t.is_active,
      });
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }
  return (
    <>
      <ErrorBanner message={error} />
      <Card title="Trackers">
        {rows.length === 0 && <p className="muted">No trackers fitted yet.</p>}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Vehicle</th>
                <th>Device</th>
                <th>State</th>
                <th>Power</th>
                <th>Last heard</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((t) => (
                <tr key={t.id}>
                  <td>{t.registration}</td>
                  <td>
                    {[t.brand, t.model].filter(Boolean).join(" ") || "Tracker"}
                    <div className="muted">{t.imei}</div>
                  </td>
                  <td>
                    <span
                      className={`status ${t.online_state === "online" ? "ok" : t.online_state === "offline" ? "bad" : "warn"}`}
                    >
                      {ONLINE_STATE[t.online_state]}
                    </span>
                    {!t.is_active && <span className="muted"> switched off</span>}
                    {t.immobilised && <span className="status bad"> engine stopped</span>}
                  </td>
                  <td>
                    {t.power_ok === false ? (
                      <span className="status bad">Power lost</span>
                    ) : (
                      t.power_v != null && `${t.power_v.toFixed(1)} V`
                    )}
                    {t.battery_pct != null && (
                      <span className="muted"> battery {Math.round(t.battery_pct)}%</span>
                    )}
                    {t.gps_ok === false && <span className="status warn"> no GPS lock</span>}
                  </td>
                  <td>{quietFor(t.quiet_seconds)}</td>
                  <td>
                    {can("vehicles.manage") && (
                      <button className="btn" type="button" onClick={() => toggle(t)}>
                        {t.is_active ? "Switch off" : "Switch on"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      {can("vehicles.manage") && (
        <Card title="Fit a tracker">
          <p className="muted">
            Use the IMEI printed on the device: it is how the tracking server tells us which tracker
            a position came from. A vehicle with a tracker moves up to the standard tier.
          </p>
          <form className="form-grid" onSubmit={add}>
            <Field label="Vehicle">
              <select
                value={form.vehicle_id}
                onChange={(e) => setForm({ ...form, vehicle_id: e.target.value })}
                required
              >
                <option value="">Choose a vehicle</option>
                {vehicles.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.registration}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="IMEI">
              <input
                value={form.imei}
                onChange={(e) => setForm({ ...form, imei: e.target.value })}
                required
                minLength={6}
                maxLength={20}
                inputMode="numeric"
              />
            </Field>
            <Field label="Brand">
              <input
                value={form.brand}
                onChange={(e) => setForm({ ...form, brand: e.target.value })}
              />
            </Field>
            <Field label="Model">
              <input
                value={form.model}
                onChange={(e) => setForm({ ...form, model: e.target.value })}
              />
            </Field>
            <Field label="SIM phone number">
              <input
                value={form.sim_phone}
                onChange={(e) => setForm({ ...form, sim_phone: e.target.value })}
                inputMode="tel"
              />
            </Field>
            <label className="check">
              <input
                type="checkbox"
                checked={form.supports_immobiliser}
                onChange={(e) => setForm({ ...form, supports_immobiliser: e.target.checked })}
              />
              <span>This tracker is wired to stop the engine</span>
            </label>
            <button className="btn primary" type="submit">
              <Plus size={16} /> Fit tracker
            </button>
          </form>
        </Card>
      )}
    </>
  );
}

export default function Tracking() {
  return (
    <>
      <h2>
        <Radio size={20} /> Trackers and alerts
      </h2>
      <nav className="tabs">
        <NavLink to="/tracking" end>
          Alerts
        </NavLink>
        <NavLink to="/tracking/trackers">Trackers</NavLink>
        <NavLink to="/tracking/areas">Mapped areas</NavLink>
        <NavLink to="/tracking/behaviour">Driving behaviour</NavLink>
      </nav>
      <Routes>
        <Route index element={<Alerts />} />
        <Route path="trackers" element={<Trackers />} />
        <Route path="areas" element={<Geofences />} />
        <Route path="behaviour" element={<Behaviour />} />
      </Routes>
    </>
  );
}
