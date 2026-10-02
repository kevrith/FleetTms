import type { Invoice } from "@fleettms/types";
import { BellRing, Download, Plus, Send } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { ETIMS_STATUS, INVOICE_STATUS, kes, todayIso } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

const toCents = (kesText: string) => Math.round(Number(kesText || 0) * 100);

function Standing({ i }: { i: Invoice }) {
  return (
    <span
      className={`status ${i.status === "paid" ? "ok" : i.overdue ? "bad" : i.status === "void" ? "" : "warn"}`}
    >
      {INVOICE_STATUS[i.status]}
      {i.overdue && ", overdue"}
    </span>
  );
}

export function InvoiceList() {
  const [rows, setRows] = useState<Invoice[]>([]);
  const [unpaidOnly, setUnpaidOnly] = useState(false);
  const [month, setMonth] = useState(todayIso().slice(0, 7));
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setRows(await api.invoices({ unpaidOnly }));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [unpaidOnly]);
  useEffect(() => {
    void load();
  }, [load]);
  const owed = rows.reduce((sum, r) => sum + r.balance_cents, 0);
  return (
    <>
      <ErrorBanner message={error} />
      {message && <p className="banner ok">{message}</p>}
      <Card title="Invoices">
        <label className="field">
          <span>
            <input
              type="checkbox"
              checked={unpaidOnly}
              onChange={(e) => setUnpaidOnly(e.target.checked)}
            />{" "}
            Unpaid only
          </span>
        </label>
        <p className="muted">Owed on these invoices: {kes(owed)}</p>
        {rows.length === 0 && (
          <p className="muted">No invoices yet. They appear when a delivery is proven.</p>
        )}
        {rows.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Invoice</th>
                  <th>Client</th>
                  <th>Issued</th>
                  <th>Due</th>
                  <th>Total</th>
                  <th>Balance</th>
                  <th>Status</th>
                  <th>KRA</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <Link to={`/clients/invoices/${r.id}`}>{r.number}</Link>
                      {r.kind === "contract" && <span className="muted"> (contract)</span>}
                    </td>
                    <td>{r.client_name}</td>
                    <td>{r.issue_date}</td>
                    <td>{r.due_date}</td>
                    <td>{kes(r.total_cents)}</td>
                    <td>{kes(r.balance_cents)}</td>
                    <td>
                      <Standing i={r} />
                    </td>
                    <td>{r.etims ? ETIMS_STATUS[r.etims.status] : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <Card title="Monthly contract invoices">
        <p className="muted">
          Contract jobs are invoiced on the 1st for the month before. Run it by hand for any month;
          a contract is billed once a month.
        </p>
        <div className="form-grid">
          <Field label="Month">
            <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} />
          </Field>
          <button
            className="btn"
            onClick={async () => {
              setError(null);
              setMessage(null);
              try {
                const done = await api.runContractInvoices(`${month}-01`);
                setMessage(
                  done.issued.length
                    ? `${done.issued.length} invoice(s) issued.`
                    : "Nothing new to invoice for that month.",
                );
                await load();
              } catch (e) {
                setError(errorMessage(e));
              }
            }}
          >
            <Plus size={16} /> Issue contract invoices
          </button>
        </div>
      </Card>
    </>
  );
}

