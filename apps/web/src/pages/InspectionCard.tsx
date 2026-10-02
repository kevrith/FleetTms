import type { Inspection } from "@fleettms/types";
import { ShieldAlert } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { fmtTime, INSPECTION_STATUS } from "../labels";
import { ErrorBanner, errorMessage, Field } from "../ui";

export function StatusPill({ status }: { status: string }) {
  const cls = status === "passed" ? "ok" : status === "blocked" ? "bad" : "warn";
  return <span className={`status ${cls}`}>{INSPECTION_STATUS[status] ?? status}</span>;
}

/** One inspection with its results, photos of faults, and (for managers) the override form on a blocked one. */
export default function InspectionCard({
  inspection,
  onChanged,
}: {
  inspection: Inspection;
  onChanged: () => Promise<void> | void;
}) {
  const { can } = useAuth();
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function override() {
    setError(null);
    try {
      await api.overrideInspection(inspection.id, reason);
      setReason("");
      await onChanged();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  const faults = inspection.results.filter((r) => !r.ok);
  return (
    <div>
      <p>
        <StatusPill status={inspection.status} />{" "}
        <span className="muted">{fmtTime(inspection.performed_at)}</span>
      </p>
      <ErrorBanner message={error} />
      {faults.length === 0 && (
        <p className="muted">All {inspection.results.length} checks were fine.</p>
      )}
      <ul className="list">
        {faults.map((r) => (
          <li key={r.label}>
            <span>
              <strong>{r.label}</strong>
              {r.critical && <span className="status bad"> critical</span>}
              <br />
              <span className="muted">{r.note}</span>
            </span>
            {r.photo && (
              <a href={api.mediaUrl(r.photo.url)} target="_blank" rel="noreferrer">
                <img src={api.mediaUrl(r.photo.url)} alt={`Photo of ${r.label}`} height={64} />
              </a>
            )}
          </li>
        ))}
      </ul>
      {inspection.override_reason && (
        <p className="muted">
          Overridden {fmtTime(inspection.overridden_at)}: {inspection.override_reason}
        </p>
      )}
      {inspection.status === "blocked" && can("inspections.override") && (
        <div className="form-grid">
          <Field label="Reason for letting this vehicle go out">
            <input value={reason} onChange={(e) => setReason(e.target.value)} />
          </Field>
          <button className="btn danger" disabled={reason.trim().length < 5} onClick={override}>
            <ShieldAlert size={16} /> Override and allow trips
          </button>
        </div>
      )}
    </div>
  );
}
