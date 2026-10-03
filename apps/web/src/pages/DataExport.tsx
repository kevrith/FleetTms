import type { DataExportInfo } from "@fleettms/types";
import { Download } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { nairobiTime } from "../labels";
import { Card, ErrorBanner, errorMessage } from "../ui";

const STATE: Record<string, string> = {
  queued: "Waiting to start",
  running: "Being made",
  ready: "Ready",
  failed: "Failed",
  expired: "Deleted after a week",
};
const mb = (bytes: number | null) => (bytes ? `${(bytes / 1_048_576).toFixed(1)} MB` : "");

/** A full copy of everything the business has, as a zip of spreadsheets, whenever the owner wants it, even if the account is read-only. */
export default function DataExport() {
  const [rows, setRows] = useState<DataExportInfo[]>([]);
  const [photos, setPhotos] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setRows(await api.dataExports());
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  const busy = rows.some((r) => r.status === "queued" || r.status === "running");
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(load, 3000);
    return () => clearInterval(timer);
  }, [busy, load]);

  async function request() {
    setError(null);
    try {
      await api.requestExport(photos);
      await load();
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  async function download(r: DataExportInfo) {
    setError(null);
    try {
      const url = URL.createObjectURL(await api.dataExportFile(r.id));
      const a = document.createElement("a");
      a.href = url;
      a.download = `fleettms-data-${r.created_at.slice(0, 10)}.zip`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  return (
    <>
      <ErrorBanner message={error} />
      <Card title="Your data">
        <p>
          Everything your business has in FleetTms is yours. A copy is a zip of spreadsheets, one
          for each kind of record (vehicles, trips, fuel, expenses, invoices, payments, staff and
          more), with a note explaining them. Passwords and security keys are never in it.
        </p>
        <label className="check">
          <input type="checkbox" checked={photos} onChange={(e) => setPhotos(e.target.checked)} />
          <span>Include the photos too (the copy is much bigger)</span>
        </label>
        <p className="actions">
          <button className="btn primary" type="button" disabled={busy} onClick={request}>
            Make a copy now
          </button>
        </p>
        <p className="muted">
          This works even if the subscription has not been paid. A copy is kept for a week, then
          deleted.
        </p>
      </Card>
      <Card title="Copies">
        {rows.length === 0 && <p className="muted">None yet.</p>}
        <ul className="list">
          {rows.map((r) => (
            <li key={r.id}>
              <span>
                {nairobiTime(r.created_at)}{" "}
                <span
                  className={`status ${r.status === "ready" ? "ok" : r.status === "failed" ? "bad" : "warn"}`}
                >
                  {STATE[r.status]}
                </span>{" "}
                <span className="muted">
                  {r.include_photos ? "with photos" : "without photos"} {mb(r.size_bytes)}
                  {r.error ? ` ${r.error}` : ""}
                </span>
              </span>
              {r.status === "ready" && (
                <button className="btn" type="button" onClick={() => download(r)}>
                  <Download size={16} /> Download
                </button>
              )}
            </li>
          ))}
        </ul>
      </Card>
    </>
  );
}
