import type { ComplianceCell, VehicleCompliance } from "@fleettms/types";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { Card, ErrorBanner, errorMessage } from "../ui";

type Kind = "insurance" | "inspection";

const TEXT: Record<ComplianceCell["status"], string> = {
  ok: "In date",
  due_soon: "Due soon",
  expired: "Expired",
  missing: "Not recorded",
};
const TONE: Record<ComplianceCell["status"], string> = {
  ok: "ok",
  due_soon: "warn",
  expired: "bad",
  missing: "bad",
};

const days = (c: ComplianceCell) =>
  c.days_left === null
    ? ""
    : c.days_left < 0
      ? `expired ${-c.days_left} d ago`
      : c.days_left === 0
        ? "expires today"
        : `${c.days_left} d left`;

function Cell({
  row,
  kind,
  canManage,
  onSaved,
}: {
  row: VehicleCompliance;
  kind: Kind;
  canManage: boolean;
  onSaved: () => void;
}) {
  const cell = row[kind];
  const [editing, setEditing] = useState(false);
  const [date, setDate] = useState(cell.expires_on ?? "");
  const [error, setError] = useState<string | null>(null);

  async function save() {
    setError(null);
    try {
      await api.setVehicleExpiry(row.vehicle_id, kind, date);
      setEditing(false);
      onSaved();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  return (
    <td>
      <span className={`status ${TONE[cell.status]}`}>{TEXT[cell.status]}</span>{" "}
      {cell.expires_on && (
        <span className="muted">
          {cell.expires_on}, {days(cell)}
        </span>
      )}
      {canManage && !editing && (
        <>
          {" "}
          <button className="btn" onClick={() => setEditing(true)}>
            {cell.expires_on ? "Renew" : "Add"}
          </button>
        </>
      )}
      {editing && (
        <div className="form-grid">
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            aria-label={`${kind} expiry date`}
          />
          <button className="btn primary" disabled={!date} onClick={save}>
            Save
          </button>
          <button className="btn" onClick={() => setEditing(false)}>
            Cancel
          </button>
        </div>
      )}
      {error && <p className="banner bad">{error}</p>}
    </td>
  );
}

/** Insurance and inspection for every vehicle at a glance. What needs a person is first, and a vehicle with nothing on record is shown,
 * because nothing would ever remind about it. Reminders go out at 60, 30, 14, 7 and 1 days. */
export default function Compliance() {
  const { can } = useAuth();
  const [rows, setRows] = useState<VehicleCompliance[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setRows(await api.vehicleCompliance());
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  const canManage = can("vehicles.manage");

  return (
    <>
      <h2>Insurance and inspection</h2>
      <p className="muted">
        Keep both in date for every vehicle. You are reminded 60, 30, 14, 7 and 1 days before each
        runs out, by text and on your phone. Add a date for any vehicle marked "Not recorded", or
        you will not be reminded about it.
      </p>
      <ErrorBanner message={error} />
      <Card>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Vehicle</th>
                <th>Insurance</th>
                <th>Inspection</th>
              </tr>
            </thead>
            <tbody>
              {(rows ?? []).map((r) => (
                <tr key={r.vehicle_id}>
                  <td>
                    <Link to={`/vehicles/${r.vehicle_id}`}>{r.registration}</Link>
                  </td>
                  <Cell row={r} kind="insurance" canManage={canManage} onSaved={load} />
                  <Cell row={r} kind="inspection" canManage={canManage} onSaved={load} />
                </tr>
              ))}
              {rows?.length === 0 && (
                <tr>
                  <td colSpan={3} className="muted">
                    No vehicles yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