export function InvoiceDetail() {
  const { id } = useParams();
  const [inv, setInv] = useState<Invoice | null>(null);
  const [pay, setPay] = useState({
    amount: "",
    method: "mpesa" as "cash" | "mpesa" | "bank" | "cheque",
    reference: "",
  });
  const [voidReason, setVoidReason] = useState("");
  const [channel, setChannel] = useState<"email" | "whatsapp" | "sms">("whatsapp");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setInv(await api.invoice(id!));
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
      const url = URL.createObjectURL(await api.invoicePdf(inv!.id));
      const a = document.createElement("a");
      a.href = url;
      a.download = `${inv!.number}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  if (!inv) return <ErrorBanner message={error} />;
  return (
    <>
      <p>
        <Link to="/clients/invoices">Back to invoices</Link>
      </p>
      <ErrorBanner message={error} />
      {message && <p className="banner ok">{message}</p>}
      <Card title={`Invoice ${inv.number} for ${inv.client_name}`}>
        <p>
          <Standing i={inv} /> Issued {inv.issue_date}, due {inv.due_date}.
          {inv.period_start && ` Covers ${inv.period_start} to ${inv.period_end}.`}
          {inv.trip_id && (
            <>
              {" "}
              <Link to={`/trips/${inv.trip_id}`}>See the trip and its proof of delivery</Link>.
            </>
          )}
        </p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Description</th>
                <th>Quantity</th>
                <th>Unit</th>
                <th>Amount</th>
              </tr>
            </thead>
            <tbody>
              {(inv.lines ?? []).map((l) => (
                <tr key={l.id}>
                  <td>{l.description}</td>
                  <td>{l.quantity}</td>
                  <td>{l.unit_cents ? kes(l.unit_cents) : ""}</td>
                  <td>{l.amount_cents ? kes(l.amount_cents) : "Included"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <ul className="list">
          <li>
            <span>Subtotal</span>
            <strong>{kes(inv.subtotal_cents)}</strong>
          </li>
          {inv.vat_pct > 0 && (
            <li>
              <span>VAT {inv.vat_pct}%</span>
              <strong>{kes(inv.vat_cents)}</strong>
            </li>
          )}
          <li>
            <span>Total</span>
            <strong>{kes(inv.total_cents)}</strong>
          </li>
          <li>
            <span>Paid</span>
            <strong>{kes(inv.paid_cents)}</strong>
          </li>
          <li>
            <span>Balance</span>
            <strong>{kes(inv.balance_cents)}</strong>
          </li>
        </ul>
        <p className="actions">
          <button className="btn" onClick={download}>
            <Download size={16} /> PDF{inv.trip_id ? " (with proof of delivery)" : ""}
          </button>
        </p>
      </Card>
      {inv.status !== "void" && (
        <Card title="Send to the client">
          <div className="form-grid">
            <Field label="Send by">
              <select
                value={channel}
                onChange={(e) => setChannel(e.target.value as typeof channel)}
              >
                <option value="whatsapp">WhatsApp (PDF)</option>
                <option value="email">Email (PDF)</option>
                <option value="sms">SMS (amount and due date)</option>
              </select>
            </Field>
            <button
              className="btn"
              onClick={() => run(() => api.sendInvoice(inv.id, channel), "Invoice sent.")}
            >
              <Send size={16} /> Send
            </button>
          </div>
          {inv.sent_at && <p className="muted">Last sent by {inv.sent_via}.</p>}
        </Card>
      )}
      {inv.status !== "void" && inv.balance_cents > 0 && (
        <Card title="Payment reminders">
          <p className="actions">
            <button
              className="btn"
              onClick={() =>
                run(async () => {
                  const done = await api.remindInvoice(inv.id, ["sms", "email"]);
                  const ok = done.sent
                    .filter((x) => x.status === "sent")
                    .map((x) => x.channel.toUpperCase());
                  setMessage(
                    ok.length
                      ? `Reminder sent by ${ok.join(" and ")}.`
                      : "The reminder could not be sent.",
                  );
                })
              }
            >
              <BellRing size={16} /> Remind now
            </button>
          </p>
          {(inv.reminders ?? []).length === 0 && <p className="muted">No reminders sent yet.</p>}
          <ul className="list">
            {(inv.reminders ?? []).map((r) => (
              <li key={r.id}>
                <span>
                  {new Date(r.sent_at).toLocaleDateString("en-KE")}, by {r.channel.toUpperCase()},{" "}
                  {r.automatic ? "automatic" : "by hand"}
                  {r.error && ` (${r.error})`}
                </span>
                <span className={`status ${r.status === "sent" ? "ok" : "bad"}`}>
                  {r.status === "sent" ? "Sent" : "Failed"}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}
      {inv.etims && (
        <Card title="KRA eTIMS">
          <p>
            <span
              className={`status ${inv.etims.status === "submitted" || inv.etims.status === "resolved" ? "ok" : inv.etims.status === "needs_review" ? "bad" : "warn"}`}
            >
              {ETIMS_STATUS[inv.etims.status]}
            </span>
            {inv.etims.receipt_no && ` Receipt number ${inv.etims.receipt_no}.`}
            {inv.etims.credit_note_status &&
              ` Credit note: ${(ETIMS_STATUS[inv.etims.credit_note_status] ?? "").toLowerCase()}.`}
          </p>
          {inv.etims.last_error && <p className="muted">{inv.etims.last_error}</p>}
          <p>
            <Link to="/clients/etims">Open the eTIMS queue</Link>
          </p>
        </Card>
      )}
      <Card title="Payments">
        {(inv.payments ?? []).length === 0 && <p className="muted">Nothing received yet.</p>}
        <ul className="list">
          {(inv.payments ?? []).map((p) => (
            <li key={p.id}>
              <span>
                {p.received_on}, {p.method}
                {p.reference && ` ${p.reference}`}
              </span>
              <strong>{kes(p.amount_cents)}</strong>
            </li>
          ))}
        </ul>
        {inv.status !== "void" && inv.balance_cents > 0 && (
          <div className="form-grid">
            <Field label="Amount received (KES)">
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
            <Field label="Reference (M-Pesa code, cheque number)">
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
                  await api.addPayment(inv.id, {
                    amount_cents: toCents(pay.amount),
                    method: pay.method,
                    reference: pay.reference || null,
                  });
                  setPay({ ...pay, amount: "", reference: "" });
                })
              }
            >
              Record payment
            </button>
          </div>
        )}
      </Card>
      {inv.status === "issued" && (
        <Card title="Void">
          <div className="form-grid">
            <Field label="Reason">
              <input value={voidReason} onChange={(e) => setVoidReason(e.target.value)} />
            </Field>
            <button
              className="btn danger"
              disabled={voidReason.trim().length < 3}
              onClick={() => run(() => api.voidInvoice(inv.id, voidReason))}
            >
              Void this invoice
            </button>
          </div>
        </Card>
      )}
    </>
  );
}
