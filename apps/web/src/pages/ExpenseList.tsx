import type { Expense, ExpenseCategory, StaffProfile, Vehicle } from "@fleettms/types";
import { Check, Plus, X } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { EXPENSE_CATEGORY, EXPENSE_FLAG, EXPENSE_STATUS, fmtTime, kes } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

export default function ExpenseList() {
  const { can } = useAuth();
  const [rows, setRows] = useState<Expense[]>([]);
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [staff, setStaff] = useState<StaffProfile[]>([]);
  const [status, setStatus] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({
    category: "repair",
    vehicle: "",
    kes: "",
    note: "",
    code: "",
    driver: "",
  });

  const load = useCallback(async () => {
    try {
      setRows(await api.expenses({ status: status || undefined }));
      setVehicles(await api.vehicles().catch(() => []));
      if (can("staff.view")) setStaff(await api.staff());
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [status, can]);
  useEffect(() => {
    void load();
  }, [load]);

  async function decide(e: Expense, approve: boolean) {
    const note =
      window.prompt(approve ? "Note for the record (optional)" : "Why are you rejecting it?") ?? "";
    if (!approve && !note.trim()) return;
    try {
      await api.decideExpense(e.id, approve, note.trim() || undefined);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function add(ev: FormEvent) {
    ev.preventDefault();
    setError(null);
    try {
      await api.addExpense({
        category: form.category as ExpenseCategory,
        amount_cents: Math.round(Number(form.kes) * 100),
        vehicle_id: form.vehicle || null,
        note: form.note.trim() || null,
        mpesa_code: form.code.trim() || null,
        driver_membership_id: form.driver || null,
        from_float: form.driver ? true : null,
      });
      setForm({ ...form, kes: "", note: "", code: "" });
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const reg = (id: string | null) => vehicles.find((v) => v.id === id)?.registration ?? "";
  const crew = staff.filter((s) => s.roles.includes("driver") || s.roles.includes("turnboy"));
  return (
    <>
      <ErrorBanner message={error} />
      {can("expenses.manage") && (
        <Card title="Record an expense">
          <form onSubmit={add} className="form-grid">
            <Field label="Type">
              <select
                value={form.category}
                onChange={(e) => setForm({ ...form, category: e.target.value })}
              >
                {Object.entries(EXPENSE_CATEGORY).map(([k, label]) => (
                  <option key={k} value={k}>
                    {label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Vehicle">
              <select
                value={form.vehicle}
                onChange={(e) => setForm({ ...form, vehicle: e.target.value })}
              >
                <option value="">None (overhead)</option>
                {vehicles.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.registration}
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
            <Field label="Note">
              <input
                value={form.note}
                onChange={(e) => setForm({ ...form, note: e.target.value })}
              />
            </Field>
            <Field label="M-Pesa code">
              <input
                value={form.code}
                onChange={(e) => setForm({ ...form, code: e.target.value })}
                maxLength={10}
              />
            </Field>
            {crew.length > 0 && (
              <Field label="Paid from a driver's float (optional)">
                <select
                  value={form.driver}
                  onChange={(e) => setForm({ ...form, driver: e.target.value })}
                >
                  <option value="">No, paid by the business</option>
                  {crew.map((s) => (
                    <option key={s.membership_id} value={s.membership_id}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </Field>
            )}
            <button className="btn primary">
              <Plus size={16} /> Record expense
            </button>
          </form>
        </Card>
      )}
      <Card title="Expenses">
        <p>
          <label className="field" style={{ maxWidth: 260 }}>
            <span>Show</span>
            <select value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">Everything</option>
              {Object.entries(EXPENSE_STATUS).map(([k, label]) => (
                <option key={k} value={k}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        </p>
        {rows.length === 0 && <p className="muted">No expenses to show.</p>}
        {rows.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>When</th>
                  <th>Type</th>
                  <th>Vehicle</th>
                  <th>Amount</th>
                  <th>Status</th>
                  <th>Checks</th>
                  <th>Receipt</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td>{fmtTime(r.spent_at)}</td>
                    <td>
                      {EXPENSE_CATEGORY[r.category]}
                      {r.note && <span className="muted"> {r.note}</span>}
                    </td>
                    <td>{reg(r.vehicle_id)}</td>
                    <td>{kes(r.amount_cents)}</td>
                    <td>
                      <span
                        className={`status ${r.status === "awaiting_approval" ? "warn" : r.status === "rejected" ? "bad" : "ok"}`}
                      >
                        {EXPENSE_STATUS[r.status]}
                      </span>
                    </td>
                    <td>
                      {r.flags.map((f) => (
                        <p key={f} className="status warn">
                          {EXPENSE_FLAG[f] ?? f}
                        </p>
                      ))}
                    </td>
                    <td>
                      {r.receipt ? (
                        <a href={api.mediaUrl(r.receipt.url)} target="_blank" rel="noreferrer">
                          <img src={api.mediaUrl(r.receipt.url)} alt="Receipt" height={40} />
                        </a>
                      ) : (
                        r.mpesa_code
                      )}
                    </td>
                    <td>
                      {r.status === "awaiting_approval" && can("expenses.approve_limit") && (
                        <span className="actions">
                          <button className="btn" onClick={() => decide(r, true)}>
                            <Check size={16} /> Approve
                          </button>
                          <button className="btn danger" onClick={() => decide(r, false)}>
                            <X size={16} /> Reject
                          </button>
                        </span>
                      )}
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
