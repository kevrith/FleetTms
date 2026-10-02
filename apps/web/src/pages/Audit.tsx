import type { AuditEntry } from "@fleettms/types";
import { Fragment, useEffect, useState } from "react";
import { api } from "../api";
import { Card, ErrorBanner, errorMessage } from "../ui";

const when = (iso: string) =>
  new Date(iso).toLocaleString("en-KE", {
    timeZone: "Africa/Nairobi",
    dateStyle: "medium",
    timeStyle: "short",
  });

export default function Audit() {
  const [rows, setRows] = useState<AuditEntry[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .audit({ limit: 100 })
      .then(setRows)
      .catch((e) => setError(errorMessage(e)));
  }, []);

  return (
    <Card title="Audit trail">
      <p className="muted">
        Every sensitive change is recorded here. Entries cannot be edited or deleted.
      </p>
      <ErrorBanner message={error} />
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>When (Nairobi)</th>
              <th>Action</th>
              <th>Record</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((a) => (
              <Fragment key={a.id}>
                <tr>
                  <td>{when(a.created_at)}</td>
                  <td>
                    <code>{a.action}</code>
                  </td>
                  <td>{a.entity_type}</td>
                  <td>
                    <button className="btn" onClick={() => setOpen(open === a.id ? null : a.id)}>
                      {open === a.id ? "Hide" : "Details"}
                    </button>
                  </td>
                </tr>
                {open === a.id && (
                  <tr>
                    <td colSpan={4}>
                      <pre>
                        {JSON.stringify(
                          { before: a.before, after: a.after, note: a.note },
                          null,
                          2,
                        )}
                      </pre>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
