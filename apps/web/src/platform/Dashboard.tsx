import {
  AlertTriangle,
  Banknote,
  CalendarClock,
  Percent,
  TrendingDown,
  TrendingUp,
  Truck,
  Users,
  Wallet,
} from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { ErrorBanner } from "../ui";
import { BarChart, BLUE, Donut, GREEN, monthLabel, VIOLET } from "./charts";
import { kes, shortKes, STATE } from "./format";
import { Badge, DataTable, Empty, Page, Panel, Stat, useLoad } from "./kit";

/** The first page: what needs a person, the money, growth, and where customers stand. */
export default function Dashboard() {
  const analytics = useLoad(() => api.platformAnalytics(12));
  const attention = useLoad(() => api.platformAttention());
  const nav = useNavigate();
  const a = analytics.data;
  const k = a?.kpis;

  return (
    <Page
      title="Overview"
      subtitle="How FleetTms is doing as a business: money, growth, and what needs you today."
      actions={
        <>
          <Link className="pf-btn" to="/platform/renewals">
            <CalendarClock size={15} /> Renewals
          </Link>
          <Link className="pf-btn primary" to="/platform/analytics">
            <TrendingUp size={15} /> Full analytics
          </Link>
        </>
      }
    >
      <ErrorBanner message={analytics.error ?? attention.error} />

      <Panel title="Needs attention" flush={false}>
        {!attention.data ? (
          <p className="pf-muted">Loading...</p>
        ) : attention.data.length === 0 ? (
          <p className="pf-muted">Nothing needs you right now.</p>
        ) : (
          <div className="pf-attention">
            {attention.data.map((i) => (
              <Link key={i.key} to={i.link} className={`pf-attn ${i.severity}`}>
                {i.severity === "red" && <AlertTriangle size={18} />}
                <b>{i.count}</b>
                <span>{i.label}</span>
              </Link>
            ))}
          </div>
        )}
      </Panel>

      {k && a && (
        <>
          <div className="pf-grid cols-6">
            <Stat
              label="Monthly recurring revenue"
              icon={<Banknote size={14} />}
              value={`KES ${shortKes(k.mrr_cents)}`}
              hint={`${kes(k.arr_cents)} a year`}
            />
            <Stat
              label="Paying customers"
              icon={<Users size={14} />}
              value={k.paying}
              hint={`${kes(k.arpa_cents)} each on average`}
            />
            <Stat
              label="Vehicles on the platform"
              icon={<Truck size={14} />}
              value={k.vehicles}
              hint={`${k.businesses} businesses`}
            />
            <Stat
              label="Collected, last 30 days"
              icon={<Wallet size={14} />}
              tone="ok"
              value={`KES ${shortKes(k.collected_30d_cents)}`}
            />
            <Stat
              label="Owed to us"
              icon={<Banknote size={14} />}
              tone={k.overdue_cents > 0 ? "bad" : undefined}
              value={`KES ${shortKes(k.outstanding_cents)}`}
              hint={
                k.overdue_cents > 0
                  ? `${kes(k.overdue_cents)} is past its due date`
                  : "none overdue"
              }
            />
            <Stat
              label="Trial to paid"
              icon={<Percent size={14} />}
              value={k.trial_conversion_pct === null ? "n/a" : `${k.trial_conversion_pct}%`}
              hint={
                k.past_trial
                  ? `${k.converted} of ${k.past_trial} past their trial`
                  : "no trial has ended yet"
              }
            />
          </div>
          <div className="pf-grid cols-4">
            <Stat
              label="New customers, 30 days"
              icon={<TrendingUp size={14} />}
              tone="ok"
              value={k.new_30d}
            />
            <Stat
              label="Cancelled, 30 days"
              icon={<TrendingDown size={14} />}
              tone={k.churned_30d > 0 ? "warn" : undefined}
              value={k.churned_30d}
            />
            <Stat label="On trial" value={a.states.trialing ?? 0} />
            <Stat
              label="Overdue or read-only"
              tone={(a.states.grace ?? 0) + (a.states.read_only ?? 0) > 0 ? "warn" : undefined}
              value={(a.states.grace ?? 0) + (a.states.read_only ?? 0)}
            />
          </div>

          <div className="pf-grid wide-left">
            <Panel title="Money collected each month">
              <BarChart
                data={a.revenue.map((r) => ({
                  label: monthLabel(r.month),
                  values: { subscription: r.subscription_cents, sms: r.sms_cents },
                }))}
                series={[
                  { key: "subscription", label: "Subscriptions", color: BLUE },
                  { key: "sms", label: "Text bundles", color: GREEN },
                ]}
                format={shortKes}
                summary={`Money collected in each of the last ${a.revenue.length} months, subscriptions and text bundles.`}
              />
            </Panel>
            <Panel title="Customers by state">
              <Donut
                slices={Object.entries(a.states).map(([s, n]) => ({
                  label: STATE[s]?.label ?? s,
                  value: n,
                }))}
                summary="Customers by state."
              />
            </Panel>
          </div>

          <div className="pf-grid cols-2">
            <Panel title="Sign-ups each month">
              <BarChart
                data={a.signups.map((s) => ({
                  label: monthLabel(s.month),
                  values: { signups: s.count },
                }))}
                series={[{ key: "signups", label: "Sign-ups", color: VIOLET }]}
                format={(v) => String(Math.round(v))}
                height={180}
                summary="New businesses signing up each month."
              />
            </Panel>
            <Panel title="Biggest customers" flush>
              <DataTable
                rows={a.top_customers}
                rowKey={(r) => r.id}
                onRowClick={(r) => nav(`/platform/customers/${r.id}`)}
                empty={<Empty>No paying customers yet.</Empty>}
                columns={[
                  { key: "name", header: "Customer", render: (r) => <strong>{r.name}</strong> },
                  { key: "veh", header: "Vehicles", num: true, render: (r) => r.vehicles },
                  { key: "per", header: "Billed", render: (r) => <Badge>{r.period}</Badge> },
                  { key: "mrr", header: "Monthly", num: true, render: (r) => kes(r.monthly_cents) },
                ]}
              />
            </Panel>
          </div>
        </>
      )}
    </Page>
  );
}
