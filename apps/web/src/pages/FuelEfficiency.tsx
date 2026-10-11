import type {
  FuelEfficiency as FuelData,
  FuelEfficiencyVehicle,
  FuelFigures,
} from "@fleettms/types";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { kes } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

const PERIODS = [1, 3, 6, 12];

const num = (v: number | null, digits = 1) =>
  v === null ? "-" : v.toLocaleString("en-KE", { maximumFractionDigits: digits });

function Figures({ f }: { f: FuelFigures }) {
  return (
    <>
      <td>{f.km.toLocaleString()}</td>
      <td>{num(f.litres)}</td>
      <td>{num(f.l_per_100km)}</td>
      <td>{num(f.km_per_litre, 2)}</td>
      <td>{f.cost_per_km_cents === null ? "-" : kes(f.cost_per_km_cents)}</td>
    </>
  );
}

const HEAD = (
  <>
    <th>Km</th>
    <th>Litres</th>
    <th>L / 100 km</th>
    <th>Km / L</th>
    <th>Cost / km</th>
  </>
);

function Against({ v, limit }: { v: FuelEfficiencyVehicle; limit: number }) {
  if (v.vs_expected_pct === null) return <span className="muted">no expected figure</span>;
  const tone = v.above_expected ? "bad" : v.vs_expected_pct > limit / 2 ? "warn" : "ok";
  const sign = v.vs_expected_pct > 0 ? "+" : "";
  return (
    <span className={`status ${tone}`}>
      {sign}
      {v.vs_expected_pct}% vs {num(v.expected_km_per_litre, 2)} km/L
    </span>
  );
}

/** How much fuel each lorry, driver and route uses for the distance driven, month by month, and whether it is more than usual. */
export default function FuelEfficiency() {
  const [months, setMonths] = useState(3);
  const [data, setData] = useState<FuelData | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api
      .fuelEfficiency(months)
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e) => setError(errorMessage(e)));
  }, [months]);
  return (
    <>
      <h2>Fuel use</h2>
      <ErrorBanner message={error} />
      <Card title="Period">
        <div className="form-grid">
          <Field label="Months (this one and the ones before it)">
            <select value={months} onChange={(e) => setMonths(Number(e.target.value))}>
              {PERIODS.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <p className="muted">
          Distance is each finished trip's distance (the odometer, or GPS for a lorry set to use
          GPS). Fuel is everything recorded for the lorry in the period, so fuel bought between
          trips still counts. A lorry is marked when it uses more than{" "}
          {data ? `${data.limit_pct}%` : "the limit"} above the figure entered for it.
        </p>
      </Card>
      <Card title="Lorries">
        {data && data.vehicles.length === 0 && (
          <p className="muted">No finished trips or fuel in this period.</p>
        )}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Lorry</th>
                {HEAD}
                <th>Against expected</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data?.vehicles.map((v) => (
                <FragmentRow
                  key={v.vehicle_id}
                  v={v}
                  limit={data.limit_pct}
                  open={open === v.vehicle_id}
                  toggle={() => setOpen(open === v.vehicle_id ? null : v.vehicle_id)}
                />
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      {data && data.alerts.length > 0 && (
        <Card title="Fuel alerts in this period">
          <ul className="list">
            {data.alerts.map((a) => (
              <li key={a.id}>
                <span>
                  <span className={`status ${a.severity === "red" ? "bad" : "warn"}`}>
                    {a.severity}
                  </span>{" "}
                  {a.title}
                </span>
                <span className="muted">
                  {a.status}, {new Date(a.occurred_at).toLocaleDateString("en-KE")}
                </span>
              </li>
            ))}
          </ul>
          <p className="muted">
            <Link to="/alerts">Open alerts</Link> to explain or confirm them.
          </p>
        </Card>
      )}
      <Card title="Drivers">
        <p className="muted">
          Only fuel that can be tied to a trip (entered on it, or bought while it ran), set against
          the distance of those same trips. A driver with few trips counted is not a fair
          comparison.
        </p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Driver</th>
                <th>Trips counted</th>
                {HEAD}
              </tr>
            </thead>
            <tbody>
              {data?.drivers.map((d) => (
                <tr key={d.membership_id}>
                  <td>{d.name}</td>
                  <td>{d.trips_counted}</td>
                  <Figures f={d} />
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <Card title="Routes">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Route</th>
                <th>Trips counted</th>
                {HEAD}
              </tr>
            </thead>
            <tbody>
              {data?.routes.map((r) => (
                <tr key={r.route}>
                  <td>{r.route}</td>
                  <td>{r.trips_counted}</td>
                  <Figures f={r} />
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}

function FragmentRow({
  v,
  limit,
  open,
  toggle,
}: {
  v: FuelEfficiencyVehicle;
  limit: number;
  open: boolean;
  toggle: () => void;
}) {
  return (
    <>
      <tr>
        <td>
          <Link to={`/vehicles/${v.vehicle_id}`}>{v.registration}</Link>
          {v.distance_source === "gps" && <span className="muted"> (GPS distance)</span>}
        </td>
        <Figures f={v} />
        <td>
          <Against v={v} limit={limit} />
        </td>
        <td>
          <button type="button" className="btn" onClick={toggle}>
            {open ? "Hide months" : "Months"}
          </button>
        </td>
      </tr>
      {open &&
        v.monthly.map((m) => (
          <tr key={m.month} className="muted">
            <td>{m.month}</td>
            <Figures f={m} />
            <td />
            <td />
          </tr>
        ))}
    </>
  );
}
