import type { OwnershipCost, Vehicle } from "@fleettms/types";
import { Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { kes, todayIso } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

const toCents = (kesText: string) => Math.round(Number(kesText || 0) * 100);
const KIND = {
  insurance: "Insurance",
  licence: "Licence",
  depreciation: "Depreciation",
  other: "Other",
} as const;

/** Fixed costs of owning a lorry, spread evenly across months so every month carries its share. */
export function OwnershipCosts() {
  const { can } = useAuth();
  const [rows, setRows] = useState<OwnershipCost[]>([]);
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [form, setForm] = useState({
    vehicle_id: "",
    kind: "insurance" as OwnershipCost["kind"],
    name: "",
    amount: "",
    period: "year" as "year" | "month",
    salvage: "",
    life: "60",
    start: todayIso(),
  });
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setRows(await api.ownershipCosts());
      setVehicles(await api.vehicles());
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  const dep = form.kind === "depreciation";
  async function add(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.addOwnershipCost({
        vehicle_id: form.vehicle_id,
        kind: form.kind,
        name: form.name || KIND[form.kind],
        amount_cents: toCents(form.amount),
        period: dep ? "month" : form.period,
        salvage_cents: dep ? toCents(form.salvage) : 0,
        life_months: dep ? Number(form.life) : null,
        start_date: form.start,
      });
      setForm({ ...form, name: "", amount: "", salvage: "" });
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }
  return (
    <>
      <ErrorBanner message={error} />
      <Card title="Ownership costs">
        <p className="muted">
          An insurance premium paid once a year is counted as a twelfth each month, and depreciation
          spreads what a lorry cost, less what it will be worth, over its life. An insurance or
          licence expense for a lorry that has one of these set up is not counted again.
        </p>
        {rows.length === 0 && <p className="muted">None yet.</p>}
        {rows.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Vehicle</th>
                  <th>Cost</th>
                  <th>Amount</th>
                  <th>A month</th>
                  <th>From</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((o) => (
                  <tr key={o.id}>
                    <td>{o.registration}</td>
                    <td>{o.name}</td>
                    <td>
                      {kes(o.amount_cents)}
                      {o.kind === "depreciation"
                        ? ` over ${o.life_months} months`
                        : ` a ${o.period}`}
                    </td>
                    <td>{kes(o.monthly_cents)}</td>
                    <td>{o.start_date}</td>
                    <td>
                      {can("leases.manage") && (
                        <button
                          className="btn danger"
                          aria-label="Delete"
                          onClick={async () => {
                            if (!window.confirm("Delete this cost?")) return;
                            try {
                              await api.deleteOwnershipCost(o.id);
                              await load();
                            } catch (e) {
                              setError(errorMessage(e));
                            }
                          }}
                        >
                          <Trash2 size={16} />
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {can("leases.manage") && (
        <Card title="Add an ownership cost">
          <form onSubmit={add}>
            <div className="form-grid">
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
              <Field label="Kind">
                <select
                  value={form.kind}
                  onChange={(e) =>
                    setForm({ ...form, kind: e.target.value as OwnershipCost["kind"] })
                  }
                >
                  {Object.entries(KIND).map(([k, label]) => (
                    <option key={k} value={k}>
                      {label}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Name">
                <input
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder={KIND[form.kind]}
                />
              </Field>
              <Field label={dep ? "What the lorry cost (KES)" : "Amount (KES)"}>
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={form.amount}
                  onChange={(e) => setForm({ ...form, amount: e.target.value })}
                  required
                />
              </Field>
              {!dep && (
                <Field label="That amount is per">
                  <select
                    value={form.period}
                    onChange={(e) =>
                      setForm({ ...form, period: e.target.value as "year" | "month" })
                    }
                  >
                    <option value="year">Year</option>
                    <option value="month">Month</option>
                  </select>
                </Field>
              )}
              {dep && (
                <>
                  <Field label="Worth at the end (KES)">
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      value={form.salvage}
                      onChange={(e) => setForm({ ...form, salvage: e.target.value })}
                    />
                  </Field>
                  <Field label="Life (months)">
                    <input
                      type="number"
                      min="1"
                      value={form.life}
                      onChange={(e) => setForm({ ...form, life: e.target.value })}
                    />
                  </Field>
                </>
              )}
              <Field label="From">
                <input
                  type="date"
                  value={form.start}
                  onChange={(e) => setForm({ ...form, start: e.target.value })}
                  required
                />
              </Field>
            </div>
            <p className="actions">
              <button className="btn primary" type="submit">
                <Plus size={16} /> Save
              </button>
            </p>
          </form>
        </Card>
      )}
    </>
  );
}
