import type { PlatformRenewalRow } from "@fleettms/types";
import { Bell, CalendarPlus } from "lucide-react";
import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { ErrorBanner } from "../ui";
import { AdvanceDialog } from "./Dialogs";
import { date, daysText, kes } from "./format";
import { Badge, Chips, DataTable, Page, Panel, Stat, useLoad, useToast } from "./kit";

const CATEGORY = {
  overdue: ["Overdue", "bad"],
  trial: ["On trial", "info"],
  renewing: ["Renewing", "ok"],
  suspended: ["On hold", "bad"],
} as const;

/** Every paying or trialing customer by the date its paid time or trial ends: who to chase, who to nudge, what is about to come in. */
export default function Renewals() {
  const [params, setParams] = useSearchParams();
  const category = params.get("category") ?? "all";
  const [window, setWindow] = useState("30");
  const { data, error, reload } = useLoad(
    () => api.platformRenewals(Number(window), category),
    [window, category],
  );
  const [advancing, setAdvancing] = useState<PlatformRenewalRow | null>(null);
  const nav = useNavigate();
  const toast = useToast();

  async function remind(r: PlatformRenewalRow) {
    try {
      const res = await api.platformRemind(r.id);
      toast.ok(
        `Reminder texted to ${res.sent} ${res.sent === 1 ? "person" : "people"} at ${r.name}.`,
      );
    } catch (e) {
      toast.err(e instanceof Error ? e.message : "The reminder was not sent.");
    }
  }

  return (
    <Page
      title="Renewals"
      subtitle="Who is about to run out, who already has, and what is due to come in."
    >
      <ErrorBanner message={error} />
      {data && (
        <div className="pf-grid cols-4">
          <Stat
            label="Overdue"
            tone={data.totals.overdue ? "bad" : undefined}
            value={data.totals.overdue}
            hint={`${kes(data.totals.at_risk_cents)} a month at risk`}
          />
          <Stat label="Trials ending" value={data.totals.trial} hint={`within ${window} days`} />
          <Stat label="Renewing" value={data.totals.renewing} hint={`within ${window} days`} />
          <Stat
            label="Expected"
            tone="ok"
            value={kes(data.totals.expected_cents)}
            hint="a month, from those renewing"
          />
        </div>
      )}
      <Panel flush>
        <div className="pf-tablebar">
          <Chips
            value={category}
            onChange={(c) => setParams(c === "all" ? {} : { category: c })}
            options={[
              { id: "all", label: "Everyone" },
              { id: "overdue", label: "Overdue" },
              { id: "trial", label: "Trials" },
              { id: "renewing", label: "Renewing" },
            ]}
          />
          <label style={{ marginLeft: "auto" }}>
            Look ahead{" "}
            <select value={window} onChange={(e) => setWindow(e.target.value)}>
              {[7, 14, 30, 60, 90, 180].map((d) => (
                <option key={d} value={d}>
                  {d} days
                </option>
              ))}
            </select>
          </label>
        </div>
        <DataTable<PlatformRenewalRow>
          rows={data?.rows ?? []}
          rowKey={(r) => r.id}
          onRowClick={(r) => nav(`/platform/customers/${r.id}`)}
          searchText={(r) => r.name}
          searchPlaceholder="Search customers"
          empty="Nobody is due in that time."
          columns={[
            {
              key: "name",
              header: "Customer",
              sort: (r) => r.name.toLowerCase(),
              render: (r) => (
                <>
                  <strong>{r.name}</strong>
                  {r.cancelled && (
                    <>
                      {" "}
                      <Badge tone="bad">cancelled</Badge>
                    </>
                  )}
                </>
              ),
            },
            {
              key: "cat",
              header: "Status",
              sort: (r) => r.category,
              render: (r) => (
                <Badge tone={CATEGORY[r.category][1]}>{CATEGORY[r.category][0]}</Badge>
              ),
            },
            {
              key: "ends",
              header: "Ends",
              sort: (r) => r.days_left,
              render: (r) => (
                <>
                  {date(r.ends_at)}
                  <div
                    className={r.days_left < 0 ? "" : "pf-muted"}
                    style={r.days_left < 0 ? { color: "var(--pf-bad)" } : undefined}
                  >
                    {daysText(r.days_left)}
                  </div>
                </>
              ),
            },
            {
              key: "veh",
              header: "Vehicles",
              num: true,
              sort: (r) => r.vehicles,
              render: (r) => r.vehicles,
            },
            {
              key: "mrr",
              header: "Monthly",
              num: true,
              sort: (r) => r.monthly_cents,
              render: (r) => kes(r.monthly_cents),
            },
            {
              key: "inv",
              header: "Open invoice",
              render: (r) =>
                r.open_invoice ? (
                  <>
                    {r.open_invoice.number}
                    <div className="pf-muted">{kes(r.open_invoice.total_cents)}</div>
                  </>
                ) : (
                  <span className="pf-muted">none</span>
                ),
            },
            {
              key: "who",
              header: "Contact",
              render: (r) =>
                r.owner ? (
                  <>
                    {r.owner.name}
                    <div className="pf-muted">{r.owner.phone ?? r.owner.email}</div>
                  </>
                ) : (
                  ""
                ),
            },
            {
              key: "act",
              header: "",
              render: (r) => (
                <span style={{ display: "flex", gap: 6 }} onClick={(e) => e.stopPropagation()}>
                  <button
                    className="pf-btn small"
                    onClick={() => void remind(r)}
                    aria-label={`Remind ${r.name}`}
                  >
                    <Bell size={13} /> Remind
                  </button>
                  <button
                    className="pf-btn small"
                    onClick={() => setAdvancing(r)}
                    aria-label={`Advance ${r.name}`}
                  >
                    <CalendarPlus size={13} /> Advance
                  </button>
                </span>
              ),
            },
          ]}
        />
      </Panel>
      {advancing && (
        <AdvanceDialog
          businessId={advancing.id}
          onClose={() => setAdvancing(null)}
          onDone={async () => {
            await reload();
            toast.ok(`${advancing.name}'s renewal was moved.`);
          }}
        />
      )}
    </Page>
  );
}
