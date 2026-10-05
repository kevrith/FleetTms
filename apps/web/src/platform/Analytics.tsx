import { useState } from "react";
import { api } from "../api";
import { ErrorBanner } from "../ui";
import { BarChart, BLUE, Donut, GREEN, LineChart, monthLabel, RED, SLATE, VIOLET } from "./charts";
import { kes, METHOD, shortKes } from "./format";
import { Chips, DataTable, Page, Panel, Stat, useLoad } from "./kit";

const PLAN_COLORS: Record<string, string> = { starter: SLATE, standard: BLUE, premium: VIOLET };

/** Money and growth over time, longer than the overview shows: revenue by kind, sign-ups against cancellations, plan and payment mix. */
export default function Analytics() {
  const [months, setMonths] = useState("12");
  const { data: a, error } = useLoad(() => api.platformAnalytics(Number(months)), [months]);
  const total = a?.revenue.reduce((sum, r) => sum + r.subscription_cents + r.sms_cents, 0) ?? 0;
  const rows = a
    ? a.revenue.map((r, i) => ({
        month: r.month,
        subscription: r.subscription_cents,
        sms: r.sms_cents,
        invoices: r.invoices,
        signups: a.signups[i]?.count ?? 0,
        cancelled: a.cancellations[i]?.count ?? 0,
      }))
    : [];

  return (
    <Page
      title="Analytics"
      subtitle="Revenue, growth and the mix of what customers buy."
      actions={
        <Chips
          options={[
            { id: "6", label: "6 months" },
            { id: "12", label: "12 months" },
            { id: "24", label: "24 months" },
            { id: "36", label: "36 months" },
          ]}
          value={months}
          onChange={setMonths}
        />
      }
    >
      <ErrorBanner message={error} />
      {a && (
        <>
          <div className="pf-grid cols-4">
            <Stat
              label={`Collected in ${months} months`}
              value={`KES ${shortKes(total)}`}
              hint={kes(total)}
            />
            <Stat
              label="Monthly recurring revenue"
              value={`KES ${shortKes(a.kpis.mrr_cents)}`}
              hint={`${kes(a.kpis.arr_cents)} a year`}
            />
            <Stat
              label="Average per paying customer"
              value={kes(a.kpis.arpa_cents)}
              hint={`${a.kpis.paying} paying`}
            />
            <Stat
              label="Trial to paid"
              value={
                a.kpis.trial_conversion_pct === null ? "n/a" : `${a.kpis.trial_conversion_pct}%`
              }
              hint={`${a.kpis.converted} of ${a.kpis.past_trial} past their trial`}
            />
          </div>

          <Panel title="Money collected">
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
              height={260}
              summary="Money collected each month from subscriptions and text bundles."
            />
          </Panel>

          <div className="pf-grid cols-2">
            <Panel title="Customers joined">
              <LineChart
                data={a.signups.map((s) => ({ label: monthLabel(s.month), value: s.count }))}
                format={(v) => String(Math.round(v))}
                color={VIOLET}
                summary="New businesses signing up each month."
              />
            </Panel>
            <Panel title="Customers who cancelled">
              <LineChart
                data={a.cancellations.map((s) => ({ label: monthLabel(s.month), value: s.count }))}
                format={(v) => String(Math.round(v))}
                color={RED}
                summary="Customers cancelling each month."
              />
            </Panel>
          </div>

          <div className="pf-grid cols-3">
            <Panel title="Vehicles by plan">
              <Donut
                slices={Object.entries(a.vehicles_by_plan).map(([p, n]) => ({
                  label: p,
                  value: n,
                  color: PLAN_COLORS[p],
                }))}
                summary="Vehicles on each plan."
              />
            </Panel>
            <Panel title="How customers pay (last 90 days)">
              <Donut
                slices={Object.entries(a.payment_methods).map(([m, cents]) => ({
                  label: METHOD[m] ?? m,
                  value: cents,
                }))}
                format={shortKes}
                summary="Money collected by payment method in the last 90 days."
              />
            </Panel>
            <Panel title="Customers by state">
              <Donut
                slices={Object.entries(a.states).map(([s, n]) => ({
                  label: s.replace("_", " "),
                  value: n,
                }))}
                summary="Customers by state."
              />
            </Panel>
          </div>

          <Panel title="Month by month" flush>
            <DataTable
              rows={[...rows].reverse()}
              rowKey={(r) => r.month}
              pageSize={12}
              columns={[
                { key: "month", nowrap: true, header: "Month", render: (r) => r.month },
                {
                  key: "sub",
                  header: "Subscriptions",
                  num: true,
                  render: (r) => kes(r.subscription),
                },
                { key: "sms", header: "Text bundles", num: true, render: (r) => kes(r.sms) },
                { key: "inv", header: "Invoices paid", num: true, render: (r) => r.invoices },
                { key: "new", header: "Joined", num: true, render: (r) => r.signups },
                { key: "gone", header: "Cancelled", num: true, render: (r) => r.cancelled },
              ]}
            />
          </Panel>
        </>
      )}
    </Page>
  );
}
