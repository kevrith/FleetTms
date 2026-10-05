import type { Part, ServiceSchedule, VehicleBrief, WorkOrder } from "@fleettms/types";
import { Check, Plus, Trash2, Wrench } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, NavLink, Navigate, Route, Routes } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { DUE_STATUS, PRIORITY, WO_STATUS, kes } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";
import Parts from "./Parts";
import Tyres from "./Tyres";

function WorkOrderPanel({
  wo,
  vehicle,
  onChanged,
  onCompleted,
}: {
  wo: WorkOrder;
  vehicle?: VehicleBrief;
  onChanged: () => Promise<void>;
  onCompleted: () => void;
}) {
  const { can } = useAuth();
  const manage = can("workshop.manage");
  const [assignee, setAssignee] = useState({
    kind: wo.assignee_kind ?? "mechanic",
    name: wo.assignee_name ?? "",
  });
  const [labour, setLabour] = useState(String(wo.labour_cents / 100));
  // Parts issued from the store are handled below; only hand-entered parts are edited here.
  const storeParts = wo.parts.filter((p) => p.part_id);
  const [stock, setStock] = useState<Part[]>([]);
  const [issue, setIssue] = useState({ partId: "", qty: "1" });
  useEffect(() => {
    if (manage && wo.status !== "done" && wo.status !== "cancelled")
      api
        .parts()
        .then(setStock)
        .catch(() => setStock([]));
  }, [manage, wo.status, wo.parts.length]);
  const [parts, setParts] = useState(
    wo.parts
      .filter((p) => !p.part_id)
      .map((p) => ({
        name: p.name,
        qty: String(p.quantity),
        cost: String(p.unit_cost_cents / 100),
      })),
  );
  const [done, setDone] = useState({ odometer: String(vehicle?.odometer_km ?? ""), notes: "" });
  const [error, setError] = useState<string | null>(null);
  const closed = wo.status === "done" || wo.status === "cancelled";

  async function run(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
      await onChanged();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  const save = (extra: Record<string, unknown> = {}) =>
    run(() =>
      api.updateWorkOrder(wo.id, {
        assignee_kind: assignee.name.trim() ? assignee.kind : null,
        assignee_name: assignee.name.trim() || null,
        labour_cents: Math.round(Number(labour || 0) * 100),
        parts: parts
          .filter((p) => p.name.trim())
          .map((p) => ({
            name: p.name.trim(),
            quantity: Math.max(1, Number(p.qty) || 1),
            unit_cost_cents: Math.round(Number(p.cost || 0) * 100),
          })),
        ...extra,
      }),
    );

  return (
    <Card title={`${vehicle?.registration ?? ""}: ${wo.title}`}>
      <ErrorBanner message={error} />
      <p>
        <span
          className={`status ${wo.priority === "urgent" ? "bad" : wo.priority === "high" ? "warn" : "ok"}`}
        >
          {PRIORITY[wo.priority]}
        </span>{" "}
        {WO_STATUS[wo.status]}{" "}
        <span className="muted">
          (
          {wo.source === "defect"
            ? "from an inspection"
            : wo.source === "service"
              ? "from a service reminder"
              : wo.source === "incident"
                ? "from a breakdown report"
                : "raised by hand"}
          )
        </span>
      </p>
      {wo.description && <p className="muted">{wo.description}</p>}
      {wo.photos && wo.photos.length > 0 && (
        <p>
          {wo.photos.map((p) => (
            <a key={p.id} href={api.mediaUrl(p.url)} target="_blank" rel="noreferrer">
              <img src={api.mediaUrl(p.url)} alt="Sent by the driver" height={80} />
            </a>
          ))}
        </p>
      )}
      {manage && !closed && (
        <>
          <div className="form-grid">
            <Field label="Assigned to">
              <select
                value={assignee.kind}
                onChange={(e) =>
                  setAssignee({ ...assignee, kind: e.target.value as "mechanic" | "garage" })
                }
              >
                <option value="mechanic">Mechanic</option>
                <option value="garage">Garage</option>
              </select>
            </Field>
            <Field label="Name">
              <input
                value={assignee.name}
                onChange={(e) => setAssignee({ ...assignee, name: e.target.value })}
              />
            </Field>
            <Field label="Labour (KES)">
              <input
                type="number"
                min="0"
                step="0.01"
                value={labour}
                onChange={(e) => setLabour(e.target.value)}
              />
            </Field>
          </div>
          <h4>Parts from the store</h4>
          {storeParts.length === 0 && <p className="muted">Nothing issued from the store yet.</p>}
          <ul className="list">
            {storeParts.map((p) => (
              <li key={p.id}>
                <span>
                  {p.quantity} x {p.name} ({kes(p.quantity * p.unit_cost_cents)}){" "}
                  <span className={`status ${p.fitted ? "ok" : "warn"}`}>
                    {p.fitted ? "Fitted" : "Not yet confirmed as fitted"}
                  </span>
                </span>
                <span className="actions">
                  <button
                    className="btn"
                    onClick={() => run(() => api.markPartFitted(wo.id, p.id, !p.fitted))}
                  >
                    {p.fitted ? "Mark not fitted" : "Mark as fitted"}
                  </button>
                  <button
                    className="btn danger"
                    onClick={() => run(() => api.returnPart(wo.id, p.id))}
                  >
                    Return to store
                  </button>
                </span>
              </li>
            ))}
          </ul>
          <div className="form-grid">
            <Field label="Issue a part">
              <select
                value={issue.partId}
                onChange={(e) => setIssue({ ...issue, partId: e.target.value })}
              >
                <option value="">Choose a part</option>
                {stock.map((p) => (
                  <option key={p.id} value={p.id} disabled={p.quantity === 0}>
                    {p.name} ({p.quantity} in stock)
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Quantity">
              <input
                type="number"
                min="1"
                value={issue.qty}
                onChange={(e) => setIssue({ ...issue, qty: e.target.value })}
              />
            </Field>
            <button
              className="btn primary"
              disabled={!issue.partId || !(Number(issue.qty) > 0)}
              onClick={() =>
                run(async () => {
                  await api.issuePart(wo.id, issue.partId, Number(issue.qty));
                  setIssue({ partId: "", qty: "1" });
                })
              }
            >
              Issue from the store
            </button>
          </div>
          <h4>Other parts (bought outside the store)</h4>
          {parts.map((p, i) => (
            <div key={i} className="form-grid">
              <Field label="Part">
                <input
                  value={p.name}
                  onChange={(e) =>
                    setParts(parts.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))
                  }
                />
              </Field>
              <Field label="Quantity">
                <input
                  type="number"
                  min="1"
                  value={p.qty}
                  onChange={(e) =>
                    setParts(parts.map((x, j) => (j === i ? { ...x, qty: e.target.value } : x)))
                  }
                />
              </Field>
              <Field label="Unit cost (KES)">
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={p.cost}
                  onChange={(e) =>
                    setParts(parts.map((x, j) => (j === i ? { ...x, cost: e.target.value } : x)))
                  }
                />
              </Field>
              <button
                className="btn danger"
                onClick={() => setParts(parts.filter((_, j) => j !== i))}
              >
                <Trash2 size={16} /> Remove
              </button>
            </div>
          ))}
          <p className="actions">
            <button
              className="btn"
              onClick={() => setParts([...parts, { name: "", qty: "1", cost: "0" }])}
            >
              <Plus size={16} /> Add a part
            </button>
            <button className="btn" onClick={() => save()}>
              Save changes
            </button>
            {wo.status !== "in_progress" && (
              <button className="btn" onClick={() => save({ status: "in_progress" })}>
                Start work
              </button>
            )}
            {wo.status !== "waiting_parts" && (
              <button className="btn" onClick={() => save({ status: "waiting_parts" })}>
                Waiting for parts
              </button>
            )}
            <button className="btn danger" onClick={() => save({ status: "cancelled" })}>
              Cancel
            </button>
          </p>
          <h4>Finish the job</h4>
          <div className="form-grid">
            <Field label="Odometer now (km)">
              <input
                type="number"
                min="0"
                value={done.odometer}
                onChange={(e) => setDone({ ...done, odometer: e.target.value })}
              />
            </Field>
            <Field label="Notes">
              <input
                value={done.notes}
                onChange={(e) => setDone({ ...done, notes: e.target.value })}
              />
            </Field>
            <button
              className="btn primary"
              onClick={() =>
                run(async () => {
                  await save();
                  await api.completeWorkOrder(wo.id, {
                    odometer_km: done.odometer ? Number(done.odometer) : null,
                    labour_cents: Math.round(Number(labour || 0) * 100),
                    notes: done.notes.trim() || null,
                  });
                  onCompleted();
                })
              }
            >
              <Check size={16} /> Mark done and record the cost
            </button>
          </div>
        </>
      )}
      {(closed || !manage) && (
        <p className="muted">
          Labour {kes(wo.labour_cents)}, parts {kes(wo.parts_cents)}, total{" "}
          <strong>{kes(wo.total_cents)}</strong>
        </p>
      )}
    </Card>
  );
}

function WorkOrders() {
  const { can } = useAuth();
  const [rows, setRows] = useState<WorkOrder[]>([]);
  const [vehicles, setVehicles] = useState<VehicleBrief[]>([]);
  const [openOnly, setOpenOnly] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  const [form, setForm] = useState({ vehicle: "", title: "", priority: "normal" });
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRows(await api.workOrders({ openOnly }));
      setVehicles(await api.workshopVehicles());
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [openOnly]);
  useEffect(() => {
    void load();
  }, [load]);

  async function create(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const wo = await api.createWorkOrder({
        vehicle_id: form.vehicle,
        title: form.title,
        priority: form.priority,
      });
      setForm({ ...form, title: "" });
      setSelected(wo.id);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const vehicle = (id: string) => vehicles.find((v) => v.id === id);
  const current = rows.find((r) => r.id === selected);
  return (
    <>
      <ErrorBanner message={error} />
      {can("workshop.manage") && (
        <Card title="Raise a work order">
          <form onSubmit={create} className="form-grid">
            <Field label="Vehicle">
              <select
                value={form.vehicle}
                onChange={(e) => setForm({ ...form, vehicle: e.target.value })}
                required
              >
                <option value="">Choose...</option>
                {vehicles.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.registration}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="What needs doing?">
              <input
                value={form.title}
                onChange={(e) => setForm({ ...form, title: e.target.value })}
                required
                minLength={3}
              />
            </Field>
            <Field label="Priority">
              <select
                value={form.priority}
                onChange={(e) => setForm({ ...form, priority: e.target.value })}
              >
                {Object.entries(PRIORITY).map(([k, label]) => (
                  <option key={k} value={k}>
                    {label}
                  </option>
                ))}
              </select>
            </Field>
            <button className="btn primary">
              <Wrench size={16} /> Raise
            </button>
          </form>
        </Card>
      )}
      <Card title="Work orders">
        <label className="check">
          <input
            type="checkbox"
            checked={openOnly}
            onChange={(e) => setOpenOnly(e.target.checked)}
          />
          <span>Only open ones</span>
        </label>
        {rows.length === 0 && <p className="muted">No work orders.</p>}
        {rows.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Vehicle</th>
                  <th>Job</th>
                  <th>Priority</th>
                  <th>Status</th>
                  <th>Assigned to</th>
                  <th>Cost</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td>{vehicle(r.vehicle_id)?.registration}</td>
                    <td>
                      <button className="btn" onClick={() => setSelected(r.id)}>
                        {r.title}
                      </button>
                    </td>
                    <td>{PRIORITY[r.priority]}</td>
                    <td>{WO_STATUS[r.status]}</td>
                    <td>{r.assignee_name}</td>
                    <td>{r.total_cents > 0 ? kes(r.total_cents) : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {current && (
        <WorkOrderPanel
          key={current.id + current.status + current.total_cents}
          wo={current}
          vehicle={vehicle(current.vehicle_id)}
          onChanged={load}
          onCompleted={() => setOpenOnly(false)}
        />
      )}
    </>
  );
}

function ServiceDue() {
  const [rows, setRows] = useState<ServiceSchedule[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api
      .serviceSchedules()
      .then(setRows)
      .catch((e) => setError(errorMessage(e)));
  }, []);
  return (
    <>
      <ErrorBanner message={error} />
      <Card title="Service schedules across the fleet">
        <p className="muted">Add schedules on each vehicle's page. Most urgent first.</p>
        {rows.length === 0 && <p className="muted">No service schedules yet.</p>}
        {rows.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Vehicle</th>
                  <th>Service</th>
                  <th>Where it stands</th>
                  <th>Next due</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <Link to={`/vehicles/${r.vehicle_id}`}>{r.registration}</Link>
                    </td>
                    <td>{r.name}</td>
                    <td>
                      <span
                        className={`status ${r.due_status === "overdue" ? "bad" : r.due_status === "due_soon" ? "warn" : "ok"}`}
                      >
                        {DUE_STATUS[r.due_status]}
                      </span>
                    </td>
                    <td>
                      {r.next_km !== null &&
                        `${r.next_km.toLocaleString()} km (${r.km_left! >= 0 ? `${r.km_left!.toLocaleString()} to go` : `${(-r.km_left!).toLocaleString()} over`})`}
                      {r.next_km !== null && r.next_due_on && ", "}
                      {r.next_due_on && `${r.next_due_on}`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}

export default function Workshop() {
  return (
    <>
      <h2>Workshop</h2>
      <nav className="tabs">
        <NavLink to="orders">Work orders</NavLink>
        <NavLink to="service">Service due</NavLink>
        <NavLink to="tyres">Tyres</NavLink>
        <NavLink to="parts">Parts store</NavLink>
      </nav>
      <Routes>
        <Route index element={<Navigate to="orders" replace />} />
        <Route path="orders" element={<WorkOrders />} />
        <Route path="service" element={<ServiceDue />} />
        <Route path="tyres" element={<Tyres />} />
        <Route path="parts" element={<Parts />} />
      </Routes>
    </>
  );
}
