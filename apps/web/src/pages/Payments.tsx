import type { Invoice, MpesaPayment, StatementImport, StatementLine } from "@fleettms/types";
import { Upload } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { kes, MPESA_STATUS, STATEMENT_STATE } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

const when = (iso: string) => new Date(iso).toLocaleString("en-KE");

/** Client payments that came in by M-Pesa, and the ones nobody could match to an invoice yet. */
export function MpesaPayments() {
  const [rows, setRows] = useState<MpesaPayment[]>([]);
  const [open, setOpen] = useState<Invoice[]>([]);
  const [filter, setFilter] = useState("needs_attention");
  const [pick, setPick] = useState<Record<string, string>>({});
  const [reason, setReason] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      const list = await api.mpesaPayments(filter === "all" ? undefined : filter);
      // the suggestions (invoices that owe exactly that much) come with each payment's own page
      const detailed = await Promise.all(
        list.map((p) =>
          p.status === "unmatched" || p.status === "partly_matched" ? api.mpesaPayment(p.id) : p,
        ),
      );
      setRows(detailed);
      setOpen(await api.invoices({ unpaidOnly: true }));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [filter]);
  useEffect(() => {
    void load();
  }, [load]);
  async function run(action: () => Promise<unknown>, done: string) {
    setError(null);
    setMessage(null);
    try {
      await action();
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
      <Card title="M-Pesa payments from clients">
        <p className="muted">
          A payment that names an invoice number is put against that invoice at once. Anything else
          waits here for you.
        </p>
        <Field label="Show">
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="needs_attention">Waiting for a match</option>
            <option value="matched">Matched</option>
            <option value="dismissed">Set aside</option>
            <option value="all">Everything</option>
          </select>
        </Field>
        {rows.length === 0 && <p className="muted">Nothing here.</p>}
        {rows.map((p) => {
          const waiting = p.status === "unmatched" || p.status === "partly_matched";
          return (
            <div className="card" key={p.id}>
              <p>
                <strong>{kes(p.amount_cents)}</strong> from {p.payer_name ?? "an unknown payer"},
                code {p.trans_id}, {when(p.paid_at)}{" "}
                <span
                  className={`status ${p.status === "matched" ? "ok" : p.status === "dismissed" ? "" : "warn"}`}
                >
                  {MPESA_STATUS[p.status]}
                </span>
              </p>
              <p className="muted">
                Account number typed: {p.bill_ref ? `"${p.bill_ref}"` : "nothing"}.
                {p.reason_text && ` ${p.reason_text}`}
                {p.allocated_cents > 0 &&
                  ` ${kes(p.allocated_cents)} is matched, ${kes(p.left_cents)} left.`}
                {p.dismissed_reason && ` Set aside: ${p.dismissed_reason}.`}
              </p>
              {waiting && (
                <>
                  {(p.suggestions ?? []).length > 0 && (
                    <p className="muted">
                      Owes exactly this much:{" "}
                      {(p.suggestions ?? []).map((s) => (
                        <button
                          key={s.id}
                          className="btn"
                          onClick={() =>
                            run(() => api.matchPayment(p.id, s.id), `Put against ${s.number}.`)
                          }
                        >
                          {s.number}
                        </button>
                      ))}
                    </p>
                  )}
                  <div className="form-grid">
                    <Field label="Put it against invoice">
                      <select
                        value={pick[p.id] ?? ""}
                        onChange={(e) => setPick({ ...pick, [p.id]: e.target.value })}
                      >
                        <option value="">Choose an invoice</option>
                        {open.map((i) => (
                          <option key={i.id} value={i.id}>
                            {i.number}, {i.client_name}, owes {kes(i.balance_cents)}
                          </option>
                        ))}
                      </select>
                    </Field>
                    <button
                      className="btn primary"
                      disabled={!pick[p.id]}
                      onClick={() =>
                        run(() => api.matchPayment(p.id, pick[p.id]!), "Payment matched.")
                      }
                    >
                      Match
                    </button>
                  </div>
                  <div className="form-grid">
                    <Field label="Or set it aside (for example: refunded, not for us)">
                      <input
                        value={reason[p.id] ?? ""}
                        onChange={(e) => setReason({ ...reason, [p.id]: e.target.value })}
                      />
                    </Field>
                    <button
                      className="btn danger"
                      disabled={(reason[p.id] ?? "").trim().length < 3}
                      onClick={() =>
                        run(() => api.dismissPayment(p.id, reason[p.id]!), "Payment set aside.")
                      }
                    >
                      Set aside
                    </button>
                  </div>
                </>
              )}
            </div>
          );
        })}
      </Card>
    </>
  );
}

