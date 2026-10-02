import type { ProfitReport } from "@fleettms/types";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { kes, todayIso } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

const OWNERSHIP: Record<string, string> = {
  owned: "Owned",
  asset_financed: "Financed",
  leased_in: "Leased in",
  leased_out: "Leased out",
};
const pct = (a: number, b: number) => (b ? `${Math.round((a / b) * 100)}%` : "");

/** What each lorry, client, driver, depot and the business really made, after every deduction. */
export function ProfitPage() {
  const [from, setFrom] = useState(todayIso().slice(0, 7));
  const [to, setTo] = useState(todayIso().slice(0, 7));
  const [data, setData] = useState<ProfitReport | null>(null);
  const [trips, setTrips] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setError(null);
      setData(await api.profit(`${from}-01`, `${to}-01`, trips));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [from, to, trips]);
  useEffect(() => {
    void load();
  }, [load]);
  const b = data?.business;
  return (
    <>
      <ErrorBanner message={error} />
      <Card title="Profit">
        <div className="form-grid">
          <Field label="From month">
            <input type="month" value={from} onChange={(e) => setFrom(e.target.value)} />
          </Field>
          <Field label="To month">
            <input type="month" value={to} onChange={(e) => setTo(e.target.value)} />
          </Field>
          <label className="field">
            <span>
              <input type="checkbox" checked={trips} onChange={(e) => setTrips(e.target.checked)} />{" "}
              Show every trip
            </span>
          </label>
        </div>
        {b && (
          <ul className="list">
            <li>
              <span>Revenue (before VAT)</span>
              <strong>{kes(b.revenue)}</strong>
            </li>
            <li>
              <span>Costs of running (fuel, expenses, crew)</span>
              <strong>{kes(b.operating)}</strong>
            </li>
            <li>
              <span>Gross profit</span>
              <strong>{kes(b.gross)}</strong>
            </li>
            <li>
              <span>Paid to lorry owners, after costs paid on their behalf</span>
              <strong>{kes(b.lease_payable)}</strong>
            </li>
            <li>
              <span>Loan repayments</span>
              <strong>{kes(b.finance)}</strong>
            </li>
            <li>
              <span>Insurance, licences and depreciation</span>
              <strong>{kes(b.ownership)}</strong>
            </li>
            <li>
              <span>Net profit of the lorries</span>
              <strong>{kes(b.net)}</strong>
            </li>
            <li>
              <span>Office costs and pay not tied to a lorry</span>
              <strong>{kes(b.overheads)}</strong>
            </li>
            <li>
              <span>Net profit of the business</span>
              <strong>{kes(b.net_after_overheads)}</strong>
            </li>
          </ul>
        )}
        {b && (b.unbilled > 0 || b.estimated > 0) && (
          <p className="muted">
            {b.unbilled > 0 &&
              `${b.unbilled} delivered trip${b.unbilled === 1 ? " has" : "s have"} no invoice yet, so no revenue. `}
            {b.estimated > 0 &&
              `${b.estimated} contract trip${b.estimated === 1 ? " uses" : "s use"} an estimated share of the monthly fee until its invoice is issued.`}
          </p>
        )}
        <p className="muted">
          Salaries come from approved payroll runs, or from the salaries on file where no run is
          approved yet. A cost the lease makes the owner's responsibility is left out of your costs
          and comes back through the offset.
        </p>
      </Card>
      {data && (
        <Card title="By vehicle">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Vehicle</th>
                  <th>Revenue</th>
                  <th>Gross profit</th>
                  <th>To owner</th>
                  <th>Loan</th>
                  <th>Fixed</th>
                  <th>Net profit</th>
                  <th>Cost a km</th>
                  <th>Empty km</th>
                </tr>
              </thead>
              <tbody>
                {data.vehicles.map((v) => (
                  <tr key={v.vehicle_id}>
                    <td>
                      {v.registration} <span className="muted">{OWNERSHIP[v.ownership_type]}</span>
                      {v.lease_not_paying && (
                        <div className="status warn">
                          The owner has earned more than you for three months. Is this lease worth
                          it?
                        </div>
                      )}
                    </td>
                    <td>{kes(v.revenue)}</td>
                    <td>{kes(v.gross)}</td>
                    <td>{v.lease_payable ? kes(v.lease_payable) : ""}</td>
                    <td>{v.finance ? kes(v.finance) : ""}</td>
                    <td>{v.ownership ? kes(v.ownership) : ""}</td>
                    <td>
                      <strong>{kes(v.net)}</strong>
                    </td>
                    <td>{v.cost_per_km !== null ? kes(v.cost_per_km) : ""}</td>
                    <td>{pct(v.empty_km, v.km)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
      {data && data.depots.length > 1 && (
        <Card title="By depot">
          <ul className="list">
            {data.depots.map((d) => (
              <li key={d.name}>
                <span>
                  {d.name} ({d.vehicles} vehicle{d.vehicles === 1 ? "" : "s"})
                </span>
                <strong>{kes(d.net)}</strong>
              </li>
            ))}
          </ul>
        </Card>
      )}
      {data && (
        <Card title="By client and by driver">
          <p className="muted">Revenue less the fuel and expenses booked to each trip.</p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Client</th>
                  <th>Trips</th>
                  <th>Revenue</th>
                  <th>Trip costs</th>
                  <th>Left over</th>
                </tr>
              </thead>
              <tbody>
                {data.clients.map((c) => (
                  <tr key={c.name}>
                    <td>{c.name}</td>
                    <td>{c.trips}</td>
                    <td>{kes(c.revenue_cents)}</td>
                    <td>{kes(c.direct_cost_cents)}</td>
                    <td>{kes(c.contribution_cents)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Driver</th>
                  <th>Trips</th>
                  <th>Revenue</th>
                  <th>Trip costs</th>
                  <th>Left over</th>
                </tr>
              </thead>
              <tbody>
                {data.drivers.map((c) => (
                  <tr key={c.name}>
                    <td>{c.name}</td>
                    <td>{c.trips}</td>
                    <td>{kes(c.revenue_cents)}</td>
                    <td>{kes(c.direct_cost_cents)}</td>
                    <td>{kes(c.contribution_cents)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
      {data && trips && (
        <Card title="Trips">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Delivered</th>
                  <th>Vehicle</th>
                  <th>Route</th>
                  <th>Client</th>
                  <th>Revenue</th>
                  <th>Costs</th>
                  <th>Left over</th>
                </tr>
              </thead>
              <tbody>
                {data.trips.map((t) => (
                  <tr key={t.trip_id}>
                    <td>{new Date(t.delivered_at).toLocaleDateString("en-KE")}</td>
                    <td>
                      <Link to={`/trips/${t.trip_id}`}>{t.registration}</Link>
                    </td>
                    <td>{t.route}</td>
                    <td>{t.client_name}</td>
                    <td>
                      {kes(t.revenue_cents)}
                      {t.estimated && <span className="muted"> est.</span>}
                      {t.unbilled && <span className="muted"> not invoiced</span>}
                    </td>
                    <td>{kes(t.direct_cost_cents)}</td>
                    <td>{kes(t.contribution_cents)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </>
  );
}
