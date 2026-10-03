import type { FuelLevel, VehicleModelInfo } from "@fleettms/types";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { nairobiTime } from "../labels";
import { Card, ErrorBanner, errorMessage } from "../ui";

const RANGES: [string, number][] = [
  ["Last 6 hours", 6],
  ["Last 24 hours", 24],
  ["Last 3 days", 72],
  ["Last 7 days", 168],
];
const W = 640;
const H = 240;
const PAD = { l: 44, r: 12, t: 12, b: 28 };

/** The tank's level over time with refills, parked drops and the fuel that was bought marked on it. */
export function FuelLevelCard({ vehicleId }: { vehicleId: string }) {
  const { can } = useAuth();
  const [hours, setHours] = useState(24);
  const [data, setData] = useState<FuelLevel | null>(null);
  const [error, setError] = useState<string | null>(null);
  const allowed = can("vehicles.view");
  useEffect(() => {
    if (!allowed) return;
    const end = new Date();
    api
      .fuelLevel(
        vehicleId,
        new Date(end.getTime() - hours * 3600_000).toISOString(),
        end.toISOString(),
      )
      .then(setData)
      .catch((e) => setError(errorMessage(e)));
  }, [vehicleId, hours, allowed]);
  const chart = useMemo(() => {
    if (!data || data.points.length === 0) return null;
    const t0 = Date.parse(data.from);
    const t1 = Date.parse(data.to);
    const top = Math.max(data.tank_litres ?? 0, ...data.points.map((p) => p.litres)) * 1.05 || 1;
    const x = (iso: string) => PAD.l + ((Date.parse(iso) - t0) / (t1 - t0)) * (W - PAD.l - PAD.r);
    const y = (litres: number) => PAD.t + (1 - litres / top) * (H - PAD.t - PAD.b);
    return {
      x,
      y,
      top,
      line: data.points.map((p) => `${x(p.at).toFixed(1)},${y(p.litres).toFixed(1)}`).join(" "),
    };
  }, [data]);
  if (!allowed || !data || !data.has_sensor) return null;
  return (
    <Card title="Fuel level">
      <ErrorBanner message={error} />
      <label className="field">
        <span>Period</span>
        <select value={hours} onChange={(e) => setHours(Number(e.target.value))}>
          {RANGES.map(([label, h]) => (
            <option key={h} value={h}>
              {label}
            </option>
          ))}
        </select>
      </label>
      {!chart && <p className="muted">The fuel sensor has not reported in this period.</p>}
      {chart && (
        <svg
          viewBox={`0 0 ${W} ${H}`}
          role="img"
          aria-label={`Fuel level of ${data.registration}, ${data.events.length} refills or drops`}
          style={{ width: "100%", height: "auto" }}
        >
          {[0, 0.5, 1].map((f) => (
            <g key={f}>
              <line
                x1={PAD.l}
                x2={W - PAD.r}
                y1={chart.y(chart.top * f)}
                y2={chart.y(chart.top * f)}
                stroke="currentColor"
                opacity={0.15}
              />
              <text
                x={PAD.l - 6}
                y={chart.y(chart.top * f) + 4}
                fontSize="11"
                textAnchor="end"
                fill="currentColor"
              >
                {Math.round(chart.top * f)}
              </text>
            </g>
          ))}
          <polyline points={chart.line} fill="none" stroke="#2563eb" strokeWidth={2} />
          {data.purchases.map((p) => (
            <line
              key={p.at}
              x1={chart.x(p.at)}
              x2={chart.x(p.at)}
              y1={PAD.t}
              y2={H - PAD.b}
              stroke="#d97706"
              strokeDasharray="4 3"
            />
          ))}
          {data.events.map((e) => (
            <circle
              key={e.start}
              cx={chart.x(e.start)}
              cy={chart.y(e.kind === "drop" ? e.after : e.before)}
              r={6}
              fill={e.kind === "drop" ? "#dc2626" : "#16a34a"}
              stroke="#fff"
              strokeWidth={2}
            />
          ))}
          <text x={PAD.l} y={H - 8} fontSize="11" fill="currentColor">
            {nairobiTime(data.from)}
          </text>
          <text x={W - PAD.r} y={H - 8} fontSize="11" textAnchor="end" fill="currentColor">
            {nairobiTime(data.to)}
          </text>
        </svg>
      )}
      <p className="muted">
        Levels in litres{data.unit === "percent" ? " (the sensor reports percent of the tank)" : ""}
        . Red dots are fuel leaving a parked lorry, green dots are refills, and dashed lines are
        fuel purchases that were recorded.
      </p>
      <ul className="list">
        {data.events.map((e) => (
          <li key={e.start}>
            <span style={{ color: e.kind === "drop" ? "#dc2626" : "#16a34a" }}>
              {e.kind === "drop" ? "Drop" : "Refill"} of {e.litres} litres
            </span>
            <span className="muted">
              {e.before} to {e.after} litres, {nairobiTime(e.start)}
            </span>
          </li>
        ))}
        {data.purchases.map((p) => (
          <li key={p.at}>
            <span>
              Bought {p.litres} litres{p.station ? ` at ${p.station}` : ""}
            </span>
            <span className="muted">{nairobiTime(p.at)}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

/** What has been learned about this vehicle's fuel use from its own trips, and whether it is trusted yet. */
export function ModelCard({ vehicleId }: { vehicleId: string }) {
  const { can } = useAuth();
  const [m, setM] = useState<VehicleModelInfo | null>(null);
  const allowed = can("vehicles.view");
  useEffect(() => {
    if (allowed)
      api
        .vehicleModel(vehicleId)
        .then(setM)
        .catch(() => setM(null));
  }, [vehicleId, allowed]);
  if (!allowed || !m) return null;
  return (
    <Card title="What we have learned about its fuel use">
      <p>
        <span className={`status ${m.reliable ? "ok" : "warn"}`}>
          {m.trained
            ? m.reliable
              ? "Used alongside the rules"
              : "Not trusted yet"
            : "Nothing learned yet"}
        </span>{" "}
        <span className="muted">{m.message}</span>
      </p>
      {m.trained && (
        <ul className="list">
          <li>
            <span>Every kilometre</span>
            <span>{m.litres_per_km?.toFixed(3)} litres</span>
          </li>
          <li>
            <span>Every tonne carried a kilometre</span>
            <span>{m.litres_per_tonne_km?.toFixed(5)} litres</span>
          </li>
          <li>
            <span>Every hour of idling</span>
            <span>{m.litres_per_idle_hour?.toFixed(1)} litres</span>
          </li>
          <li>
            <span>Worked out from</span>
            <span className="muted">
              {m.trips} trips. It explains {Math.round((m.r2 ?? 0) * 100)}% of how their fuel varied
              and is usually within {m.sigma_litres} litres.
            </span>
          </li>
        </ul>
      )}
    </Card>
  );
}