const STATE_CLASS: Record<string, string> = {
  matched: "ok",
  amount_differs: "bad",
  unmatched: "warn",
  ignored: "",
};

/** Upload the business's M-Pesa statement: what drivers claimed is checked against it, and client money that came in is matched. */
export function StatementPage() {
  const input = useRef<HTMLInputElement>(null);
  const [imports, setImports] = useState<StatementImport[]>([]);
  const [lines, setLines] = useState<StatementLine[]>([]);
  const [state, setState] = useState("attention");
  const [result, setResult] = useState<StatementImport | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setImports(await api.statementImports());
      setLines(await api.statementLines({ state: state === "all" ? undefined : state }));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [state]);
  useEffect(() => {
    void load();
  }, [load]);
  async function upload() {
    const file = input.current?.files?.[0];
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await api.uploadStatement(file));
      if (input.current) input.current.value = "";
      await load();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  const s = result?.summary;
  return (
    <>
      <ErrorBanner message={error} />
      <Card title="Upload an M-Pesa statement">
        <p className="muted">
          Download the statement from the M-Pesa business portal as CSV or Excel. Fuel, expenses and
          floats the drivers claimed are checked against it by M-Pesa code. It is safe to upload the
          same statement again.
        </p>
        <div className="form-grid">
          <Field label="Statement file">
            <input ref={input} type="file" accept=".csv,.xlsx" />
          </Field>
          <button className="btn primary" disabled={busy} onClick={upload}>
            <Upload size={16} /> {busy ? "Reading..." : "Upload"}
          </button>
        </div>
        {result && s && (
          <div className="banner ok">
            <p>
              Read {result.rows} lines ({result.new_rows} new). {s.matched} matched,{" "}
              {s.amount_differs} with a different amount, {s.unmatched} not matched.
              {s.payments_recovered > 0 &&
                ` ${s.payments_recovered} client payment${s.payments_recovered === 1 ? "" : "s"} found that Safaricom never told us about.`}
            </p>
            {s.not_on_statement.length > 0 && (
              <p>
                Claimed by drivers but not on this statement:{" "}
                {s.not_on_statement
                  .map((m) => `${m.mpesa_code} (${kes(m.amount_cents)})`)
                  .join(", ")}
                .
              </p>
            )}
          </div>
        )}
      </Card>
      <Card title="Statement lines">
        <Field label="Show">
          <select value={state} onChange={(e) => setState(e.target.value)}>
            <option value="attention">Needs a look</option>
            <option value="matched">Matched</option>
            <option value="ignored">Looked at, fine</option>
            <option value="all">Everything</option>
          </select>
        </Field>
        {lines.length === 0 && <p className="muted">Nothing here.</p>}
        {lines.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>When</th>
                  <th>Code</th>
                  <th>Details</th>
                  <th>In</th>
                  <th>Out</th>
                  <th>Result</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {lines.map((l) => (
                  <tr key={l.id}>
                    <td>{when(l.completed_at)}</td>
                    <td>{l.receipt}</td>
                    <td>{l.details}</td>
                    <td>{l.paid_in_cents ? kes(l.paid_in_cents) : ""}</td>
                    <td>{l.withdrawn_cents ? kes(l.withdrawn_cents) : ""}</td>
                    <td>
                      <span className={`status ${STATE_CLASS[l.state]}`}>
                        {STATEMENT_STATE[l.state]}
                        {l.match_label && `, ${l.match_label.toLowerCase()}`}
                      </span>
                      {l.note && <div className="muted">{l.note}</div>}
                      {l.match_kind === "client_payment" && l.state === "unmatched" && (
                        <div>
                          <Link to="/clients/payments">Match it to an invoice</Link>
                        </div>
                      )}
                    </td>
                    <td>
                      {(l.state === "unmatched" || l.state === "amount_differs") && (
                        <div className="form-grid">
                          <input
                            placeholder="Why it is fine"
                            value={note[l.id] ?? ""}
                            onChange={(e) => setNote({ ...note, [l.id]: e.target.value })}
                          />
                          <button
                            className="btn"
                            disabled={(note[l.id] ?? "").trim().length < 3}
                            onClick={async () => {
                              try {
                                await api.ignoreStatementLine(l.id, note[l.id]!);
                                await load();
                              } catch (e) {
                                setError(errorMessage(e));
                              }
                            }}
                          >
                            Mark as fine
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <Card title="Earlier uploads">
        {imports.length === 0 && <p className="muted">None yet.</p>}
        <ul className="list">
          {imports.map((i) => (
            <li key={i.id}>
              <span>
                {when(i.created_at)}, {i.filename ?? "statement"}
              </span>
              <span>
                {i.rows} lines, {i.new_rows} new
              </span>
            </li>
          ))}
        </ul>
      </Card>
    </>
  );
}
