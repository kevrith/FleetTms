import type { FloatTransfer, FuelEntry, StaffProfile, Vehicle } from "@fleettms/types";
import { formatKes, kesToCents } from "@fleettms/business-rules";
import { Send } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { FUEL_FLAG, fmtTime } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";
import ExpenseList from "./ExpenseList";
import Limits from "./Limits";
import Reconciliations from "./Reconciliations";

function Floats() {
  const { can } = useAuth();
  const manage = can("floats.manage");
  const [rows, setRows] = useState<FloatTransfer[]>([]);
  const [staff, setStaff] = useState<StaffProfile[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ driver: "", kes: "", code: "", note: "" });

  const load = useCallback(async () => {
    try {
      setRows(await api.floats());
      if (can("staff.view")) setStaff(await api.staff());
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [can]);
  useEffect(() => {
    void load();
  }, [load]);

  async function send(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.sendFloat({
        driver_membership_id: form.driver,
        amount_cents: kesToCents(Number(form.kes)),
        mpesa_code: form.code.trim() || null,
        note: form.note.trim() || null,
      });
      setForm({ ...form, kes: "", code: "", note: "" });
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const crew = staff.filter((s) => s.roles.includes("driver") || s.roles.includes("turnboy"));
  const name = (id: string) => staff.find((s) => s.membership_id === id)?.name ?? "Driver";
  const balances = new Map<string, number>();
  for (const r of rows)
    balances.set(
      r.driver_membership_id,
      (balances.get(r.driver_membership_id) ?? 0) + r.amount_cents,
    );

  return (
    <>
      <ErrorBanner message={error} />
      {manage && (
        <Card title="Record a float">
          <p className="muted">
            Send the money by M-Pesa as usual, then record it here so the driver's balance is right.
          </p>
          <form onSubmit={send} className="form-grid">
            <Field label="Driver or turnboy">
              <select
                value={form.driver}
                onChange={(e) => setForm({ ...form, driver: e.target.value })}
                required
              >
                <option value="">Choose...</option>
                {crew.map((s) => (
                  <option key={s.membership_id} value={s.membership_id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Amount (KES)">
              <input
                type="number"
                min="1"
                step="0.01"
                value={form.kes}
                onChange={(e) => setForm({ ...form, kes: e.target.value })}
                required
              />
            </Field>
            <Field label="M-Pesa code">
              <input
                value={form.code}
                onChange={(e) => setForm({ ...form, code: e.target.value })}
                placeholder="QGH7XYZ123"
                maxLength={10}
              />
            </Field>
            <Field label="What is it for?">
              <input
                value={form.note}
                onChange={(e) => setForm({ ...form, note: e.target.value })}
              />
            </Field>
            <button className="btn primary">
              <Send size={16} /> Record float
            </button>
          </form>
        </Card>
      )}
      <Card title="Floats sent">
        {rows.length === 0 && <p className="muted">No floats recorded yet.</p>}
        {rows.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>When</th>
                  <th>Driver</th>
                  <th>Amount</th>
                  <th>M-Pesa code</th>
                  <th>For</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td>{fmtTime(r.sent_at)}</td>
                    <td>{name(r.driver_membership_id)}</td>
                    <td>{formatKes(r.amount_cents)}</td>
                    <td>{r.mpesa_code}</td>
                    <td>{r.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {balances.size > 0 && (
        <Card title="Total sent per driver">
          <ul className="list">
            {[...balances].map(([id, cents]) => (
              <li key={id}>
                <span>{name(id)}</span>
                <strong>{formatKes(cents)}</strong>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}

function Fuel() {
  const [rows, setRows] = useState<FuelEntry[]>([]);
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.fuel(), api.vehicles()])
      .then(([f, v]) => {
        setRows(f);
        setVehicles(v);
      })
      .catch((e) => setError(errorMessage(e)));
  }, []);

  const reg = (id: string) => vehicles.find((v) => v.id === id)?.registration ?? "";
  return (
    <>
      <ErrorBanner message={error} />
      <Card title="Fuel purchases">
        {rows.length === 0 && <p className="muted">No fuel recorded yet.</p>}
        {rows.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>When</th>
                  <th>Vehicle</th>
                  <th>Litres</th>
                  <th>Price per litre</th>
                  <th>Amount</th>
                  <th>Station</th>
                  <th>M-Pesa code</th>
                  <th>Checks</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td>{fmtTime(r.captured_at)}</td>
                    <td>{reg(r.vehicle_id)}</td>
                    <td>{r.litres}</td>
                    <td>{formatKes(r.price_per_litre_cents)}</td>
                    <td>{formatKes(r.amount_cents)}</td>
                    <td>{r.station}</td>
                    <td>{r.mpesa_code}</td>
                    <td>
                      {r.flags.length === 0 && <span className="status ok">Fine</span>}
                      {r.flags.map((f) => (
                        <p key={f} className="status warn">
                          {FUEL_FLAG[f] ?? f}
                        </p>
                      ))}
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

export default function Expenses() {
  const { can } = useAuth();
  const tabs = [
    { to: "expenses", label: "Expenses", show: can("expenses.view") },
    {
      to: "reconciliation",
      label: "Reconciliation",
      show: can("reconciliations.approve") || can("finance.view"),
    },
    { to: "floats", label: "Floats", show: can("floats.manage") || can("finance.view") },
    { to: "fuel", label: "Fuel", show: can("vehicles.view") },
    { to: "limits", label: "Limits and routes", show: can("expenses.view") },
  ].filter((t) => t.show);
  return (
    <>
      <h2>Expenses</h2>
      <nav className="tabs">
        {tabs.map((t) => (
          <NavLink key={t.to} to={t.to}>
            {t.label}
          </NavLink>
        ))}
      </nav>
      <Routes>
        <Route index element={<Navigate to={tabs[0]?.to ?? "floats"} replace />} />
        <Route path="expenses" element={<ExpenseList />} />
        <Route path="reconciliation" element={<Reconciliations />} />
        <Route path="limits" element={<Limits />} />
        <Route path="floats" element={<Floats />} />
        <Route path="fuel" element={<Fuel />} />
      </Routes>
    </>
  );
}
