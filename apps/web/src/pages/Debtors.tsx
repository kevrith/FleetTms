import type { DebtorDetail, Debtors } from "@fleettms/types";
import { BellRing } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { AGEING, kes } from "../labels";
import { Card, ErrorBanner, errorMessage } from "../ui";

const ORDER = ["current", "1_30", "31_60", "61_90", "over_90"] as const;

function Buckets({ buckets }: { buckets: Record<(typeof ORDER)[number], number> }) {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
      {ORDER.map((b) => (
        <div className="card" key={b} style={{ minWidth: 150 }}>
          <p className="muted">{AGEING[b]}</p>
          <p style={{ fontSize: 20, fontWeight: 700, margin: "4px 0" }}>{kes(buckets[b])}</p>
        </div>
      ))}
    </div>
  );
}

/** Who owes the business money, how late it is, and who has paid recently. */
export function DebtorList() {
  const [data, setData] = useState<Debtors | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api
      .debtors()
      .then(setData)
      .catch((e) => setError(errorMessage(e)));
  }, []);
  if (!data) return <ErrorBanner message={error} />;
  return (
    <>
      <ErrorBanner message={error} />
      <Card title={`Owed to you: ${kes(data.balance_cents)}`}>
        <p className="muted">
          Counted from each invoice's due date. {kes(data.overdue_cents)} is past its due date.
        </p>
        <Buckets buckets={data.buckets} />
      </Card>
      <Card title="By client, worst first">
        {data.clients.length === 0 && <p className="muted">Nobody owes you anything right now.</p>}
        {data.clients.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Client</th>
                  <th>Owes</th>
                  <th>Past due</th>
                  <th>Oldest</th>
                  <th>Last paid</th>
                  <th>Reminders</th>
                </tr>
              </thead>
              <tbody>
                {data.clients.map((c) => (
                  <tr key={c.client_id}>
                    <td>
                      <Link to={c.client_id}>{c.name}</Link>
                    </td>
                    <td>{kes(c.balance_cents)}</td>
                    <td>{c.overdue_cents > 0 ? kes(c.overdue_cents) : ""}</td>
                    <td>
                      {c.oldest_days_late > 0 ? `${c.oldest_days_late} days late` : "Not yet due"}
                    </td>
                    <td>{c.last_payment_on ?? "Never"}</td>
                    <td>{c.reminders_enabled ? "On" : "Off"}</td>
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

/** One client's statement: what is open and how old, what they have paid, and who has been reminded. */
export function DebtorPage() {
  const { id } = useParams();
  const [data, setData] = useState<DebtorDetail | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setData(await api.debtor(id!));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [id]);
  useEffect(() => {
    void load();
  }, [load]);
  async function remind(invoiceId: string) {
    setError(null);
    setMessage(null);
    try {
      const done = await api.remindInvoice(invoiceId, ["sms", "email"]);
      const failed = done.sent.filter((s) => s.status === "failed");
      setMessage(
        `Reminder sent by ${
          done.sent
            .filter((s) => s.status === "sent")
            .map((s) => s.channel.toUpperCase())
            .join(" and ") || "nothing"
        }.${failed.length ? ` ${failed.map((f) => f.error).join(" ")}` : ""}`,
      );
      await load();
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  if (!data) return <ErrorBanner message={error} />;
  return (
    <>
      <p>
        <Link to="/clients/debtors">Back to who owes you</Link>
      </p>
      <ErrorBanner message={error} />
      {message && <p className="banner ok">{message}</p>}
      <Card title={`${data.client.name} owes ${kes(data.balance_cents)}`}>
        <p className="muted">
          Pays in {data.client.payment_terms_days} days.{" "}
          {[data.client.phone, data.client.email].filter(Boolean).join(", ") ||
            "No phone or email on file, so reminders cannot be sent."}
        </p>
        <Buckets buckets={data.buckets} />
      </Card>
      <Card title="Open invoices">
        {data.invoices.length === 0 && <p className="muted">Nothing is owed.</p>}
        {data.invoices.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Invoice</th>
                  <th>Due</th>
                  <th>Age</th>
                  <th>Owed</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.invoices.map((i) => (
                  <tr key={i.id}>
                    <td>
                      <Link to={`/clients/invoices/${i.id}`}>{i.number}</Link>
                    </td>
                    <td>{i.due_date}</td>
                    <td>{i.days_late > 0 ? `${i.days_late} days late` : "Not yet due"}</td>
                    <td>{kes(i.balance_cents)}</td>
                    <td>
                      <button className="btn" onClick={() => remind(i.id)}>
                        <BellRing size={16} /> Remind now
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <Card title="Payments received">
        {data.payments.length === 0 && <p className="muted">No payments yet.</p>}
        <ul className="list">
          {data.payments.map((p, n) => (
            <li key={`${p.invoice_id}-${n}`}>
              <span>
                {p.received_on}, {p.invoice_number}, {p.method}
                {p.reference && ` ${p.reference}`}
              </span>
              <strong>{kes(p.amount_cents)}</strong>
            </li>
          ))}
        </ul>
      </Card>
      <Card title="Reminders sent">
        {data.reminders.length === 0 && <p className="muted">None yet.</p>}
        <ul className="list">
          {data.reminders.map((r, n) => (
            <li key={n}>
              <span>
                {new Date(r.sent_at).toLocaleDateString("en-KE")}, {r.invoice_number}, by{" "}
                {r.channel.toUpperCase()}, {r.automatic ? "automatic" : "by hand"}
              </span>
              <span className={`status ${r.status === "sent" ? "ok" : "bad"}`}>
                {r.status === "sent" ? "Sent" : "Failed"}
              </span>
            </li>
          ))}
        </ul>
      </Card>
    </>
  );
}
