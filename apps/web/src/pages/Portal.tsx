import type { LeaseStatement, PortalLease } from "@fleettms/types";
import { Download } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { kes, todayIso } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";
import { StatementView, terms } from "./Leases";

/** The lessor's window onto their own lorry: what was charged, paid and owed, and the lorry's service history. */
export default function Portal() {
  const [leases, setLeases] = useState<PortalLease[]>([]);
  const [open, setOpen] = useState<PortalLease | null>(null);
  const [month, setMonth] = useState(todayIso().slice(0, 7));
  const [statement, setStatement] = useState<LeaseStatement | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setLeases(await api.portalLeases());
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  async function show(id: string) {
    setError(null);
    setStatement(null);
    try {
      setOpen(await api.portalLease(id));
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  async function download() {
    if (!open) return;
    try {
      const url = URL.createObjectURL(await api.portalStatementPdf(open.id, `${month}-01`));
      const a = document.createElement("a");
      a.href = url;
      a.download = `lease-${month}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  return (
    <>
      <h2>Your leased lorries</h2>
      <ErrorBanner message={error} />
      {leases.length === 0 && <p className="muted">No leases are set up for you yet.</p>}
      {leases.map((l) => (
        <Card
          key={l.id}
          title={`${l.registration}${l.operator ? `, leased to ${l.operator}` : ""}`}
        >
          <p>
            {terms(l)}. {l.status === "active" ? "Running" : "Ended"} since {l.start_date}.
          </p>
          <p>
            <strong>Owed to you: {kes(l.balance_cents ?? 0)}</strong>
            {(l.overdue_cents ?? 0) > 0 && (
              <span className="status bad"> {kes(l.overdue_cents ?? 0)} is overdue</span>
            )}
            {l.next_due_date && <span className="muted"> Next payment due {l.next_due_date}.</span>}
          </p>
          <p className="actions">
            <button className="btn" onClick={() => show(l.id)}>
              Open
            </button>
          </p>
        </Card>
      ))}
      {open && (
        <>
          <Card title={`${open.registration}: statement`}>
            <div className="form-grid">
              <Field label="Month">
                <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} />
              </Field>
              <button
                className="btn"
                onClick={async () => {
                  try {
                    setStatement(await api.portalStatement(open.id, `${month}-01`));
                  } catch (e) {
                    setError(errorMessage(e));
                  }
                }}
              >
                Show
              </button>
              <button className="btn" onClick={download}>
                <Download size={16} /> PDF
              </button>
            </div>
            {statement && <StatementView st={statement} />}
          </Card>
          <Card title="Account">
            <ul className="list">
              {(open.entries ?? []).map((e) => (
                <li key={e.id}>
                  <span>
                    {e.entry_date}, {e.description}
                  </span>
                  <strong>{kes(e.amount_cents)}</strong>
                </li>
              ))}
            </ul>
          </Card>
          <Card title="Service and inspections">
            <ul className="list">
              {(open.service_history ?? []).map((s, n) => (
                <li key={n}>
                  <span>
                    {s.done_on}, serviced at {s.odometer_km.toLocaleString()} km
                  </span>
                  <span>{s.notes}</span>
                </li>
              ))}
              {(open.inspections ?? []).slice(0, 10).map((i, n) => (
                <li key={`i${n}`}>
                  <span>{i.date}, daily inspection</span>
                  <span>{i.status.replace("_", " ")}</span>
                </li>
              ))}
            </ul>
          </Card>
        </>
      )}
    </>
  );
}
