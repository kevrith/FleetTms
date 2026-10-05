import type { PlatformEtimsInvoice } from "@fleettms/types";
import { Plug, RefreshCw } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { ErrorBanner } from "../ui";
import { dateTime, kes } from "./format";
import {
  Badge,
  DataTable,
  FormDialog,
  FormField,
  Page,
  Panel,
  Stat,
  useLoad,
  useToast,
} from "./kit";

const TONE = { pending: "warn", submitted: "ok", needs_review: "bad", resolved: "info" } as const;

/** FleetTms's own tax invoices to KRA: whether the device is set up, what is stuck, and the buttons to fix it. */
export default function KraInvoices() {
  const { data: e, error, reload } = useLoad(() => api.platformEtims());
  const [resolving, setResolving] = useState<PlatformEtimsInvoice | null>(null);
  const [note, setNote] = useState("");
  const [receipt, setReceipt] = useState("");
  const toast = useToast();

  async function act(work: () => Promise<string | void>) {
    try {
      const done = await work();
      if (done) toast.ok(done);
      await reload();
    } catch (err) {
      toast.err(err instanceof Error ? err.message : "That did not work.");
    }
  }

  return (
    <Page
      title="KRA invoices"
      subtitle="Every paid subscription and text bundle is sent to KRA as a tax invoice from the platform's own device."
      actions={
        <>
          <button
            className="pf-btn"
            disabled={!e?.enabled}
            onClick={() =>
              void act(async () => {
                await api.platformEtimsConnect();
                return "The device is registered with KRA.";
              })
            }
          >
            <Plug size={15} /> Connect the device
          </button>
          <button
            className="pf-btn"
            disabled={!e?.enabled}
            onClick={() =>
              void act(async () => {
                const r = await api.platformEtimsBackfill();
                return `${r.queued} paid invoice(s) queued.`;
              })
            }
          >
            <RefreshCw size={15} /> Queue invoices paid before this was set up
          </button>
        </>
      }
    >
      <ErrorBanner message={error} />
      {e && (
        <>
          {!e.enabled && (
            <Panel>
              <p style={{ margin: 0 }}>
                Not set up. Set <code>PLATFORM_KRA_PIN</code> and{" "}
                <code>PLATFORM_ETIMS_DEVICE_SERIAL</code> where the API runs, then connect the
                device here. Until then paid invoices are not sent to KRA.
              </p>
            </Panel>
          )}
          <div className="pf-grid cols-4">
            <Stat label="Sent to KRA" tone="ok" value={e.submitted} />
            <Stat label="Waiting" value={e.pending} />
            <Stat
              label="Need a person"
              tone={e.needs_review ? "bad" : undefined}
              value={e.needs_review}
            />
            <Stat
              label="Handled by hand"
              value={e.resolved}
              hint={e.vat_pct > 0 ? `${e.vat_pct}% VAT taken out of the price` : "no VAT"}
            />
          </div>
          <Panel title="Invoices" flush>
            <DataTable<PlatformEtimsInvoice>
              rows={e.invoices}
              rowKey={(i) => i.id}
              searchText={(i) => `${i.invoice_number} ${i.business}`}
              searchPlaceholder="Search invoices"
              empty="None yet."
              columns={[
                {
                  key: "n",
                  nowrap: true,
                  header: "Invoice",
                  render: (i) => <strong>{i.invoice_number}</strong>,
                },
                {
                  key: "b",
                  header: "Customer",
                  render: (i) => (
                    <>
                      {i.business}
                      {!i.business_has_pin && <div className="pf-muted">no buyer PIN</div>}
                    </>
                  ),
                },
                { key: "t", header: "Total", num: true, render: (i) => kes(i.total_cents) },
                {
                  key: "s",
                  header: "Status",
                  render: (i) => (
                    <Badge tone={TONE[i.status]}>
                      {i.status_text}
                      {i.receipt_no ? ` ${i.receipt_no}` : ""}
                    </Badge>
                  ),
                },
                {
                  key: "w",
                  header: "Last problem",
                  render: (i) => (
                    <span className="pf-muted">
                      {i.status !== "submitted"
                        ? i.last_error
                        : i.submitted_at
                          ? dateTime(i.submitted_at)
                          : ""}
                    </span>
                  ),
                },
                {
                  key: "a",
                  header: "",
                  render: (i) =>
                    i.status === "pending" || i.status === "needs_review" ? (
                      <span style={{ display: "flex", gap: 6 }}>
                        <button
                          className="pf-btn small"
                          onClick={() =>
                            void act(async () => {
                              await api.platformEtimsRetry(i.id);
                            })
                          }
                        >
                          Try again
                        </button>
                        <button
                          className="pf-btn small"
                          onClick={() => {
                            setResolving(i);
                            setNote("");
                            setReceipt("");
                          }}
                        >
                          Handled by hand
                        </button>
                      </span>
                    ) : null,
                },
              ]}
            />
          </Panel>
        </>
      )}
      {resolving && (
        <FormDialog
          title={`Handled by hand: ${resolving.invoice_number}`}
          description="For an invoice dealt with outside FleetTms, for example entered on the KRA portal."
          submitLabel="Mark handled"
          onClose={() => setResolving(null)}
          onSubmit={async () => {
            await api.platformEtimsResolve(resolving.id, note.trim(), receipt.trim());
            await reload();
            toast.ok("Marked as handled.");
          }}
        >
          <FormField label="How it was dealt with">
            <input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              minLength={3}
              maxLength={255}
              required
            />
          </FormField>
          <FormField label="KRA receipt number (optional)">
            <input value={receipt} onChange={(e) => setReceipt(e.target.value)} maxLength={40} />
          </FormField>
        </FormDialog>
      )}
    </Page>
  );
}
