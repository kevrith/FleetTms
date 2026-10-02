import type { Tyre, TyreAlert, TyreReport, VehicleBrief } from "@fleettms/types";
import { Check, Plus } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { TYRE_REASON, TYRE_STATUS, kes, positionLabel } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

const POSITIONS = [
  "steer_left",
  "steer_right",
  ...["drive1", "drive2", "trailer1", "trailer2"].flatMap((axle) =>
    ["left_outer", "left_inner", "right_inner", "right_outer"].map((s) => `${axle}_${s}`),
  ),
  "spare",
];

function AddTyre({ onAdded }: { onAdded: () => void }) {
  const [form, setForm] = useState({ serial: "", brand: "", size: "", cost: "", supplier: "" });
  const [error, setError] = useState<string | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.addTyre({
        serial: form.serial,
        brand: form.brand,
        size: form.size,
        cost_cents: Math.round(Number(form.cost || 0) * 100),
        supplier: form.supplier || null,
      });
      setForm({ serial: "", brand: "", size: "", cost: "", supplier: "" });
      onAdded();
    } catch (err) {
      setError(errorMessage(err));
    }
  }
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm({ ...form, [k]: e.target.value });
  return (
    <Card title="Record a new tyre">
      <ErrorBanner message={error} />
      <form className="form-grid" onSubmit={submit}>
        <Field label="Serial number">
          <input value={form.serial} onChange={set("serial")} required />
        </Field>
        <Field label="Brand">
          <input value={form.brand} onChange={set("brand")} required />
        </Field>
        <Field label="Size">
          <input value={form.size} onChange={set("size")} placeholder="315/80R22.5" required />
        </Field>
        <Field label="Cost (KES)">
          <input type="number" min="0" step="0.01" value={form.cost} onChange={set("cost")} />
        </Field>
        <Field label="Supplier">
          <input value={form.supplier} onChange={set("supplier")} />
        </Field>
        <button className="btn primary" type="submit">
          <Plus size={16} /> Add tyre
        </button>
      </form>
    </Card>
  );
}

function TyreActions({
  tyre,
  vehicles,
  onDone,
  fail,
}: {
  tyre: Tyre;
  vehicles: VehicleBrief[];
  onDone: () => void;
  fail: (m: string | null) => void;
}) {
  const [vehicleId, setVehicleId] = useState(vehicles[0]?.id ?? "");
  const [position, setPosition] = useState("steer_left");
  const [tread, setTread] = useState("");
  const [cost, setCost] = useState("");
  async function run(action: () => Promise<unknown>) {
    fail(null);
    try {
      await action();
      onDone();
    } catch (e) {
      fail(errorMessage(e));
    }
  }
  const fitted = tyre.status === "fitted";
  const free = tyre.status === "in_store" || tyre.status === "removed";
  return (
    <div className="form-grid">
      {free && (
        <>
          <Field label="VehicleBrief">
            <select value={vehicleId} onChange={(e) => setVehicleId(e.target.value)}>
              {vehicles.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.registration}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Position">
            <select value={position} onChange={(e) => setPosition(e.target.value)}>
              {POSITIONS.map((p) => (
                <option key={p} value={p}>
                  {positionLabel(p)}
                </option>
              ))}
            </select>
          </Field>
          <button
            className="btn primary"
            onClick={() => run(() => api.fitTyre(tyre.id, { vehicle_id: vehicleId, position }))}
          >
            Fit
          </button>
          <Field label="Retread cost (KES)">
            <input type="number" min="0" value={cost} onChange={(e) => setCost(e.target.value)} />
          </Field>
          <button
            className="btn"
            disabled={cost === ""}
            onClick={() => run(() => api.retreadTyre(tyre.id, Math.round(Number(cost) * 100)))}
          >
            Retread
          </button>
        </>
      )}
      {fitted && (
        <>
          <Field label="Move to">
            <select value={position} onChange={(e) => setPosition(e.target.value)}>
              {POSITIONS.map((p) => (
                <option key={p} value={p}>
                  {positionLabel(p)}
                </option>
              ))}
            </select>
          </Field>
          <button className="btn" onClick={() => run(() => api.rotateTyre(tyre.id, position))}>
            Rotate
          </button>
          <Field label="Tread (mm)">
            <input
              type="number"
              min="0"
              step="0.1"
              value={tread}
              onChange={(e) => setTread(e.target.value)}
            />
          </Field>
          <button
            className="btn"
            disabled={tread === ""}
            onClick={() => run(() => api.tyreTread(tyre.id, tread))}
          >
            Record tread
          </button>
          <button className="btn" onClick={() => run(() => api.removeTyre(tyre.id, {}))}>
            Take off
          </button>
          <button
            className="btn danger"
            onClick={() => run(() => api.removeTyre(tyre.id, { scrap: true }))}
          >
            Scrap
          </button>
        </>
      )}
    </div>
  );
}

