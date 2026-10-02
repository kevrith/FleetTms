import { financeSchedule } from "@fleettms/business-rules";
import type { FinanceAgreement, Vehicle } from "@fleettms/types";
import { Plus } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { kes, todayIso } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

const toCents = (kesText: string) => Math.round(Number(kesText || 0) * 100);

/** Loans on lorries: the schedule is worked out once, then repayments are ticked off. */
export function LoanList() {
  const { can } = useAuth();
  const [rows, setRows] = useState<FinanceAgreement[]>([]);
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [form, setForm] = useState({
    vehicle_id: "",
    principal: "",
    rate: "12",
    months: "36",
    first_due: todayIso(),
    instalment: "",
    reference: "",
  });
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setRows(await api.loans());
      setVehicles(await api.vehicles());
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  const financed = vehicles.filter((v) => v.ownership_type === "asset_financed");
  const principal = toCents(form.principal);
  const months = Number(form.months);
  const preview =
    principal > 0 && months >= 1 && months <= 120
      ? financeSchedule(
          principal,
          Number(form.rate || 0),
          months,
          form.first_due,
          form.instalment ? toCents(form.instalment) : null,
        )
      : [];
  async function add(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const v = vehicles.find((x) => x.id === form.vehicle_id);
    if (!v?.party_id) return setError("That vehicle has no lender set.");
    try {
      await api.createLoan({
        vehicle_id: v.id,
        party_id: v.party_id,
        principal_cents: principal,
        annual_rate_pct: Number(form.rate || 0),
        months,
        first_due: form.first_due,
        instalment_cents: form.instalment ? toCents(form.instalment) : null,
        reference: form.reference || null,
      });
      setForm({ ...form, principal: "", instalment: "", reference: "" });
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }
  return (
    <>
      <ErrorBanner message={error} />
      <Card title="Loans">
        {rows.length === 0 && <p className="muted">No loans yet.</p>}
        {rows.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Vehicle</th>
                  <th>Lender</th>
                  <th>Repayment</th>
                  <th>Still owed (loan)</th>
                  <th>Overdue</th>
                  <th>Next due</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((f) => (
                  <tr key={f.id}>
                    <td>
                      <Link to={f.id}>{f.registration}</Link>
                    </td>
                    <td>{f.party_name}</td>
                    <td>{kes(f.instalment_cents)} a month</td>
                    <td>{kes(f.principal_balance_cents)}</td>
                    <td>{f.overdue_cents > 0 ? kes(f.overdue_cents) : ""}</td>
                    <td>{f.status === "closed" ? "Paid off" : (f.next_due_date ?? "")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {can("leases.manage") && (
        <Card title="Add a loan">
          <form onSubmit={add}>
            <div className="form-grid">
              <Field label="Vehicle (asset-financed)">
                <select
                  value={form.vehicle_id}
                  onChange={(e) => setForm({ ...form, vehicle_id: e.target.value })}
                  required
                >
                  <option value="">Choose a vehicle</option>
                  {financed.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.registration}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Amount borrowed (KES)">
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={form.principal}
                  onChange={(e) => setForm({ ...form, principal: e.target.value })}
                  required
                />
              </Field>
              <Field label="Interest a year (%)">
                <input
                  type="number"
                  min="0"
                  max="100"
                  step="0.01"
                  value={form.rate}
                  onChange={(e) => setForm({ ...form, rate: e.target.value })}
                />
              </Field>
              <Field label="Months to repay">
                <input
                  type="number"
                  min="1"
                  max="120"
                  value={form.months}
                  onChange={(e) => setForm({ ...form, months: e.target.value })}
                />
              </Field>
              <Field label="First repayment due">
                <input
                  type="date"
                  value={form.first_due}
                  onChange={(e) => setForm({ ...form, first_due: e.target.value })}
                  required
                />
              </Field>
              <Field label="Monthly repayment from the lender (KES, optional)">
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={form.instalment}
                  onChange={(e) => setForm({ ...form, instalment: e.target.value })}
                />
              </Field>
              <Field label="Loan reference">
                <input
                  value={form.reference}
                  onChange={(e) => setForm({ ...form, reference: e.target.value })}
                />
              </Field>
            </div>
            {financed.length === 0 && (
              <p className="muted">
                No vehicle is set as asset-financed yet. Set its ownership and lender first.
              </p>
            )}
            {preview.length > 0 && (
              <p className="muted">
                That is {kes(preview[0]!.amount_cents)} a month. In all you repay{" "}
                {kes(preview.reduce((a, r) => a + r.amount_cents, 0))}, of which{" "}
                {kes(preview.reduce((a, r) => a + r.interest_cents, 0))} is interest.
              </p>
            )}
            <p className="actions">
              <button className="btn primary" type="submit">
                <Plus size={16} /> Save loan
              </button>
            </p>
          </form>
        </Card>
      )}
    </>
  );
}

export function LoanDetail() {
  const { id } = useParams();
  const { can } = useAuth();
  const [loan, setLoan] = useState<FinanceAgreement | null>(null);
  const [pay, setPay] = useState({
    method: "mpesa" as "mpesa" | "bank" | "cash" | "cheque",
    code: "",
  });
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setLoan(await api.loan(id!));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [id]);
  useEffect(() => {
    void load();
  }, [load]);
  if (!loan) return <ErrorBanner message={error} />;
  return (
    <>
      <p>
        <Link to="/leases/finance">Back to loans</Link>
      </p>
      <ErrorBanner message={error} />
      <Card title={`${loan.registration}: loan from ${loan.party_name}`}>
        <p>
          {kes(loan.principal_cents)} at {loan.annual_rate_pct}% over {loan.months} months,{" "}
          {kes(loan.instalment_cents)} a month. Still owed on the loan:{" "}
          <strong>{kes(loan.principal_balance_cents)}</strong>. Remaining repayments with interest:{" "}
          {kes(loan.outstanding_cents)}.
          {loan.overdue_cents > 0 && (
            <span className="status bad"> {kes(loan.overdue_cents)} is overdue.</span>
          )}
        </p>
        {can("leases.manage") && (
          <div className="form-grid">
            <Field label="Pay by">
              <select
                value={pay.method}
                onChange={(e) => setPay({ ...pay, method: e.target.value as typeof pay.method })}
              >
                <option value="mpesa">M-Pesa</option>
                <option value="bank">Bank</option>
                <option value="cash">Cash</option>
                <option value="cheque">Cheque</option>
              </select>
            </Field>
            <Field label="M-Pesa code (optional)">
              <input value={pay.code} onChange={(e) => setPay({ ...pay, code: e.target.value })} />
            </Field>
          </div>
        )}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Due</th>
                <th>Repayment</th>
                <th>Interest</th>
                <th>Paid</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {(loan.schedule ?? []).map((r) => (
                <tr key={r.number}>
                  <td>{r.number}</td>
                  <td>
                    {r.due_date} {r.overdue && <span className="status bad">overdue</span>}
                  </td>
                  <td>{kes(r.amount_cents)}</td>
                  <td>{kes(r.interest_cents)}</td>
                  <td>
                    {r.paid_cents > 0
                      ? `${kes(r.paid_cents)}${r.paid_on ? `, ${r.paid_on}` : ""}`
                      : ""}
                  </td>
                  <td>
                    {can("leases.manage") && r.paid_cents < r.amount_cents && (
                      <button
                        className="btn"
                        onClick={async () => {
                          setError(null);
                          try {
                            setLoan(
                              await api.repayLoan(loan.id, r.number, {
                                method: pay.method,
                                mpesa_code: pay.code || null,
                              }),
                            );
                            setPay({ ...pay, code: "" });
                          } catch (e) {
                            setError(errorMessage(e));
                          }
                        }}
                      >
                        Mark paid
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
