import type { ReportSchedule, ReportSummary } from "@fleettms/types";
import { Download, Pause, Play, Send, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { EXPENSE_CATEGORY, kes, todayIso } from "../labels";
import { useAuth } from "../auth";
import { Card, ErrorBanner, errorMessage } from "../ui";

const FREQUENCY = {
  daily: "Every day (yesterday)",
  weekly: "Every Monday (last week)",
  monthly: "1st of the month (last month)",
};
const CHANNEL = { email: "Email", whatsapp: "WhatsApp" };

/** Reports sent as a PDF on a schedule, by email or WhatsApp. */
function ScheduledReports() {
  const [rows, setRows] = useState<ReportSchedule[]>([]);
  const [form, setForm] = useState<{
    frequency: ReportSchedule["frequency"];
    channel: ReportSchedule["channel"];
    recipient: string;
  }>({ frequency: "weekly", channel: "email", recipient: "" });
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRows(await api.reportSchedules());
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  async function act(work: () => Promise<unknown>, done?: string) {
    setError(null);
    setNote(null);
    try {
      await work();
      if (done) setNote(done);
      await load();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  return (
    <Card title="Scheduled reports">
      <ErrorBanner message={error} />
      {note && <p className="banner ok">{note}</p>}
      {rows.length === 0 && <p className="muted">No scheduled reports yet.</p>}
      <ul className="list">
        {rows.map((s) => (
          <li key={s.id}>
            <span>
              {CHANNEL[s.channel]} to {s.recipient}: {FREQUENCY[s.frequency]}
              {!s.is_active && " (paused)"}
              {s.last_error && <span className="muted"> Last attempt failed: {s.last_error}</span>}
            </span>
            <span className="actions">
              <button
                className="btn"
                title="Send the latest report now"
                onClick={() => act(() => api.sendReportScheduleNow(s.id), "Report sent.")}
              >
                <Send size={16} />
              </button>
              <button
                className="btn"
                title={s.is_active ? "Pause" : "Resume"}
                onClick={() => act(() => api.setReportScheduleActive(s.id, !s.is_active))}
              >
                {s.is_active ? <Pause size={16} /> : <Play size={16} />}
              </button>
              <button
                className="btn"
                title="Delete"
                onClick={() => act(() => api.deleteReportSchedule(s.id))}
              >
                <Trash2 size={16} />
              </button>
            </span>
          </li>
        ))}
      </ul>
      <div className="form-grid">
        <label className="field">
          <span>How often</span>
          <select
            value={form.frequency}
            onChange={(e) =>
              setForm({ ...form, frequency: e.target.value as typeof form.frequency })
            }
          >
            {Object.entries(FREQUENCY).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Send by</span>
          <select
            value={form.channel}
            onChange={(e) => setForm({ ...form, channel: e.target.value as typeof form.channel })}
          >
            {Object.entries(CHANNEL).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>{form.channel === "email" ? "Email address" : "WhatsApp number"}</span>
          <input
            value={form.recipient}
            onChange={(e) => setForm({ ...form, recipient: e.target.value })}
          />
        </label>
        <button
          className="btn primary"
          disabled={!form.recipient.trim()}
          onClick={() =>
            act(async () => {
              await api.createReportSchedule(form);
              setForm({ ...form, recipient: "" });
            })
          }
        >
          Add
        </button>
      </div>
      <p className="muted">Each report is sent once, as a PDF, at 06:30 Nairobi time.</p>
    </Card>
  );
}

const shift = (iso: string, days: number) => {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
};

/** Daily, weekly, monthly or any date range: trips, distance, fuel and expenses, by category, vehicle and day. */
export default function Reports() {
  const { can } = useAuth();
  const today = todayIso();
  const [range, setRange] = useState({ from: today, to: today });
  const [data, setData] = useState<ReportSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async (from: string, to: string) => {
    setError(null);
    try {
      setData(await api.reportSummary(from, to));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => {
    void run(today, today);
  }, [run, today]);

  const preset = (from: string, to: string) => {
    setRange({ from, to });
    void run(from, to);
  };
  async function download(format: "xlsx" | "pdf") {
    setError(null);
    try {
      const url = URL.createObjectURL(await api.exportReport(data!.from, data!.to, format));
      const a = document.createElement("a");
      a.href = url;
      a.download = `fleettms-report-${data!.from}-to-${data!.to}.${format}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  const t = data?.totals;
  return (
    <>
      <h2>Reports</h2>
      <Card title="Date range">
        <p className="actions">
          <button className="btn" onClick={() => preset(today, today)}>
            Today
          </button>
          <button className="btn" onClick={() => preset(shift(today, -6), today)}>
            Last 7 days
          </button>
          <button className="btn" onClick={() => preset(`${today.slice(0, 8)}01`, today)}>
            This month
          </button>
        </p>
        <div className="form-grid">
          <label className="field">
            <span>From</span>
            <input
              type="date"
              value={range.from}
              onChange={(e) => setRange({ ...range, from: e.target.value })}
            />
          </label>
          <label className="field">
            <span>To</span>
            <input
              type="date"
              value={range.to}
              onChange={(e) => setRange({ ...range, to: e.target.value })}
            />
          </label>
          <button className="btn primary" onClick={() => run(range.from, range.to)}>
            Show report
          </button>
        </div>
      </Card>
      <ErrorBanner message={error} />
      {t && (
        <>
          <p className="actions">
            <button className="btn" onClick={() => download("xlsx")}>
              <Download size={16} /> Excel
            </button>
            <button className="btn" onClick={() => download("pdf")}>
              <Download size={16} /> PDF
            </button>
          </p>
          <Card title="Totals">
            <ul className="list">
              <li>
                <span>Trips completed</span>
                <strong>{t.trips_completed}</strong>
              </li>
              <li>
                <span>Distance driven</span>
                <strong>{t.distance_km.toLocaleString()} km</strong>
              </li>
              <li>
                <span>Fuel</span>
                <strong>
                  {kes(t.fuel_cents)} ({t.fuel_litres} litres)
                </strong>
              </li>
              <li>
                <span>Expenses</span>
                <strong>{kes(t.expenses_cents)}</strong>
              </li>
              <li>
                <span>Floats sent</span>
                <strong>{kes(t.floats_sent_cents)}</strong>
              </li>
            </ul>
            <p className="muted">
              Income, profit and money owed arrive with quotes, jobs and billing.
            </p>
          </Card>
          <Card title="Expenses by type">
            {data.expenses_by_category.length === 0 && (
              <p className="muted">No expenses in this range.</p>
            )}
            <ul className="list">
              {data.expenses_by_category.map((c) => (
                <li key={c.category}>
                  <span>{EXPENSE_CATEGORY[c.category]}</span>
                  <strong>{kes(c.cents)}</strong>
                </li>
              ))}
            </ul>
          </Card>
          <Card title="By vehicle">
            {data.by_vehicle.length === 0 && <p className="muted">No activity in this range.</p>}
            {data.by_vehicle.length > 0 && (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Vehicle</th>
                      <th>Trips</th>
                      <th>Distance</th>
                      <th>Fuel</th>
                      <th>Km per litre</th>
                      <th>Expenses</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.by_vehicle.map((v) => (
                      <tr key={v.vehicle_id}>
                        <td>{v.registration}</td>
                        <td>{v.trips}</td>
                        <td>{v.distance_km.toLocaleString()} km</td>
                        <td>{kes(v.fuel_cents)}</td>
                        <td>{v.km_per_litre ?? ""}</td>
                        <td>{kes(v.expenses_cents)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
          {data.by_day.length > 1 && (
            <Card title="By day">
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Day</th>
                      <th>Trips</th>
                      <th>Distance</th>
                      <th>Fuel</th>
                      <th>Expenses</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.by_day.map((d) => (
                      <tr key={d.day}>
                        <td>{d.day}</td>
                        <td>{d.trips}</td>
                        <td>{d.distance_km.toLocaleString()} km</td>
                        <td>{kes(d.fuel_cents)}</td>
                        <td>{kes(d.expenses_cents)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
        </>
      )}
      {can("reports.schedule") && <ScheduledReports />}
    </>
  );
}
