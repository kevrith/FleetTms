import type { CatalogReport, ReportData } from "@fleettms/types";
import { Download } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { todayIso } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

function daysAgo(n: number): string {
  const d = new Date(`${todayIso()}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() - n);
  return d.toISOString().slice(0, 10);
}

const cell = (v: string | number | null) =>
  v === null ? "" : typeof v === "number" ? v.toLocaleString("en-KE") : v;

/** Every report in the catalogue: choose one and a period, read it here, and take it away as a PDF or an Excel file. */
export default function ReportLibrary() {
  const [catalog, setCatalog] = useState<CatalogReport[]>([]);
  const [key, setKey] = useState("");
  const [start, setStart] = useState(daysAgo(29));
  const [end, setEnd] = useState(todayIso());
  const [report, setReport] = useState<ReportData | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api
      .reportCatalog()
      .then((c) => {
        setCatalog(c);
        setKey((k) => k || (c.find((r) => r.available)?.key ?? ""));
      })
      .catch((e) => setError(errorMessage(e)));
  }, []);
  const chosen = catalog.find((r) => r.key === key);
  useEffect(() => {
    if (!key || !chosen?.available) {
      setReport(null);
      return;
    }
    api
      .runReport(key, start, end)
      .then((r) => {
        setReport(r);
        setError(null);
      })
      .catch((e) => {
        setReport(null);
        setError(errorMessage(e));
      });
  }, [key, start, end, chosen?.available]);

  async function download(fileFormat: "pdf" | "xlsx") {
    setError(null);
    try {
      const url = URL.createObjectURL(await api.reportFile(key, fileFormat, start, end));
      const a = document.createElement("a");
      a.href = url;
      a.download = `fleettms-${key}-${start}-to-${end}.${fileFormat}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  return (
    <>
      <h2>Reports</h2>
      <p>
        <Link to="/reports">Back to the daily summary and scheduled reports</Link>
      </p>
      <ErrorBanner message={error} />
      <Card title="Choose a report">
        <div className="form-grid">
          <Field label="Report">
            <select value={key} onChange={(e) => setKey(e.target.value)}>
              {catalog.map((r) => (
                <option key={r.key} value={r.key}>
                  {r.title}
                  {r.available ? "" : ` (needs ${r.plan_needed})`}
                </option>
              ))}
            </select>
          </Field>
          {chosen?.has_period !== false && (
            <>
              <Field label="From">
                <input
                  type="date"
                  value={start}
                  max={end}
                  onChange={(e) => setStart(e.target.value)}
                />
              </Field>
              <Field label="To">
                <input
                  type="date"
                  value={end}
                  min={start}
                  onChange={(e) => setEnd(e.target.value)}
                />
              </Field>
            </>
          )}
        </div>
        {chosen && <p className="muted">{chosen.description}</p>}
        {chosen && !chosen.available && (
          <p className="banner warn">
            This report is part of the {chosen.plan_needed} plan. Move a vehicle to it in Settings,
            Subscription.
          </p>
        )}
        {report && (
          <p className="actions">
            <button className="btn" type="button" onClick={() => download("xlsx")}>
              <Download size={16} /> Excel
            </button>
            <button className="btn" type="button" onClick={() => download("pdf")}>
              <Download size={16} /> PDF
            </button>
          </p>
        )}
      </Card>
      {report?.notes.map((n) => (
        <p key={n} className="muted">
          {n}
        </p>
      ))}
      {report?.sections.map((s) => (
        <Card key={s.title} title={s.title}>
          {s.rows.length === 0 && <p className="muted">Nothing in this period.</p>}
          {s.rows.length > 0 && (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    {s.columns.map((c) => (
                      <th key={c}>{c}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {s.rows.map((row, i) => (
                    <tr key={i}>
                      {row.map((v, j) => (
                        <td key={j}>{cell(v)}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      ))}
    </>
  );
}
