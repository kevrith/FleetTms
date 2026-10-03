import type { BehaviourEvent, BehaviourSummary } from "@fleettms/types";
import { useEffect, useState } from "react";
import { api } from "../api";
import { BEHAVIOUR_KIND, nairobiTime } from "../labels";
import { Card, ErrorBanner, errorMessage } from "../ui";

const KINDS = Object.keys(BEHAVIOUR_KIND);

function counts(c: Record<string, number>) {
  return KINDS.filter((k) => c[k]).map((k) => `${c[k]} ${(BEHAVIOUR_KIND[k] ?? k).toLowerCase()}`);
}

function describe(e: BehaviourEvent): string {
  if (e.kind === "speeding" && e.value != null)
    return `up to ${Math.round(e.value)} km/h${e.limit ? ` (limit ${Math.round(e.limit)})` : ""}`;
  if (e.kind === "idling" && e.value != null) return `${Math.round(e.value)} minutes`;
  if (e.kind === "harsh_braking" && e.value != null)
    return `${e.value.toFixed(1)} km/h lost per second`;
  if (e.value != null) return String(Math.round(e.value * 10) / 10);
  return "";
}

/** Speeding, harsh braking and idling, found in the GPS fixes and given to the driver who was on the trip. */
export default function Behaviour() {
  const [summary, setSummary] = useState<BehaviourSummary | null>(null);
  const [events, setEvents] = useState<BehaviourEvent[]>([]);
  const [kind, setKind] = useState("");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api
      .behaviourSummary()
      .then(setSummary)
      .catch((e) => setError(errorMessage(e)));
  }, []);
  useEffect(() => {
    api
      .behaviourEvents({ kind: kind || undefined, limit: 100 })
      .then(setEvents)
      .catch((e) => setError(errorMessage(e)));
  }, [kind]);
  return (
    <>
      <ErrorBanner message={error} />
      <p className="muted">
        The last 30 days. A tracker gives the most reliable reading; with no tracker the phone's
        fixes are used, which can miss a short event.
      </p>
      <Card title="By driver">
        {summary && summary.drivers.length === 0 && <p className="muted">No events.</p>}
        <ul className="list">
          {summary?.drivers.map((d) => (
            <li key={d.driver_membership_id}>
              <span>
                <strong>{d.name ?? "Unknown driver"}</strong>{" "}
                <span className="muted">{counts(d.counts).join(", ")}</span>
              </span>
              <span>{d.total}</span>
            </li>
          ))}
        </ul>
      </Card>
      <Card title="By vehicle">
        <ul className="list">
          {summary?.vehicles.map((v) => (
            <li key={v.vehicle_id}>
              <span>
                <strong>{v.registration}</strong>{" "}
                <span className="muted">{counts(v.counts).join(", ")}</span>
              </span>
              <span>{v.total}</span>
            </li>
          ))}
        </ul>
      </Card>
      <Card title="Events">
        <label className="field">
          <span>Show</span>
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">Everything</option>
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {BEHAVIOUR_KIND[k]}
              </option>
            ))}
          </select>
        </label>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>When</th>
                <th>Vehicle</th>
                <th>Driver</th>
                <th>What</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => (
                <tr key={e.id}>
                  <td>{nairobiTime(e.at)}</td>
                  <td>{e.registration}</td>
                  <td>{e.driver ?? ""}</td>
                  <td>
                    {BEHAVIOUR_KIND[e.kind] ?? e.label} <span className="muted">{describe(e)}</span>
                  </td>
                  <td>{e.source === "tracker" ? "Tracker" : "Phone"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
