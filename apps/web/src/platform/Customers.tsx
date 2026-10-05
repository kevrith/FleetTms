import type { PlatformBusinessRow } from "@fleettms/types";
import { Download } from "lucide-react";
import { useMemo } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { ErrorBanner } from "../ui";
import { date, daysText, kes, STATE } from "./format";
import { Badge, Chips, DataTable, Page, Panel, useLoad, useToast } from "./kit";
import { saveBlob } from "./download";

const ORDER = ["trialing", "active", "grace", "read_only", "suspended", "complimentary"];

export default function Customers() {
  const { data, error } = useLoad(() => api.platformBusinesses());
  const [params, setParams] = useSearchParams();
  const nav = useNavigate();
  const toast = useToast();
  const state = params.get("state") ?? "all";
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const r of data ?? []) c[r.state] = (c[r.state] ?? 0) + 1;
    return c;
  }, [data]);
  const rows = (data ?? []).filter((r) => state === "all" || r.state === state);

  async function exportCsv() {
    try {
      saveBlob(await api.platformDownload("/platform/customers.csv"), "fleettms-customers.csv");
    } catch (e) {
      toast.err(e instanceof Error ? e.message : "The export did not work.");
    }
  }

  return (
    <Page
      title="Customers"
      subtitle={
        data ? `${data.length} businesses on the platform.` : "Every business on the platform."
      }
      actions={
        <button className="pf-btn" onClick={exportCsv}>
          <Download size={15} /> Export CSV
        </button>
      }
    >
      <ErrorBanner message={error} />
      <Panel flush>
        <div className="pf-tablebar">
          <Chips
            value={state}
            onChange={(s) => setParams(s === "all" ? {} : { state: s })}
            options={[
              { id: "all", label: "All", count: data?.length ?? 0 },
              ...ORDER.filter((s) => counts[s]).map((s) => ({
                id: s,
                label: STATE[s]?.label ?? s,
                count: counts[s],
              })),
            ]}
          />
        </div>
        <DataTable<PlatformBusinessRow>
          rows={rows}
          rowKey={(r) => r.id}
          onRowClick={(r) => nav(`/platform/customers/${r.id}`)}
          searchText={(r) => r.name}
          searchPlaceholder="Search customers"
          initialSort={{ key: "joined", desc: true }}
          empty="No customers match."
          columns={[
            {
              key: "name",
              header: "Customer",
              sort: (r) => r.name.toLowerCase(),
              render: (r) => <strong>{r.name}</strong>,
            },
            {
              key: "state",
              header: "State",
              sort: (r) => ORDER.indexOf(r.state),
              render: (r) => (
                <Badge tone={STATE[r.state]?.tone}>{STATE[r.state]?.label ?? r.state}</Badge>
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
              key: "people",
              header: "People",
              num: true,
              sort: (r) => r.people,
              render: (r) => r.people,
            },
            {
              key: "plans",
              header: "Plans",
              render: (r) => (
                <span className="pf-muted">
                  {Object.entries(r.plans)
                    .map(([p, n]) => `${n} ${p}`)
                    .join(", ") || "none"}
                </span>
              ),
            },
            { key: "per", header: "Billed", sort: (r) => r.period, render: (r) => r.period },
            {
              key: "mrr",
              header: "Monthly",
              num: true,
              sort: (r) => r.monthly_cents,
              render: (r) => kes(r.monthly_cents),
            },
            {
              key: "ends",
              header: "Renews or ends",
              sort: (r) => r.paid_until ?? r.trial_ends_at,
              render: (r) => {
                const when = r.paid_until ?? r.trial_ends_at;
                return when ? (
                  <>
                    {date(when)}
                    {r.days_left !== null && (
                      <div className="pf-muted">{daysText(r.days_left)}</div>
                    )}
                  </>
                ) : (
                  "n/a"
                );
              },
            },
            {
              key: "joined",
              header: "Joined",
              sort: (r) => r.created_at,
              render: (r) => date(r.created_at),
            },
          ]}
        />
      </Panel>
    </Page>
  );
}
