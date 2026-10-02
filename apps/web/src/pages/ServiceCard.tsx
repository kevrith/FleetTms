import type { ServiceHistory } from "@fleettms/types";
import { Plus } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { DUE_STATUS, kes } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

/** A vehicle's service schedules (by kilometres and/or time) and what has been done to it. */
export default function ServiceCard({ vehicleId }: { vehicleId: string }) {
  const { can } = useAuth();
  const [data, setData] = useState<ServiceHistory | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "", km: "", months: "", lastKm: "", lastOn: "" });

  const load = useCallback(async () => {
    try {
      setData(await api.vehicleServices(vehicleId));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [vehicleId]);
  useEffect(() => {
    void load();
  }, [load]);

  async function add(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.addServiceSchedule(vehicleId, {
        name: form.name,
        every_km: form.km ? Number(form.km) : null,
        every_months: form.months ? Number(form.months) : null,
        last_done_km: form.lastKm ? Number(form.lastKm) : 0,
        last_done_on: form.lastOn || null,
      });
      setForm({ name: "", km: "", months: "", lastKm: "", lastOn: "" });
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  if (!data) return error ? <ErrorBanner message={error} /> : null;
  return (
    <Card title="Service">
      <ErrorBanner message={error} />
      {data.schedules.length === 0 && <p className="muted">No service schedules yet.</p>}
      <ul className="list">
        {data.schedules.map((s) => (
          <li key={s.id}>
            <span>
              <strong>{s.name}</strong>{" "}
              <span className="muted">
                every{" "}
                {[
                  s.every_km && `${s.every_km.toLocaleString()} km`,
                  s.every_months && `${s.every_months} months`,
                ]
                  .filter(Boolean)
                  .join(" or ")}
              </span>
            </span>
            <span>
              <span
                className={`status ${s.due_status === "overdue" ? "bad" : s.due_status === "due_soon" ? "warn" : "ok"}`}
              >
                {DUE_STATUS[s.due_status]}
              </span>{" "}
              <span className="muted">
                {s.km_left !== null &&
                  (s.km_left >= 0
                    ? `${s.km_left.toLocaleString()} km to go`
                    : `${(-s.km_left).toLocaleString()} km over`)}
                {s.days_left !== null && ` ${s.days_left} days`}
              </span>
            </span>
          </li>
        ))}
      </ul>
      {can("vehicles.manage") && (
        <form onSubmit={add} className="form-grid">
          <Field label="Service">
            <input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="Oil and filters"
              required
              minLength={2}
            />
          </Field>
          <Field label="Every (km)">
            <input
              type="number"
              min="1"
              value={form.km}
              onChange={(e) => setForm({ ...form, km: e.target.value })}
            />
          </Field>
          <Field label="Every (months)">
            <input
              type="number"
              min="1"
              value={form.months}
              onChange={(e) => setForm({ ...form, months: e.target.value })}
            />
          </Field>
          <Field label="Last done at (km)">
            <input
              type="number"
              min="0"
              value={form.lastKm}
              onChange={(e) => setForm({ ...form, lastKm: e.target.value })}
            />
          </Field>
          <Field label="Last done on">
            <input
              type="date"
              value={form.lastOn}
              onChange={(e) => setForm({ ...form, lastOn: e.target.value })}
            />
          </Field>
          <button className="btn primary">
            <Plus size={16} /> Add schedule
          </button>
        </form>
      )}
      {data.history.length > 0 && <h4>History</h4>}
      <ul className="list">
        {data.history.map((h) => (
          <li key={h.id}>
            <span>
              {h.done_on} at {h.odometer_km.toLocaleString()} km{" "}
              {h.notes && <span className="muted">{h.notes}</span>}
            </span>
            <span>{h.cost_cents > 0 ? kes(h.cost_cents) : ""}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}
