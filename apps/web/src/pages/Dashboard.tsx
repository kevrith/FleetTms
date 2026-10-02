import type { Dashboard as DashboardData } from "@fleettms/types";
import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { kes } from "../labels";
import { Card, ErrorBanner, errorMessage } from "../ui";

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="card" style={{ minWidth: 180 }}>
      <p className="muted">{label}</p>
      <p style={{ fontSize: 26, fontWeight: 700, margin: "4px 0" }}>{value}</p>
      {note && <p className="muted">{note}</p>}
    </div>
  );
}

/** Owner home: how is my business doing right now. Today's numbers, then what needs attention, most urgent first. */
export default function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .dashboard()
      .then(setData)
      .catch((e) => setError(errorMessage(e)));
  }, []);

  if (error) return <ErrorBanner message={error} />;
  if (!data) return <p className="muted">Loading today's numbers...</p>;
  const n = data.numbers;
  return (
    <>
      {n.mode === "owner_driver" && (
        <p className="muted">
          Owner-driver mode: you are also a driver, so you are not asked to approve your own
          entries.
        </p>
      )}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
        {n.trips_active !== undefined && (
          <Stat label="Trips running" value={String(n.trips_active)} />
        )}
        {n.trips_completed_today !== undefined && (
          <Stat
            label="Trips completed today"
            value={String(n.trips_completed_today)}
            note={`${(n.distance_today_km ?? 0).toLocaleString()} km driven`}
          />
        )}
        {n.fuel_today && (
          <Stat
            label="Fuel today"
            value={kes(n.fuel_today.amount_cents)}
            note={`${n.fuel_today.litres} litres`}
          />
        )}
        {n.expenses_today_cents !== undefined && (
          <Stat label="Expenses today" value={kes(n.expenses_today_cents)} />
        )}
        {n.floats_sent_today_cents !== undefined && (
          <Stat label="Floats sent today" value={kes(n.floats_sent_today_cents)} />
        )}
        <Stat label="Income today" value="Not yet" note="Arrives with quotes, jobs and billing" />
        <Stat label="Money owed to you" value="Not yet" note="Arrives with billing" />
      </div>
      <Card title="Needs attention">
        {data.alerts.length === 0 && (
          <p className="status ok">
            <CheckCircle2 size={18} /> Nothing needs your attention right now.
          </p>
        )}
        <ul className="list">
          {data.alerts.map((a, i) => (
            <li key={`${a.kind}-${i}`}>
              <span>
                <span className={`status ${a.severity === "red" ? "bad" : "warn"}`}>
                  <AlertTriangle size={16} />
                </span>{" "}
                <Link to={a.link}>{a.title}</Link>
                {a.detail && <span className="muted"> {a.detail}</span>}
              </span>
            </li>
          ))}
        </ul>
      </Card>
    </>
  );
}
