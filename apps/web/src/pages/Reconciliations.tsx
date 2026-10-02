import type { Reconciliation, ReconciliationDetail } from "@fleettms/types";
import { Check, Undo2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { EXPENSE_CATEGORY, RECON_STATUS, kes } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

/** Evening float reconciliation: opening + floats - expenses = closing, approved by a supervisor, manager or owner. */
export default function Reconciliations() {
  const [rows, setRows] = useState<Reconciliation[]>([]);
  const [open, setOpen] = useState<ReconciliationDetail | null>(null);
  const [action, setAction] = useState<"carry_forward" | "returned">("carry_forward");
  const [note, setNote] = useState("");
  const [onlyWaiting, setOnlyWaiting] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRows(await api.reconciliations(onlyWaiting ? "submitted" : undefined));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [onlyWaiting]);
  useEffect(() => {
    void load();
  }, [load]);

  async function show(id: string) {
    setError(null);
    try {
      setOpen(await api.reconciliation(id));
      setNote("");
      setAction("carry_forward");
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  async function decide(approve: boolean) {
    if (!open) return;
    setError(null);
    try {
      if (approve) await api.approveReconciliation(open.id, action, note.trim() || undefined);
      else await api.rejectReconciliation(open.id, note.trim());
      setOpen(null);
      await load();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  return (
    <>
      <ErrorBanner message={error} />
      <Card title="Daily reconciliations">
        <label className="check">
          <input
            type="checkbox"
            checked={onlyWaiting}
            onChange={(e) => setOnlyWaiting(e.target.checked)}
          />
          <span>Only those waiting for approval</span>
        </label>
        {rows.length === 0 && <p className="muted">Nothing here.</p>}
        {rows.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Day</th>
                  <th>Driver</th>
                  <th>Opening</th>
                  <th>Floats</th>
                  <th>Expenses</th>
                  <th>Closing</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td>{r.day}</td>
                    <td>{r.driver_name}</td>
                    <td>{kes(r.opening_cents)}</td>
                    <td>{kes(r.floats_cents)}</td>
                    <td>{kes(r.expenses_cents)}</td>
                    <td>
                      <strong>{kes(r.closing_cents)}</strong>
                    </td>
                    <td>{RECON_STATUS[r.status]}</td>
                    <td>
                      <button className="btn" onClick={() => show(r.id)}>
                        Open
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {open && (
        <Card title={`${open.driver_name}, ${open.day}`}>
          <p>
            {kes(open.opening_cents)} opening + {kes(open.floats_cents)} floats -{" "}
            {kes(open.expenses_cents)} expenses = <strong>{kes(open.closing_cents)}</strong>
          </p>
          {open.pending_expenses > 0 && (
            <p className="status warn">
              {open.pending_expenses} expense{open.pending_expenses === 1 ? " is" : "s are"} waiting
              for the owner. The day cannot be approved until they are decided.
            </p>
          )}
          <ul className="list">
            {open.expenses.map((e) => (
              <li key={e.id}>
                <span>
                  {EXPENSE_CATEGORY[e.category]} {e.note && <span className="muted">{e.note}</span>}
                </span>
                <span>{kes(e.amount_cents)}</span>
              </li>
            ))}
          </ul>
          {open.status === "submitted" && (
            <div className="form-grid">
              <Field label="What happens to the balance?">
                <select
                  value={action}
                  onChange={(e) => setAction(e.target.value as "carry_forward" | "returned")}
                >
                  <option value="carry_forward">Carry it forward to tomorrow</option>
                  <option value="returned">The driver returned the cash</option>
                </select>
              </Field>
              <Field label="Note (needed to send back)">
                <input value={note} onChange={(e) => setNote(e.target.value)} />
              </Field>
              <button
                className="btn primary"
                onClick={() => decide(true)}
                disabled={open.pending_expenses > 0}
              >
                <Check size={16} /> Approve
              </button>
              <button
                className="btn danger"
                onClick={() => decide(false)}
                disabled={note.trim().length < 3}
              >
                <Undo2 size={16} /> Send back
              </button>
            </div>
          )}
        </Card>
      )}
    </>
  );
}
