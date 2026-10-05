import type { PlatformInvoiceRow } from "@fleettms/types";
import { Download } from "lucide-react";
import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { ErrorBanner } from "../ui";
import { MarkPaidDialog, VoidDialog } from "./Dialogs";
import { saveBlob } from "./download";
import { date, INVOICE_STATUS, kes, METHOD } from "./format";
import { Badge, Chips, Empty, Page, Pager, Panel, Stat, useLoad, useToast } from "./kit";

const FILTERS = ["status", "kind", "q", "start", "end"] as const;

/** Every invoice FleetTms has raised, across customers: filter, page, export, mark paid, void. */
export default function Invoices() {
  const [params, setParams] = useSearchParams();
  const filter = Object.fromEntries(FILTERS.map((f) => [f, params.get(f) ?? ""])) as Record<
    (typeof FILTERS)[number],
    string
  >;
  const page = Number(params.get("page") ?? 1);
  const { data, error, reload } = useLoad(
    () => api.platformInvoices({ ...filter, page, page_size: 50 }),
    [params.toString()],
  );
  const [pay, setPay] = useState<PlatformInvoiceRow | null>(null);
  const [voiding, setVoiding] = useState<PlatformInvoiceRow | null>(null);
  const [search, setSearch] = useState(filter.q);
  const nav = useNavigate();
  const toast = useToast();

  const set = (changes: Record<string, string>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries({ page: "1", ...changes })) {
      if (v) next.set(k, v);
      else next.delete(k);
    }
    setParams(next);
  };

  async function exportCsv() {
    try {
      const q = new URLSearchParams(Object.entries(filter).filter(([, v]) => v));
      saveBlob(
        await api.platformDownload(`/platform/invoices.csv${q.size ? `?${q}` : ""}`),
        "fleettms-invoices.csv",
      );
    } catch (e) {
      toast.err(e instanceof Error ? e.message : "The export did not work.");
    }
  }

  const sum = (s: string) => data?.sums[s]?.cents ?? 0;
  return (
    <Page
      title="Invoices"
      subtitle="Subscriptions and text bundles raised to customers."
      actions={
        <button className="pf-btn" onClick={exportCsv}>
          <Download size={15} /> Export CSV
        </button>
      }
    >
      <ErrorBanner message={error} />
      {data && (
        <div className="pf-grid cols-4">
          <Stat
            label="Paid"
            tone="ok"
            value={kes(sum("paid"))}
            hint={`${data.sums.paid?.count ?? 0} invoices`}
          />
          <Stat
            label="Waiting for payment"
            tone={sum("issued") ? "warn" : undefined}
            value={kes(sum("issued"))}
            hint={`${data.sums.issued?.count ?? 0} invoices`}
          />
          <Stat
            label="Void"
            value={kes(sum("void"))}
            hint={`${data.sums.void?.count ?? 0} invoices`}
          />
          <Stat label="Matching the filter" value={data.total} hint="invoices" />
        </div>
      )}
      <Panel flush>
        <div className="pf-tablebar">
          <Chips
            value={filter.status || "all"}
            onChange={(s) => set({ status: s === "all" ? "" : s })}
            options={[
              { id: "all", label: "All" },
              { id: "issued", label: "Waiting" },
              { id: "overdue", label: "Overdue" },
              { id: "paid", label: "Paid" },
              { id: "void", label: "Void" },
            ]}
          />
          <select
            aria-label="Kind"
            value={filter.kind}
            onChange={(e) => set({ kind: e.target.value })}
          >
            <option value="">All kinds</option>
            <option value="subscription">Subscriptions</option>
            <option value="sms_bundle">Text bundles</option>
          </select>
          <label>
            From{" "}
            <input
              type="date"
              value={filter.start}
              onChange={(e) => set({ start: e.target.value })}
            />
          </label>
          <label>
            To{" "}
            <input type="date" value={filter.end} onChange={(e) => set({ end: e.target.value })} />
          </label>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              set({ q: search.trim() });
            }}
            style={{ marginLeft: "auto" }}
          >
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Invoice, customer or payment code"
              aria-label="Search invoices"
            />
          </form>
        </div>
        {data && data.rows.length === 0 ? (
          <Empty>No invoices match.</Empty>
        ) : (
          <div className="pf-scroll">
            <table>
              <thead>
                <tr>
                  <th>Invoice</th>
                  <th>Customer</th>
                  <th>Status</th>
                  <th className="num">Total</th>
                  <th>Issued</th>
                  <th>Due</th>
                  <th>Paid</th>
                  <th>KRA</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data?.rows.map((i) => (
                  <tr
                    key={i.id}
                    className="click"
                    onClick={() => nav(`/platform/customers/${i.business_id}`)}
                  >
                    <td className="nw">
                      <strong>{i.number}</strong>
                      <div className="pf-muted">
                        {i.kind === "sms_bundle" ? `${i.sms_messages} texts` : i.billing_period}
                      </div>
                    </td>
                    <td>{i.business}</td>
                    <td>
                      <Badge tone={INVOICE_STATUS[i.status]?.tone}>
                        {INVOICE_STATUS[i.status]?.label}
                      </Badge>
                      {i.overdue && (
                        <>
                          {" "}
                          <Badge tone="bad">overdue</Badge>
                        </>
                      )}
                    </td>
                    <td className="num">{kes(i.total_cents)}</td>
                    <td className="nw">{date(i.created_at)}</td>
                    <td className="nw">{date(i.due_date)}</td>
                    <td>
                      {i.paid_at ? (
                        <>
                          {date(i.paid_at)}
                          <div className="pf-muted">
                            {METHOD[i.payment_method ?? "other"] ?? i.payment_method} {i.reference}
                          </div>
                        </>
                      ) : (
                        ""
                      )}
                    </td>
                    <td>
                      {i.status === "paid" ? (
                        <Badge
                          tone={
                            i.tax_invoice === "submitted"
                              ? "ok"
                              : i.tax_invoice === "needs_review"
                                ? "bad"
                                : "warn"
                          }
                        >
                          {i.tax_invoice === "submitted"
                            ? "filed"
                            : (i.tax_invoice ?? "not queued")}
                        </Badge>
                      ) : (
                        ""
                      )}
                    </td>
                    <td onClick={(e) => e.stopPropagation()}>
                      {i.status === "issued" && (
                        <span style={{ display: "flex", gap: 6 }}>
                          <button className="pf-btn small primary" onClick={() => setPay(i)}>
                            Mark paid
                          </button>
                          <button className="pf-btn small danger" onClick={() => setVoiding(i)}>
                            Void
                          </button>
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && data.total > data.page_size && (
          <Pager
            page={data.page}
            pages={data.pages}
            total={data.total}
            pageSize={data.page_size}
            onPage={(p) => set({ page: String(p) })}
          />
        )}
      </Panel>
      {pay && (
        <MarkPaidDialog
          invoiceId={pay.id}
          number={pay.number}
          onClose={() => setPay(null)}
          onDone={async () => {
            await reload();
            toast.ok("Marked as paid.");
          }}
        />
      )}
      {voiding && (
        <VoidDialog
          invoiceId={voiding.id}
          number={voiding.number}
          onClose={() => setVoiding(null)}
          onDone={async () => {
            await reload();
            toast.ok("The invoice was voided.");
          }}
        />
      )}
    </Page>
  );
}
