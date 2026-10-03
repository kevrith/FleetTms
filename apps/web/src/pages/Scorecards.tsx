import type { DriverScorecard, Scorecards as ScorecardData } from "@fleettms/types";
import { useEffect, useState } from "react";
import { api } from "../api";
import { BEHAVIOUR_KIND, todayIso } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

const PART: [keyof DriverScorecard, string][] = [
  ["safety", "Safety"],
  ["fuel", "Fuel"],
  ["punctuality", "On time"],
  ["inspections", "Inspections"],
  ["alerts", "Alerts"],
];

function daysAgo(n: number): string {
  const d = new Date(`${todayIso()}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() - n);
  return d.toISOString().slice(0, 10);
}

function Score({ value }: { value: number | null }) {
  if (value === null) return <span className="muted">no data</span>;
  const tone = value >= 80 ? "ok" : value >= 60 ? "warn" : "bad";
  return <span className={`status ${tone}`}>{value}</span>;
}

function Detail({ d }: { d: DriverScorecard }) {
  const behaviour = Object.entries(d.detail.behaviour)
    .map(([k, n]) => `${n} ${(BEHAVIOUR_KIND[k] ?? k).toLowerCase()}`)
    .join(", ");
  return (
    <ul className="list">
      <li>
        <span>Safety</span>
        <span className="muted">
          {behaviour || "No speeding, hard braking or similar events"} over {d.km.toLocaleString()}{" "}
          km
        </span>
      </li>
      <li>
        <span>Fuel</span>
        <span className="muted">
          {d.detail.avg_fuel_variance_pct === null
            ? "No trip had a normal to compare with yet"
            : `${d.detail.trips_with_fuel_checked} trip${d.detail.trips_with_fuel_checked === 1 ? "" : "s"} checked, on average ${d.detail.avg_fuel_variance_pct}% above expected`}
        </span>
      </li>
      <li>
        <span>On time</span>
        <span className="muted">
          {d.detail.timed_trips === 0
            ? "No trip had a scheduled start"
            : `${d.detail.on_time} of ${d.detail.timed_trips} started within 30 minutes of the booking`}
        </span>
      </li>
      <li>
        <span>Inspections</span>
        <span className="muted">
          {d.detail.clean_inspections} clean, {d.detail.inspections_with_defects} with defects, of{" "}
          {d.trips} trips
        </span>
      </li>
      <li>
        <span>Alerts</span>
        <span className="muted">
          {d.detail.alerts_confirmed} confirmed, {d.detail.alerts_open} waiting,{" "}
          {d.detail.alerts_explained} explained
        </span>
      </li>
    </ul>
  );
}

/** How each driver did over a period: safety, fuel, punctuality, inspections and alerts, and an overall score. */
export default function Scorecards() {
  const [from, setFrom] = useState(daysAgo(29));
  const [to, setTo] = useState(todayIso());
  const [data, setData] = useState<ScorecardData | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api
      .scorecards(from, to)
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e) => setError(errorMessage(e)));
  }, [from, to]);
  return (
    <>
      <h2>Driver scorecards</h2>
      <ErrorBanner message={error} />
      <Card title="Period">
        <div className="form-grid">
          <Field label="From">
            <input type="date" value={from} max={to} onChange={(e) => setFrom(e.target.value)} />
          </Field>
          <Field label="To">
            <input type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} />
          </Field>
        </div>
        <p className="muted">
          Each part is out of 100. The overall score weighs safety 30%, fuel 25%, and punctuality,
          inspections and alerts 15% each; a part with no data is left out. Use it for coaching and
          for bonuses, not as proof of anything on its own.
        </p>
      </Card>
      <Card title="Drivers">
        {data && data.drivers.length === 0 && <p className="muted">Nobody drove in this period.</p>}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Driver</th>
                <th>Trips</th>
                <th>Km</th>
                {PART.map(([, text]) => (
                  <th key={text}>{text}</th>
                ))}
                <th>Overall</th>
              </tr>
            </thead>
            <tbody>
              {data?.drivers.flatMap((d) => [
                <tr
                  key={d.membership_id}
                  onClick={() => setOpen(open === d.membership_id ? null : d.membership_id)}
                  style={{ cursor: "pointer" }}
                >
                  <td>{d.name}</td>
                  <td>{d.trips}</td>
                  <td>{d.km.toLocaleString()}</td>
                  {PART.map(([key]) => (
                    <td key={key}>
                      <Score value={d[key] as number | null} />
                    </td>
                  ))}
                  <td>
                    <strong>
                      <Score value={d.overall} />
                    </strong>
                  </td>
                </tr>,
                open === d.membership_id ? (
                  <tr key={`${d.membership_id}-detail`}>
                    <td colSpan={9}>
                      <Detail d={d} />
                    </td>
                  </tr>
                ) : null,
              ])}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
