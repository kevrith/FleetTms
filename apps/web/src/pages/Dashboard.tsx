import type { Dashboard as DashboardData } from "@fleettms/types";
import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { kes } from "../labels";
import { Card, ErrorBanner, errorMessage } from "../ui";
import { OnboardingCard } from "./Onboarding";

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
      <OnboardingCard />
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
        {n.income_today_cents !== null && (
          <Stat label="Invoiced today" value={kes(n.income_today_cents)} note="Before VAT" />
        )}
        {n.money_owed_cents !== null && (
          <Stat label="Money owed to you" value={kes(n.money_owed_cents)} />
        )}
      </div>
      {data.profit_vs_cash && (
        <Card title="This month: profit on paper against cash in hand">
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
            <Stat
              label="Invoiced"
              value={kes(data.profit_vs_cash.billed_cents)}
              note="Before VAT"
            />
            <Stat
              label="Costs recorded"
              value={kes(data.profit_vs_cash.costs_cents)}
              note="Fuel and expenses"
            />
            <Stat
              label="Profit on paper"
              value={kes(data.profit_vs_cash.profit_cents)}
              note="Invoiced less costs"
            />
            <Stat label="Paid to you" value={kes(data.profit_vs_cash.received_cents)} />
            <Stat
              label="Cash after costs"
              value={kes(data.profit_vs_cash.cash_cents)}
              note="Paid to you less costs"
            />
          </div>
          <p className="muted">
            The gap between the two is money clients still owe you (
            {kes(data.profit_vs_cash.owed_cents)} in all). Salaries, lease payments and overheads
            are not counted yet; they join in with the full cost and profit view.
          </p>
        </Card>
      )}
      {data.profit_last_month && (
        <Card
          title={`Last month, after every deduction (${new Date(data.profit_last_month.month).toLocaleDateString("en-KE", { month: "long", year: "numeric", timeZone: "UTC" })})`}
        >
          <ul className="list">
            {data.profit_last_month.vehicles.map((v) => (
              <li key={v.vehicle_id}>
                <span>
                  {v.registration}{" "}
                  <span className="muted">
                    earned {kes(v.gross_profit_cents)}
                    {v.lease_payable_cents > 0 && `, ${kes(v.lease_payable_cents)} to its owner`}
                  </span>
                </span>
                <strong>{kes(v.net_profit_cents)}</strong>
              </li>
            ))}
            <li>
              <span>The whole business, after office costs</span>
              <strong>{kes(data.profit_last_month.business.net_after_overheads)}</strong>
            </li>
          </ul>
          <p>
            <Link to="/leases/profit">Open the profit report</Link>
          </p>
        </Card>
      )}
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
