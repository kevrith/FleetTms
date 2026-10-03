import type { MonthForecast } from "@fleettms/types";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { kes } from "../labels";
import { Card } from "../ui";

const money = (cents: number | null) => (cents === null ? "no forecast yet" : kes(cents));

/** How this month is likely to end, with the working shown as plain sentences so it can be checked. */
export function ForecastCard() {
  const { can } = useAuth();
  const [data, setData] = useState<MonthForecast | null>(null);
  const allowed = can("finance.view");
  useEffect(() => {
    if (allowed)
      api
        .monthForecast()
        .then(setData)
        .catch(() => setData(null));
  }, [allowed]);
  if (!allowed || !data) return null;
  const b = data.business;
  return (
    <Card title="How this month is likely to end">
      <p>
        {b.projected_net_cents === null ? (
          <span className="muted">
            There are no earlier months to learn a daily average from yet, so there is no forecast.
          </span>
        ) : (
          <>
            About{" "}
            <strong className={b.projected_net_cents < 0 ? "status bad" : "status ok"}>
              {kes(b.projected_net_cents)}
            </strong>{" "}
            after lease, finance, ownership and overhead costs.
          </>
        )}
      </p>
      <ul>
        {data.steps.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      {data.booked_work.jobs > 0 && (
        <p className="muted">
          Booked work not yet delivered: {data.booked_work.jobs} job
          {data.booked_work.jobs === 1 ? "" : "s"}, expected profit{" "}
          {kes(data.booked_work.expected_profit_cents)}. It is part of what the daily average
          already brings in, not on top of it.
        </p>
      )}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Vehicle</th>
              <th>Profit so far</th>
              <th>Likely for the month</th>
            </tr>
          </thead>
          <tbody>
            {data.vehicles.map((v) => (
              <tr key={v.vehicle_id}>
                <td>{v.registration}</td>
                <td>{kes(v.gross_to_date_cents)}</td>
                <td>{money(v.projected_net_cents)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted">
        Profit so far is before lease, finance and ownership charges, which are taken off the
        month's total as the last three months averaged them.
      </p>
    </Card>
  );
}
