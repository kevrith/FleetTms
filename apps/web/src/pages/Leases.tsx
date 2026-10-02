import type { LeaseAgreement, LeaseDetail, LeaseStatement, Party, Vehicle } from "@fleettms/types";
import { Download, Plus, Send } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, NavLink, Route, Routes, useParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { kes, todayIso } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";
import { LoanDetail, LoanList } from "./Loans";
import { OwnershipCosts } from "./OwnershipCosts";
import { ProfitPage } from "./Profit";

const toCents = (kesText: string) => Math.round(Number(kesText || 0) * 100);
const monthStart = (day: string) => `${day.slice(0, 7)}-01`;
const PERIOD = { month: "a month", week: "a week", day: "a day" } as const;

/** What a lease charges, in words. */
export function terms(a: LeaseAgreement): string {
  const parts: string[] = [];
  if (a.fixed_cents && a.fixed_period)
    parts.push(`${kes(a.fixed_cents)} ${PERIOD[a.fixed_period]}`);
  if (a.per_trip_cents) parts.push(`${kes(a.per_trip_cents)} a trip`);
  if (a.per_km_cents) parts.push(`${kes(a.per_km_cents)} a km`);
  if (a.revenue_pct) parts.push(`${a.revenue_pct}% of revenue`);
  if (a.profit_pct) parts.push(`${a.profit_pct}% of profit`);
  const text = parts.join(" plus ");
  return a.min_guarantee_cents
    ? `${text ? text + ", " : ""}at least ${kes(a.min_guarantee_cents)} a month`
    : text;
}

interface Form {
  direction: "in" | "out";
  vehicle_id: string;
  start_date: string;
  end_date: string;
  deposit: string;
  fixed: string;
  fixed_period: "month" | "week" | "day";
  per_trip: string;
  per_km: string;
  revenue_pct: string;
  profit_pct: string;
  guarantee: string;
  payment_due_days: string;
  notice_days: string;
  share_trips: boolean;
  notes: string;
  responsibilities: Record<string, "lessee" | "lessor">;
}

const emptyForm = (defaults: Record<string, "lessee" | "lessor">): Form => ({
  direction: "in",
  vehicle_id: "",
  start_date: todayIso(),
  end_date: "",
  deposit: "",
  fixed: "",
  fixed_period: "month",
  per_trip: "",
  per_km: "",
  revenue_pct: "",
  profit_pct: "",
  guarantee: "",
  payment_due_days: "7",
  notice_days: "30",
  share_trips: false,
  notes: "",
  responsibilities: defaults,
});

const formFrom = (a: LeaseAgreement): Form => ({
  direction: a.direction,
  vehicle_id: a.vehicle_id,
  start_date: a.start_date,
  end_date: a.end_date ?? "",
  deposit: a.deposit_cents ? String(a.deposit_cents / 100) : "",
  fixed: a.fixed_cents ? String(a.fixed_cents / 100) : "",
  fixed_period: a.fixed_period ?? "month",
  per_trip: a.per_trip_cents ? String(a.per_trip_cents / 100) : "",
  per_km: a.per_km_cents ? String(a.per_km_cents / 100) : "",
  revenue_pct: a.revenue_pct ? String(a.revenue_pct) : "",
  profit_pct: a.profit_pct ? String(a.profit_pct) : "",
  guarantee: a.min_guarantee_cents ? String(a.min_guarantee_cents / 100) : "",
  payment_due_days: String(a.payment_due_days),
  notice_days: String(a.notice_days),
  share_trips: a.share_trips,
  notes: a.notes ?? "",
  responsibilities: a.responsibilities,
});

function payload(f: Form, party_id: string) {
  return {
    direction: f.direction,
    vehicle_id: f.vehicle_id,
    party_id,
    start_date: f.start_date,
    end_date: f.end_date || null,
    deposit_cents: toCents(f.deposit),
    fixed_cents: toCents(f.fixed),
    fixed_period: f.fixed ? f.fixed_period : null,
    per_trip_cents: toCents(f.per_trip),
    per_km_cents: toCents(f.per_km),
    revenue_pct: Number(f.revenue_pct || 0),
    profit_pct: Number(f.profit_pct || 0),
    min_guarantee_cents: toCents(f.guarantee),
    payment_due_days: Number(f.payment_due_days || 7),
    notice_days: Number(f.notice_days || 30),
    share_trips: f.share_trips,
    notes: f.notes || null,
    responsibilities: f.responsibilities,
  };
}