function Alerts({ alerts, onChanged }: { alerts: TyreAlert[]; onChanged: () => void }) {
  const [error, setError] = useState<string | null>(null);
  if (alerts.length === 0) return null;
  return (
    <Card title="Possible tyre swaps">
      <ErrorBanner message={error} />
      <p className="muted">
        A driver read a serial at inspection that is not the tyre recorded at that position.
      </p>
      <ul className="list">
        {alerts.map((a) => (
          <li key={a.id}>
            <span>
              <strong>{a.registration}</strong>, {positionLabel(a.position).toLowerCase()}: recorded{" "}
              {a.expected_serial ?? "nothing"}, driver read <strong>{a.seen_serial}</strong>.{" "}
              <span className="muted">{TYRE_REASON[a.reason]}</span>
            </span>
            <button
              className="btn"
              onClick={async () => {
                try {
                  await api.resolveTyreAlert(a.id);
                  onChanged();
                } catch (e) {
                  setError(errorMessage(e));
                }
              }}
            >
              <Check size={16} /> Checked
            </button>
          </li>
        ))}
      </ul>
    </Card>
  );
}

/** Tyre register: serials, positions, kilometres, tread, retreads, rotations and swap alerts. */
export default function Tyres() {
  const [tyres, setTyres] = useState<Tyre[]>([]);
  const [alerts, setAlerts] = useState<TyreAlert[]>([]);
  const [report, setReport] = useState<TyreReport | null>(null);
  const [vehicles, setVehicles] = useState<VehicleBrief[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [t, a, r, v] = await Promise.all([
        api.tyres(),
        api.tyreAlerts(),
        api.tyreReport(),
        api.workshopVehicles(),
      ]);
      setTyres(t);
      setAlerts(a);
      setReport(r);
      setVehicles(v);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const current = tyres.find((t) => t.id === selected);
  return (
    <>
      <ErrorBanner message={error} />
      <Alerts alerts={alerts} onChanged={load} />
      <Card title="Tyres">
        {tyres.length === 0 && <p className="muted">No tyres recorded yet.</p>}
        {tyres.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Serial</th>
                  <th>Brand and size</th>
                  <th>Where</th>
                  <th>Run</th>
                  <th>Tread</th>
                  <th>Cost per km</th>
                  <th>Needs</th>
                </tr>
              </thead>
              <tbody>
                {tyres.map((t) => (
                  <tr key={t.id}>
                    <td>
                      <button className="btn" onClick={() => setSelected(t.id)}>
                        {t.serial}
                      </button>
                    </td>
                    <td>
                      {t.brand} {t.size}
                    </td>
                    <td>
                      {t.status === "fitted"
                        ? `${t.registration}, ${positionLabel(t.position).toLowerCase()}`
                        : TYRE_STATUS[t.status]}
                    </td>
                    <td>{t.km_run.toLocaleString()} km</td>
                    <td>{t.last_tread_mm !== null ? `${t.last_tread_mm} mm` : ""}</td>
                    <td>{t.cost_per_km_cents !== null ? kes(t.cost_per_km_cents) : ""}</td>
                    <td>
                      {t.due.map((d) => (
                        <span key={d} className={`status ${d === "replace" ? "bad" : "warn"}`}>
                          {d === "replace" ? "Replace" : "Rotate"}{" "}
                        </span>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {current && (
        <Card title={`${current.serial}: ${current.brand} ${current.size}`}>
          <p className="muted">
            Cost {kes(current.cost_cents)}
            {current.retreads > 0 &&
              `, ${current.retreads} retread(s) for ${kes(current.retread_cost_cents)}`}
            {current.supplier && `, from ${current.supplier}`}
          </p>
          {current.status !== "scrapped" && (
            <TyreActions
              key={current.id + current.status + current.position}
              tyre={current}
              vehicles={vehicles}
              onDone={load}
              fail={setError}
            />
          )}
        </Card>
      )}
      <AddTyre onAdded={load} />
      {report && (
        <Card title="Cost per km">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>By</th>
                  <th>Tyres</th>
                  <th>Total cost</th>
                  <th>Run</th>
                  <th>Cost per km</th>
                </tr>
              </thead>
              <tbody>
                {[
                  ...report.by_brand.map((g) => ({ ...g, name: `Brand: ${g.name}` })),
                  ...report.by_supplier.map((g) => ({ ...g, name: `Supplier: ${g.name}` })),
                ].map((g) => (
                  <tr key={g.name}>
                    <td>{g.name}</td>
                    <td>{g.tyres}</td>
                    <td>{kes(g.cost_cents)}</td>
                    <td>{g.km.toLocaleString()} km</td>
                    <td>{g.cost_per_km_cents !== null ? kes(g.cost_per_km_cents) : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </>
  );
}
