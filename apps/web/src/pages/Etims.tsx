import type { EtimsSubmission, EtimsSummary } from "@fleettms/types";
import { RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { ETIMS_STATUS, kes } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString("en-KE") : "");

/** Every invoice's trip to KRA eTIMS, with the ones that need a person on top. */
export function EtimsQueue() {
  const [summary, setSummary] = useState<EtimsSummary | null>(null);
  const [rows, setRows] = useState<EtimsSubmission[]>([]);
  const [filter, setFilter] = useState("attention");
  const [note, setNote] = useState<Record<string, { text: string; receipt: string }>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setSummary(await api.etimsSummary());
      setRows(await api.etimsSubmissions(filter === "all" ? undefined : filter));
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
      {summary && !summary.enabled && (
        <p className="banner">
          eTIMS is off. The owner can turn it on under Settings, Payments and tax.
        </p>
      )}
      {summary && (
        <Card title="KRA eTIMS">
          <p>
            {summary.submitted} sent to KRA, {summary.pending} waiting to send,{" "}
            <strong>{summary.needs_review} need a person</strong>, {summary.resolved} handled by
            hand.
          </p>
          <p className="muted">
            {summary.connected_at
              ? `Device connected ${when(summary.connected_at)}.`
              : "The device has not been connected yet."}{" "}
            Invoices are sent every few minutes, and tried again if KRA cannot be reached.
          </p>
        </Card>
      )}
      <Card title="Invoices">
        <Field label="Show">
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="attention">Needs a person</option>
            <option value="pending">Waiting to send</option>
            <option value="submitted">Sent to KRA</option>
            <option value="resolved">Handled by hand</option>
            <option value="all">Everything</option>
          </select>
        </Field>
        {rows.length === 0 && <p className="muted">Nothing here.</p>}
        {rows.map((s) => (
          <div className="card" key={s.id}>
            <p>
              <Link to={`/clients/invoices/${s.invoice_id}`}>{s.invoice_number}</Link>
              {s.kind === "credit_note" && " (credit note for a voided invoice)"} for{" "}
              {s.client_name}, {s.total_cents !== null && kes(s.total_cents)}{" "}
              <span
                className={`status ${s.status === "submitted" || s.status === "resolved" ? "ok" : s.status === "needs_review" ? "bad" : "warn"}`}
              >
                {ETIMS_STATUS[s.status]}
              </span>
            </p>
            {s.receipt_no && <p className="muted">KRA receipt number {s.receipt_no}.</p>}
            {s.last_error && <p className="muted">{s.last_error}</p>}
            {s.status === "pending" && s.next_attempt_at && (
              <p className="muted">
                Tried {s.attempts} time{s.attempts === 1 ? "" : "s"}. Next try{" "}
                {when(s.next_attempt_at)}.
              </p>
            )}
            {s.resolved_note && <p className="muted">{s.resolved_note}</p>}
            {(s.status === "pending" || s.status === "needs_review") && (
              <>
                <p className="actions">
                  <button
                    className="btn primary"
                    onClick={() =>
                      run(() => api.etimsRetry(s.id), "Tried again. See the result below.")
                    }
                  >
                    <RefreshCw size={16} />{" "}
                    {s.status === "pending" ? "Send now" : "Fix and send again"}
                  </button>
                </p>
                {s.status === "needs_review" && (
                  <div className="form-grid">
                    <Field label="Dealt with outside FleetTms? Say how">
                      <input
                        value={note[s.id]?.text ?? ""}
                        onChange={(e) =>
                          setNote({
                            ...note,
                            [s.id]: { text: e.target.value, receipt: note[s.id]?.receipt ?? "" },
                          })
                        }
                      />
                    </Field>
                    <Field label="KRA receipt number (if you have it)">
                      <input
                        value={note[s.id]?.receipt ?? ""}
                        onChange={(e) =>
                          setNote({
                            ...note,
                            [s.id]: { text: note[s.id]?.text ?? "", receipt: e.target.value },
                          })
                        }
                      />
                    </Field>
                    <button
                      className="btn"
                      disabled={(note[s.id]?.text ?? "").trim().length < 3}
                      onClick={() =>
                        run(
                          () => api.etimsResolve(s.id, note[s.id]!.text, note[s.id]?.receipt),
                          "Marked as handled by hand.",
                        )
                      }
                    >
                      Mark as handled
                    </button>
                  </div>
                )}
              </>
            )}
          </div>
        ))}
      </Card>
    </>
  );
}
