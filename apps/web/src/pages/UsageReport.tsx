import type { FunnelReport, UsageReport as Usage } from "@fleettms/types";
import { useEffect, useState } from "react";
import { api } from "../api";
import { Card, ErrorBanner, errorMessage } from "../ui";

/** Where new businesses get stuck, and which parts of the product are used. Counts only: no people, no records, no content. */
export default function UsageReport() {
  const [usage, setUsage] = useState<Usage | null>(null);
  const [funnel, setFunnel] = useState<FunnelReport | null>(null);
  const [days, setDays] = useState(30);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    Promise.all([api.usageReport(days), api.funnelReport(12)])
      .then(([u, f]) => {
        setUsage(u);
        setFunnel(f);
      })
      .catch((e) => setError(errorMessage(e)));
  }, [days]);
  return (
    <>
      <ErrorBanner message={error} />
      {funnel && (
        <Card title="From sign-up to paying (last 12 weeks)">
          <p className="muted">
            Worked out from what each business has done: sample data and free accounts are left out.
            "Stopped here" counts businesses that reached the step before and went no further.
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Step</th>
                  <th>Businesses</th>
                  <th>Share of sign-ups</th>
                  <th>Stopped here</th>
                </tr>
              </thead>
              <tbody>
                {funnel.steps.map((s) => (
                  <tr key={s.step}>
                    <td>{s.label}</td>
                    <td>{s.businesses}</td>
                    <td>{s.share_pct === null ? "" : `${s.share_pct}%`}</td>
                    <td>{s.stuck}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
      {usage && (
        <Card title="What is used">
          <p>
            <label>
              Last{" "}
              <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
                {[7, 30, 90].map((d) => (
                  <option key={d} value={d}>
                    {d} days
                  </option>
                ))}
              </select>
            </label>{" "}
            {usage.businesses_active} businesses active. Today's counts are added overnight.
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Part of the product</th>
                  <th>Businesses using it</th>
                  <th>Requests</th>
                </tr>
              </thead>
              <tbody>
                {usage.features.map((f) => (
                  <tr key={f.feature}>
                    <td>{f.feature}</td>
                    <td>{f.businesses}</td>
                    <td>{f.requests}</td>
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