function LeaseForm({
  f,
  set,
  vehicles,
  items,
  locked,
}: {
  f: Form;
  set: (f: Form) => void;
  vehicles: Vehicle[];
  items: Record<string, string>;
  locked?: boolean;
}) {
  const on = (k: keyof Form) => (e: { target: { value: string } }) =>
    set({ ...f, [k]: e.target.value });
  const fits = vehicles.filter(
    (v) => v.ownership_type === (f.direction === "in" ? "leased_in" : "leased_out"),
  );
  return (
    <>
      <div className="form-grid">
        <Field label="Direction">
          <select
            value={f.direction}
            disabled={locked}
            onChange={(e) =>
              set({ ...f, direction: e.target.value as "in" | "out", vehicle_id: "" })
            }
          >
            <option value="in">Leased in (we hire a lorry from its owner)</option>
            <option value="out">Leased out (someone hires our lorry)</option>
          </select>
        </Field>
        <Field label="Vehicle">
          <select value={f.vehicle_id} disabled={locked} onChange={on("vehicle_id")} required>
            <option value="">Choose a vehicle</option>
            {fits.map((v) => (
              <option key={v.id} value={v.id}>
                {v.registration}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Starts">
          <input type="date" value={f.start_date} onChange={on("start_date")} required />
        </Field>
        <Field label="Ends (blank if open-ended)">
          <input type="date" value={f.end_date} onChange={on("end_date")} />
        </Field>
        <Field label="Security deposit (KES)">
          <input type="number" min="0" step="0.01" value={f.deposit} onChange={on("deposit")} />
        </Field>
        <Field label="Notice period (days)">
          <input type="number" min="0" value={f.notice_days} onChange={on("notice_days")} />
        </Field>
      </div>
      {fits.length === 0 && (
        <p className="muted">
          No vehicle is set as {f.direction === "in" ? "leased-in" : "leased-out"} yet. Set the
          vehicle's ownership and its {f.direction === "in" ? "lessor" : "lessee"} first.
        </p>
      )}
      <h4>What the lease charges</h4>
      <p className="muted">
        Fill in one or more. The parts add up. A minimum is a floor under the total, so "at least
        120,000 or 30% of revenue, whichever is higher" is a minimum of 120,000 and a revenue share
        of 30%.
      </p>
      <div className="form-grid">
        <Field label="Fixed amount (KES)">
          <input type="number" min="0" step="0.01" value={f.fixed} onChange={on("fixed")} />
        </Field>
        <Field label="Fixed amount is per">
          <select value={f.fixed_period} onChange={on("fixed_period")}>
            <option value="month">Month</option>
            <option value="week">Week</option>
            <option value="day">Day</option>
          </select>
        </Field>
        <Field label="Per trip (KES)">
          <input type="number" min="0" step="0.01" value={f.per_trip} onChange={on("per_trip")} />
        </Field>
        <Field label="Per kilometre (KES)">
          <input type="number" min="0" step="0.01" value={f.per_km} onChange={on("per_km")} />
        </Field>
        <Field label="Share of revenue (%)">
          <input
            type="number"
            min="0"
            max="100"
            step="0.01"
            value={f.revenue_pct}
            onChange={on("revenue_pct")}
          />
        </Field>
        <Field label="Share of profit (%)">
          <input
            type="number"
            min="0"
            max="100"
            step="0.01"
            value={f.profit_pct}
            onChange={on("profit_pct")}
          />
        </Field>
        <Field label="Minimum a month (KES)">
          <input type="number" min="0" step="0.01" value={f.guarantee} onChange={on("guarantee")} />
        </Field>
        <Field label="Payment due (days after month end)">
          <input
            type="number"
            min="0"
            max="60"
            value={f.payment_due_days}
            onChange={on("payment_due_days")}
          />
        </Field>
      </div>
      <h4>Who pays for what</h4>
      <p className="muted">
        A cost the owner is responsible for, paid by you, comes off the next lease payment as an
        offset.
      </p>
      <div className="form-grid">
        {Object.entries(items).map(([key, label]) => (
          <Field key={key} label={label}>
            <select
              value={f.responsibilities[key] ?? "lessee"}
              onChange={(e) =>
                set({
                  ...f,
                  responsibilities: {
                    ...f.responsibilities,
                    [key]: e.target.value as "lessee" | "lessor",
                  },
                })
              }
            >
              <option value="lessee">
                {f.direction === "in" ? "We pay (lessee)" : "Lessee pays"}
              </option>
              <option value="lessor">
                {f.direction === "in" ? "The owner pays (lessor)" : "We pay (owner)"}
              </option>
            </select>
          </Field>
        ))}
      </div>
      {f.direction === "in" && (
        <label className="field">
          <span>
            <input
              type="checkbox"
              checked={f.share_trips}
              onChange={(e) => set({ ...f, share_trips: e.target.checked })}
            />{" "}
            The owner may see this lorry's trips on their statement
          </span>
        </label>
      )}
      <Field label="Notes">
        <input value={f.notes} onChange={on("notes")} />
      </Field>
    </>
  );
}

export function LeaseList() {
  const { can } = useAuth();
  const [rows, setRows] = useState<LeaseAgreement[]>([]);
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [items, setItems] = useState<Record<string, string>>({});
  const [form, setForm] = useState<Form | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setRows(await api.leases());
      setVehicles(await api.vehicles());
      const got = await api.leaseItems();
      setItems(got.items);
      setForm((f) => f ?? emptyForm(got.defaults));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  async function add(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const v = vehicles.find((x) => x.id === form!.vehicle_id);
    if (!v?.party_id) return setError("That vehicle has no lessor or lessee set.");
    try {
      await api.createLease(payload(form!, v.party_id));
      setForm(emptyForm((await api.leaseItems()).defaults));
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }
  const owedByUs = rows
    .filter((r) => r.direction === "in")
    .reduce((a, r) => a + (r.balance_cents ?? 0), 0);
  const owedToUs = rows
    .filter((r) => r.direction === "out")
    .reduce((a, r) => a + (r.balance_cents ?? 0), 0);
  return (
    <>
      <ErrorBanner message={error} />
      {message && <p className="banner ok">{message}</p>}
      <Card title="Leases">
        <p className="muted">
          We owe lessors {kes(owedByUs)}. Lessees owe us {kes(owedToUs)}.
        </p>
        {rows.length === 0 && <p className="muted">No leases yet.</p>}
        {rows.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Vehicle</th>
                  <th>With</th>
                  <th>Charges</th>
                  <th>Balance</th>
                  <th>Overdue</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((a) => (
                  <tr key={a.id}>
                    <td>
                      <Link to={`view/${a.id}`}>{a.registration}</Link>
                    </td>
                    <td>
                      {a.party_name} ({a.direction === "in" ? "lessor" : "lessee"})
                    </td>
                    <td>{terms(a)}</td>
                    <td>{kes(a.balance_cents ?? 0)}</td>
                    <td>{(a.overdue_cents ?? 0) > 0 ? kes(a.overdue_cents ?? 0) : ""}</td>
                    <td>{a.status === "active" ? "Running" : "Ended"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {can("leases.manage") && (
          <p className="actions">
            <button
              className="btn"
              onClick={async () => {
                setError(null);
                try {
                  const done = await api.runAllLeases(monthStart(todayIso()));
                  setMessage(
                    `This month's charges worked out for ${done.done} lease${done.done === 1 ? "" : "s"}.` +
                      (done.waiting_for_lessee_figures.length
                        ? ` ${done.waiting_for_lessee_figures.length} wait for the lessee's figures.`
                        : ""),
                  );
                  await load();
                } catch (e) {
                  setError(errorMessage(e));
                }
              }}
            >
              Work out this month's charges
            </button>
          </p>
        )}
      </Card>
      {can("leases.manage") && form && (
        <Card title="Add a lease">
          <form onSubmit={add}>
            <LeaseForm f={form} set={setForm} vehicles={vehicles} items={items} />
            <p className="actions">
              <button className="btn primary" type="submit">
                <Plus size={16} /> Save lease
              </button>
            </p>
          </form>
        </Card>
      )}
    </>
  );
}

export function LeaseDetailPage() {
  const { id } = useParams();
  const { can } = useAuth();
  const manage = can("leases.manage");
  const [lease, setLease] = useState<LeaseDetail | null>(null);
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [parties, setParties] = useState<Party[]>([]);
  const [items, setItems] = useState<Record<string, string>>({});
  const [edit, setEdit] = useState<Form | null>(null);
  const [month, setMonth] = useState(todayIso().slice(0, 7));
  const [statement, setStatement] = useState<LeaseStatement | null>(null);
  const [pay, setPay] = useState({
    amount: "",
    method: "mpesa" as "mpesa" | "bank" | "cash" | "cheque",
    code: "",
    reference: "",
  });
  const [adjust, setAdjust] = useState({ amount: "", reason: "" });
  const [reported, setReported] = useState({ trips: "", km: "", revenue: "", profit: "" });
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setLease(await api.lease(id!));
      setVehicles(await api.vehicles());
      setParties(await api.parties());
      setItems((await api.leaseItems()).items);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [id]);
  useEffect(() => {
    void load();
  }, [load]);
  async function run(action: () => Promise<unknown>, done?: string) {
    setError(null);
    setMessage(null);
    try {
      await action();
      if (done) setMessage(done);
      await load();
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  async function download() {
    try {
      const url = URL.createObjectURL(await api.leaseStatementPdf(id!, `${month}-01`));
      const a = document.createElement("a");
      a.href = url;
      a.download = `lease-${month}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  if (!lease) return <ErrorBanner message={error} />;
  const out = lease.direction === "out";
  const variable =
    lease.per_trip_cents || lease.per_km_cents || lease.revenue_pct || lease.profit_pct;
  const partyName = parties.find((p) => p.id === lease.party_id)?.name ?? lease.party_name;
  return (
    <>
      <p>
        <Link to="/leases">Back to leases</Link>
      </p>
      <ErrorBanner message={error} />
      {message && <p className="banner ok">{message}</p>}
      <Card
        title={`${lease.registration}: ${out ? "leased out to" : "leased in from"} ${partyName}`}
      >
        <p>
          {terms(lease)}. Runs from {lease.start_date}
          {lease.end_date ? ` to ${lease.end_date}` : ""}. Payment due {lease.payment_due_days} days
          after each month ends.
          {lease.deposit_cents > 0 && ` Deposit ${kes(lease.deposit_cents)}.`}
        </p>
        <p>
          <strong>
            {out ? "The lessee owes you" : "You owe the lessor"} {kes(lease.balance_cents ?? 0)}
          </strong>
          {(lease.overdue_cents ?? 0) > 0 && (
            <span className="status bad"> {kes(lease.overdue_cents ?? 0)} is overdue</span>
          )}
          {lease.next_due_date && <span className="muted"> Next due {lease.next_due_date}.</span>}
        </p>
        {lease.this_month && (
          <p className="muted">
            So far this month the charge would be {kes(lease.this_month.charge_cents)}
            {lease.this_month.guarantee_applied && " (the minimum applies)"}.
          </p>
        )}
        <p className="muted">
          {Object.entries(lease.responsibilities)
            .filter(([, who]) => who === "lessor")
            .map(([k]) => items[k] ?? k)
            .join(", ") || "Nothing"}{" "}
          {out ? "is paid by you (the owner)" : "is the lessor's cost"}.
        </p>
        {manage && lease.status === "active" && (
          <p className="actions">
            <button className="btn" onClick={() => setEdit(edit ? null : formFrom(lease))}>
              {edit ? "Close" : "Change the terms"}
            </button>{" "}
            <button
              className="btn danger"
              onClick={() => {
                if (window.confirm("End this lease today?"))
                  void run(() => api.endLease(lease.id), "Lease ended.");
              }}
            >
              End the lease
            </button>
          </p>
        )}
        {edit && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void run(async () => {
                await api.updateLease(lease.id, payload(edit, lease.party_id));
                setEdit(null);
              }, "Terms saved. Charges already worked out stay as they are until that month is worked out again.");
            }}
          >
            <LeaseForm f={edit} set={setEdit} vehicles={vehicles} items={items} locked />
            <p className="actions">
              <button className="btn primary" type="submit">
                Save
              </button>
            </p>
          </form>
        )}
      </Card>
      {manage && (
        <Card title="Work out a month">
          <div className="form-grid">
            <Field label="Month">
              <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} />
            </Field>
            {out && variable ? (
              <>
                {lease.per_trip_cents > 0 && (
                  <Field label="Trips the lessee reported">
                    <input
                      type="number"
                      min="0"
                      value={reported.trips}
                      onChange={(e) => setReported({ ...reported, trips: e.target.value })}
                    />
                  </Field>
                )}
                {lease.per_km_cents > 0 && (
                  <Field label="Kilometres reported">
                    <input
                      type="number"
                      min="0"
                      value={reported.km}
                      onChange={(e) => setReported({ ...reported, km: e.target.value })}
                    />
                  </Field>
                )}
                {lease.revenue_pct > 0 && (
                  <Field label="Revenue reported (KES)">
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      value={reported.revenue}
                      onChange={(e) => setReported({ ...reported, revenue: e.target.value })}
                    />
                  </Field>
                )}
                {lease.profit_pct > 0 && (
                  <Field label="Profit reported (KES)">
                    <input
                      type="number"
                      step="0.01"
                      value={reported.profit}
                      onChange={(e) => setReported({ ...reported, profit: e.target.value })}
                    />
                  </Field>
                )}
              </>
            ) : null}
            <button
              className="btn primary"
              onClick={() =>
                run(
                  () =>
                    api.runLease(
                      lease.id,
                      `${month}-01`,
                      out && variable
                        ? {
                            trips: Number(reported.trips || 0),
                            km: Number(reported.km || 0),
                            revenue_cents: toCents(reported.revenue),
                            profit_cents: toCents(reported.profit),
                          }
                        : undefined,
                    ),
                  "The month's charge is worked out. Costs paid on the owner's behalf were taken off.",
                )
              }
            >
              Work out
            </button>
          </div>
          <p className="muted">
            It is safe to work a month out again; offsets are never counted twice.
          </p>
        </Card>
      )}
      <Card title="Account">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>What</th>
                <th>Amount</th>
              </tr>
            </thead>
            <tbody>
              {lease.entries.map((e) => (
                <tr key={e.id}>
                  <td>{e.entry_date}</td>
                  <td>
                    {e.description}
                    {e.mpesa_code && ` (${e.mpesa_code})`}
                    {e.reference && ` ${e.reference}`}
                  </td>
                  <td>{kes(e.amount_cents)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {lease.entries.length === 0 && <p className="muted">Nothing on the account yet.</p>}
      </Card>
      {manage && (
        <Card title={out ? "Money received from the lessee" : "Pay the lessor"}>
          <div className="form-grid">
            <Field label="Amount (KES)">
              <input
                type="number"
                min="0"
                step="0.01"
                value={pay.amount}
                onChange={(e) => setPay({ ...pay, amount: e.target.value })}
              />
            </Field>
            <Field label="How">
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
            <Field label="M-Pesa code">
              <input value={pay.code} onChange={(e) => setPay({ ...pay, code: e.target.value })} />
            </Field>
            <Field label="Reference">
              <input
                value={pay.reference}
                onChange={(e) => setPay({ ...pay, reference: e.target.value })}
              />
            </Field>
            <button
              className="btn primary"
              disabled={!(Number(pay.amount) > 0)}
              onClick={() =>
                run(async () => {
                  await api.leasePayment(lease.id, {
                    amount_cents: toCents(pay.amount),
                    method: pay.method,
                    mpesa_code: pay.code || null,
                    reference: pay.reference || null,
                  });
                  setPay({ ...pay, amount: "", code: "", reference: "" });
                }, "Payment recorded.")
              }
            >
              Record payment
            </button>
          </div>
          <h4>A correction</h4>
          <div className="form-grid">
            <Field label="Amount (KES, minus to reduce what is owed)">
              <input
                type="number"
                step="0.01"
                value={adjust.amount}
                onChange={(e) => setAdjust({ ...adjust, amount: e.target.value })}
              />
            </Field>
            <Field label="Why">
              <input
                value={adjust.reason}
                onChange={(e) => setAdjust({ ...adjust, reason: e.target.value })}
              />
            </Field>
            <button
              className="btn"
              disabled={!Number(adjust.amount) || adjust.reason.trim().length < 3}
              onClick={() =>
                run(async () => {
                  await api.leaseAdjustment(lease.id, toCents(adjust.amount), adjust.reason);
                  setAdjust({ amount: "", reason: "" });
                }, "Correction recorded.")
              }
            >
              Record correction
            </button>
          </div>
        </Card>
      )}
      <Card title="Statement">
        <div className="form-grid">
          <Field label="Month">
            <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} />
          </Field>
          <button
            className="btn"
            onClick={() =>
              run(async () => setStatement(await api.leaseStatement(lease.id, `${month}-01`)))
            }
          >
            Show
          </button>
          <button className="btn" onClick={download}>
            <Download size={16} /> PDF
          </button>
          {manage && (
            <>
              <button
                className="btn"
                onClick={() =>
                  run(
                    () => api.sendLeaseStatement(lease.id, `${month}-01`, "whatsapp"),
                    "Sent by WhatsApp.",
                  )
                }
              >
                <Send size={16} /> WhatsApp
              </button>
              <button
                className="btn"
                onClick={() =>
                  run(
                    () => api.sendLeaseStatement(lease.id, `${month}-01`, "email"),
                    "Sent by email.",
                  )
                }
              >
                <Send size={16} /> Email
              </button>
            </>
          )}
        </div>
        {statement && <StatementView st={statement} />}
      </Card>
    </>
  );
}

export function StatementView({ st }: { st: LeaseStatement }) {
  return (
    <>
      <p className="muted">
        {st.vehicle},{" "}
        {new Date(st.month).toLocaleDateString("en-KE", { month: "long", year: "numeric" })}
      </p>
      {Object.keys(st.usage).length > 0 && (
        <ul className="list">
          {Object.entries(st.usage).map(([k, v]) => (
            <li key={k}>
              <span>
                {
                  {
                    trips: "Trips",
                    km: "Kilometres",
                    revenue_cents: "Revenue",
                    profit_cents: "Profit",
                  }[k]
                }
              </span>
              <strong>
                {k.endsWith("_cents") ? kes(v as number) : (v as number).toLocaleString()}
              </strong>
            </li>
          ))}
        </ul>
      )}
      <ul className="list">
        <li>
          <span>Brought forward</span>
          <strong>{kes(st.opening_balance_cents)}</strong>
        </li>
        {st.lines.map((l) => (
          <li key={l.id}>
            <span>{l.description}</span>
            <strong>{kes(l.amount_cents)}</strong>
          </li>
        ))}
        <li>
          <span>Balance at the end of the month</span>
          <strong>{kes(st.closing_balance_cents)}</strong>
        </li>
      </ul>
      {st.trips.length > 0 && (
        <>
          <h4>Trips</h4>
          <ul className="list">
            {st.trips.map((t, n) => (
              <li key={n}>
                <span>
                  {new Date(t.delivered_at).toLocaleDateString("en-KE")}, {t.route}
                </span>
                <span>{t.distance_km.toLocaleString()} km</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  );
}

/** Leases, loans, ownership costs and the profit report: the owner's view of what each lorry really costs and earns. */
export default function Leases() {
  const { can } = useAuth();
  return (
    <>
      <h2>Leases, finance and profit</h2>
      <nav className="tabs">
        <NavLink to="/leases" end>
          Leases
        </NavLink>
        <NavLink to="/leases/finance">Loans</NavLink>
        <NavLink to="/leases/costs">Ownership costs</NavLink>
        <NavLink to="/leases/profit">Profit</NavLink>
      </nav>
      {can("finance.view") ? (
        <Routes>
          <Route index element={<LeaseList />} />
          <Route path="view/:id" element={<LeaseDetailPage />} />
          <Route path="finance" element={<LoanList />} />
          <Route path="finance/:id" element={<LoanDetail />} />
          <Route path="costs" element={<OwnershipCosts />} />
          <Route path="profit" element={<ProfitPage />} />
        </Routes>
      ) : (
        <p className="muted">You do not have access to this page.</p>
      )}
    </>
  );
}
