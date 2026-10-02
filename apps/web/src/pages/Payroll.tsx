import type { PayrollRun, SalaryAdvance } from "@fleettms/types";
import { Check, Plus } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { kes, todayIso } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";
import Staff from "./Staff";

const toCents = (kesText: string) => Math.round(Number(kesText || 0) * 100);
const STATUS = { draft: "Draft", approved: "Approved", paid: "Paid" } as const;
const monthName = (iso: string) =>
  new Date(iso).toLocaleDateString("en-KE", { month: "long", year: "numeric", timeZone: "UTC" });

function Runs() {
  const { can } = useAuth();
  const manage = can("payroll.manage");
  const [runs, setRuns] = useState<PayrollRun[]>([]);
  const [open, setOpen] = useState<PayrollRun | null>(null);
  const [month, setMonth] = useState(todayIso().slice(0, 7));
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setRuns(await api.payrollRuns());
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  async function act(action: () => Promise<PayrollRun>, done: string) {
    setError(null);
    setMessage(null);
    try {
      setOpen(await action());
      setMessage(done);
      await load();
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  return (
    <>
      <ErrorBanner message={error} />
      {message && <p className="banner ok">{message}</p>}
      <Card title="Payroll runs">
        {runs.length === 0 && <p className="muted">No payroll runs yet.</p>}
        {runs.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Month</th>
                  <th>People</th>
                  <th>Salaries</th>
                  <th>Taken off</th>
                  <th>To pay</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.id}>
                    <td>{monthName(r.month)}</td>
                    <td>{r.people}</td>
                    <td>{kes(r.gross_cents)}</td>
                    <td>{kes(r.deductions_cents)}</td>
                    <td>{kes(r.net_cents)}</td>
                    <td>{STATUS[r.status]}</td>
                    <td>
                      <button className="btn" onClick={() => act(() => api.payrollRun(r.id), "")}>
                        Open
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {manage && (
          <div className="form-grid">
            <Field label="Start a run for">
              <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} />
            </Field>
            <button
              className="btn primary"
              onClick={() => act(() => api.createPayrollRun(`${month}-01`), "Draft run made.")}
            >
              <Plus size={16} /> Start the run
            </button>
          </div>
        )}
        <p className="muted">
          Each person's salary is the monthly salary on their staff record. Advances are taken back
          in full, and fines marked for payroll are taken from a driver's pay, but never more than
          the salary.
        </p>
      </Card>
      {open && (
        <Card title={`${monthName(open.month)}: ${STATUS[open.status].toLowerCase()}`}>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Person</th>
                  <th>Salary</th>
                  <th>Advances</th>
                  <th>Fines</th>
                  <th>To pay</th>
                  <th>Cost spread over</th>
                </tr>
              </thead>
              <tbody>
                {(open.lines ?? []).map((l) => (
                  <tr key={l.id}>
                    <td>{l.name}</td>
                    <td>{kes(l.gross_cents)}</td>
                    <td>{l.advances_cents ? kes(l.advances_cents) : ""}</td>
                    <td>{l.fines_cents ? kes(l.fines_cents) : ""}</td>
                    <td>
                      <strong>{kes(l.net_cents)}</strong>
                    </td>
                    <td>
                      {l.allocation
                        .map((a) => `${a.registration ?? "the business"} ${kes(a.cents)}`)
                        .join(", ")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {manage && (
            <p className="actions">
              {open.status === "draft" && (
                <>
                  <button
                    className="btn"
                    onClick={() => act(() => api.recalculatePayroll(open.id), "Worked out again.")}
                  >
                    Work out again
                  </button>{" "}
                  <button
                    className="btn primary"
                    onClick={() => {
                      if (
                        window.confirm(
                          "Approve this run? Advances and fines are taken off for good.",
                        )
                      )
                        void act(() => api.approvePayroll(open.id), "Approved.");
                    }}
                  >
                    <Check size={16} /> Approve
                  </button>
                </>
              )}
              {open.status === "approved" && (
                <button
                  className="btn primary"
                  onClick={() => act(() => api.payPayroll(open.id), "Marked as paid.")}
                >
                  Mark as paid
                </button>
              )}
            </p>
          )}
        </Card>
      )}
    </>
  );
}

function Advances() {
  const { can } = useAuth();
  const [rows, setRows] = useState<SalaryAdvance[]>([]);
  const [people, setPeople] = useState<{ membership_id: string; name: string | null }[]>([]);
  const [form, setForm] = useState({ membership_id: "", amount: "", note: "", code: "" });
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setRows(await api.advances());
      setPeople(await api.salaried());
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  return (
    <>
      <ErrorBanner message={error} />
      <Card title="Salary advances">
        {rows.length === 0 && <p className="muted">No advances yet.</p>}
        <ul className="list">
          {rows.map((a) => (
            <li key={a.id}>
              <span>
                {a.given_on}, {a.name}
                {a.note && `, ${a.note}`}
              </span>
              <span>
                {kes(a.amount_cents)}
                {a.remaining_cents > 0
                  ? `, ${kes(a.remaining_cents)} still to take back`
                  : ", taken back"}
              </span>
            </li>
          ))}
        </ul>
        {can("payroll.manage") && (
          <div className="form-grid">
            <Field label="Who">
              <select
                value={form.membership_id}
                onChange={(e) => setForm({ ...form, membership_id: e.target.value })}
              >
                <option value="">Choose a person</option>
                {people.map((p) => (
                  <option key={p.membership_id} value={p.membership_id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Amount (KES)">
              <input
                type="number"
                min="0"
                step="0.01"
                value={form.amount}
                onChange={(e) => setForm({ ...form, amount: e.target.value })}
              />
            </Field>
            <Field label="M-Pesa code">
              <input
                value={form.code}
                onChange={(e) => setForm({ ...form, code: e.target.value })}
              />
            </Field>
            <Field label="Note">
              <input
                value={form.note}
                onChange={(e) => setForm({ ...form, note: e.target.value })}
              />
            </Field>
            <button
              className="btn primary"
              disabled={!form.membership_id || !(Number(form.amount) > 0)}
              onClick={async () => {
                setError(null);
                try {
                  await api.giveAdvance({
                    membership_id: form.membership_id,
                    amount_cents: toCents(form.amount),
                    note: form.note || null,
                    mpesa_code: form.code || null,
                  });
                  setForm({ membership_id: "", amount: "", note: "", code: "" });
                  await load();
                } catch (e) {
                  setError(errorMessage(e));
                }
              }}
            >
              Give advance
            </button>
          </div>
        )}
      </Card>
    </>
  );
}

/** Staff and payroll. */
export default function StaffArea() {
  const { can } = useAuth();
  return (
    <>
      <nav className="tabs">
        <NavLink to="/staff" end>
          People
        </NavLink>
        {can("payroll.view") && <NavLink to="/staff/payroll">Payroll</NavLink>}
        {can("payroll.view") && <NavLink to="/staff/advances">Advances</NavLink>}
      </nav>
      <Routes>
        <Route index element={<Staff />} />
        {can("payroll.view") && <Route path="payroll" element={<Runs />} />}
        {can("payroll.view") && <Route path="advances" element={<Advances />} />}
      </Routes>
    </>
  );
}
