import type {
  PlanName,
  PlatformBusinessDetail,
  PlatformInvoiceRow,
  PlatformNote,
  PlatformSubscriptionDetail,
} from "@fleettms/types";
import {
  Bell,
  CalendarPlus,
  ExternalLink,
  FilePlus2,
  Pencil,
  Pin,
  PinOff,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorBanner } from "../ui";
import { AdvanceDialog, EditSubscriptionDialog, MarkPaidDialog, VoidDialog } from "./Dialogs";
import { actionText, date, dateTime, daysText, INVOICE_STATUS, kes, METHOD, STATE } from "./format";
import {
  Badge,
  DataTable,
  Empty,
  FormDialog,
  FormField,
  Page,
  Panel,
  ReasonField,
  Stat,
  Tabs,
  useLoad,
  useToast,
} from "./kit";

type TabId = "overview" | "subscription" | "invoices" | "notes" | "activity" | "account";
type Dialog =
  | null
  | "advance"
  | "edit"
  | "cancel"
  | "reactivate"
  | "invoice"
  | "details"
  | "complimentary"
  | "suspend"
  | "trial"
  | { kind: "pay"; invoice: PlatformInvoiceRow }
  | { kind: "void"; invoice: PlatformInvoiceRow }
  | { kind: "plan"; vehicleId: string; registration: string; plan: PlanName };

export default function CustomerDetail() {
  const { id = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as TabId | null) ?? "overview";
  const setTab = (t: TabId) => setParams(t === "overview" ? {} : { tab: t }, { replace: true });
  const [dialog, setDialog] = useState<Dialog>(null);
  const detail = useLoad(() => api.platformSubscription(id), [id]);
  const profile = useLoad(() => api.platformBusiness(id), [id]);
  const toast = useToast();
  const d = detail.data;
  const p = profile.data;

  async function refresh() {
    await Promise.all([detail.reload(), profile.reload()]);
  }
  const close = () => setDialog(null);
  const after = (message: string) => async () => {
    await refresh();
    toast.ok(message);
  };

  async function remind() {
    try {
      const r = await api.platformRemind(id);
      toast.ok(`Reminder texted to ${r.sent} ${r.sent === 1 ? "person" : "people"}.`);
      await refresh();
    } catch (e) {
      toast.err(e instanceof Error ? e.message : "The reminder was not sent.");
    }
  }

  if (!d || !p) return <ErrorBanner message={detail.error ?? profile.error} />;
  const state = STATE[d.access.state];
  const open = d.invoices.find((i) => i.status === "issued" && i.kind === "subscription");

  return (
    <Page
      crumbs={[{ to: "/platform/customers", label: "Customers" }, { label: p.name }]}
      title={
        <>
          {p.name} <Badge tone={state?.tone}>{state?.label ?? d.access.state}</Badge>
          {d.subscription.cancelled_at && (
            <>
              {" "}
              <Badge tone="bad">Cancelled</Badge>
            </>
          )}
        </>
      }
      subtitle={`Customer since ${date(p.created_at)}. ${p.vehicles} ${p.vehicles === 1 ? "vehicle" : "vehicles"}, ${p.people} ${p.people === 1 ? "person" : "people"}.`}
      actions={
        <>
          <button className="pf-btn" onClick={remind}>
            <Bell size={15} /> Remind now
          </button>
          <button className="pf-btn" onClick={() => setDialog("advance")}>
            <CalendarPlus size={15} /> Advance renewal
          </button>
          <button className="pf-btn primary" onClick={() => setDialog("invoice")}>
            <FilePlus2 size={15} /> Raise invoice
          </button>
        </>
      }
    >
      <Tabs
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "overview", label: "Overview" },
          { id: "subscription", label: "Subscription" },
          { id: "invoices", label: "Invoices", count: d.invoices.length },
          { id: "notes", label: "Notes" },
          { id: "activity", label: "Activity" },
          { id: "account", label: "Account" },
        ]}
      />

      {tab === "overview" && (
        <Overview
          d={d}
          p={p}
          open={open}
          onEdit={() => setDialog("edit")}
          onPay={(i) => setDialog({ kind: "pay", invoice: i })}
        />
      )}
      {tab === "subscription" && <SubscriptionTab d={d} onDialog={setDialog} />}
      {tab === "invoices" && (
        <InvoicesTab
          invoices={d.invoices}
          onPay={(i) => setDialog({ kind: "pay", invoice: i })}
          onVoid={(i) => setDialog({ kind: "void", invoice: i })}
          payments={d.payments}
        />
      )}
      {tab === "notes" && <Notes id={id} />}
      {tab === "activity" && <Activity id={id} />}
      {tab === "account" && <Account d={d} p={p} id={id} onDialog={setDialog} />}

      {dialog === "advance" && (
        <AdvanceDialog
          businessId={id}
          onClose={close}
          onDone={after("The renewal date was moved.")}
        />
      )}
      {dialog === "edit" && (
        <EditSubscriptionDialog
          detail={d}
          onClose={close}
          onDone={after("The subscription was updated.")}
        />
      )}
      {dialog === "cancel" && (
        <ReasonAction
          title="Cancel the subscription"
          description="The account turns read-only at once and everything can still be exported. After the grace period personal data is removed."
          submit="Cancel the subscription"
          danger
          run={(reason) => api.platformCancel(id, reason)}
          onClose={close}
          onDone={after("The subscription was cancelled.")}
        />
      )}
      {dialog === "reactivate" && (
        <ReasonAction
          title="Reactivate the subscription"
          description="Takes the cancellation back while the data is still there."
          submit="Reactivate"
          run={(reason) => api.platformReactivate(id, reason)}
          onClose={close}
          onDone={after("The subscription was reactivated.")}
        />
      )}
      {dialog === "complimentary" && (
        <ReasonAction
          title={d.complimentary ? "End the free account" : "Make this a free account"}
          description={
            d.complimentary
              ? "The customer goes back to the trial and billing rules."
              : "Every feature, never billed (a pilot, a partner, a gift)."
          }
          submit={d.complimentary ? "End free account" : "Make it free"}
          run={(reason) =>
            api.platformAct(id, "complimentary", { value: !d.complimentary, reason })
          }
          onClose={close}
          onDone={after("Saved.")}
        />
      )}
      {dialog === "suspend" && (
        <ReasonAction
          title={d.suspended ? "Lift the hold" : "Put the account on hold"}
          description={
            d.suspended
              ? "The account works again if it is paid up."
              : "Read-only, with nothing deleted. For abuse or a dispute, not for non-payment (that is automatic)."
          }
          submit={d.suspended ? "Lift the hold" : "Put on hold"}
          danger={!d.suspended}
          noReason={d.suspended}
          run={(reason) =>
            d.suspended
              ? api.platformAct(id, "unsuspend")
              : api.platformAct(id, "suspend", { reason })
          }
          onClose={close}
          onDone={after(d.suspended ? "The hold was lifted." : "The account is on hold.")}
        />
      )}
      {dialog === "trial" && (
        <TrialDialog id={id} onClose={close} onDone={after("The trial was extended.")} />
      )}
      {dialog === "invoice" && (
        <RaiseInvoiceDialog id={id} onClose={close} onDone={after("The invoice was raised.")} />
      )}
      {dialog === "details" && (
        <DetailsDialog
          id={id}
          name={p.name}
          pin={p.kra_pin}
          onClose={close}
          onDone={after("The details were saved.")}
        />
      )}
      {typeof dialog === "object" && dialog && dialog.kind === "pay" && (
        <MarkPaidDialog
          invoiceId={dialog.invoice.id}
          number={dialog.invoice.number}
          onClose={close}
          onDone={after("Marked as paid.")}
        />
      )}
      {typeof dialog === "object" && dialog && dialog.kind === "void" && (
        <VoidDialog
          invoiceId={dialog.invoice.id}
          number={dialog.invoice.number}
          onClose={close}
          onDone={after("The invoice was voided.")}
        />
      )}
      {typeof dialog === "object" && dialog && dialog.kind === "plan" && (
        <PlanDialog id={id} v={dialog} onClose={close} onDone={after("The plan was changed.")} />
      )}
    </Page>
  );
}

// ---- tabs ---------------------------------------------------------------------------------------------------------------------

function Overview({
  d,
  p,
  open,
  onEdit,
  onPay,
}: {
  d: PlatformSubscriptionDetail;
  p: PlatformBusinessDetail;
  open?: PlatformInvoiceRow;
  onEdit: () => void;
  onPay: (i: PlatformInvoiceRow) => void;
}) {
  const s = d.subscription;
  const ends = s.paid_until ?? s.trial_ends_at;
  return (
    <>
      <div className="pf-grid cols-4">
        <Stat
          label={s.paid_until ? "Paid until" : "Trial ends"}
          value={date(ends)}
          hint={renewalHint(d, ends)}
          tone={d.access.state === "grace" || d.access.state === "read_only" ? "bad" : undefined}
        />
        <Stat
          label="Monthly price"
          value={kes(d.quote.monthly_cents)}
          hint={
            d.quote.agreed || s.custom_monthly_cents
              ? "agreed price"
              : `${d.quote.vehicles} vehicles on the price list`
          }
        />
        <Stat
          label="Billed"
          value={s.period === "annual" ? "Annually" : "Monthly"}
          hint={
            s.period === "annual"
              ? `${kes(d.annual_quote.total_cents)} a year`
              : `${kes(d.annual_quote.total_cents)} if annual`
          }
        />
        <Stat
          label="Text messages"
          value={d.sms.credits}
          hint={`${d.sms.sent_this_month} sent this month`}
          tone={d.sms.low ? "warn" : undefined}
        />
      </div>
      {open && (
        <Panel
          title="Invoice waiting for payment"
          actions={
            <button className="pf-btn primary small" onClick={() => onPay(open)}>
              Mark as paid
            </button>
          }
        >
          <strong>{open.number}</strong> for {kes(open.total_cents)}, due {date(open.due_date)}{" "}
          {open.overdue && <Badge tone="bad">overdue</Badge>}
        </Panel>
      )}
      <div className="pf-grid cols-2">
        <Panel
          title="The business"
          actions={
            <button className="pf-btn small" onClick={onEdit}>
              Edit subscription
            </button>
          }
        >
          <dl className="pf-kv">
            <dt>Owner</dt>
            <dd>{p.owner ? p.owner.name : "none"}</dd>
            <dt>Email</dt>
            <dd>{p.owner?.email ?? "none"}</dd>
            <dt>Phone</dt>
            <dd>{p.owner?.phone ?? "none"}</dd>
            <dt>KRA PIN</dt>
            <dd>
              {p.kra_pin ?? (
                <span className="pf-muted">not set: tax invoices go without a buyer PIN</span>
              )}
            </dd>
            <dt>Free account</dt>
            <dd>{d.complimentary ? <Badge tone="accent">Yes</Badge> : "No"}</dd>
            <dt>On hold</dt>
            <dd>{d.suspended ? <Badge tone="bad">{d.suspended_reason ?? "Yes"}</Badge> : "No"}</dd>
          </dl>
        </Panel>
        <Panel title="Where the subscription stands">
          <dl className="pf-kv">
            <dt>Access</dt>
            <dd>{d.access.writable ? "Full access" : "Read-only"}</dd>
            <dt>Trial ends</dt>
            <dd>{date(s.trial_ends_at)}</dd>
            <dt>Paid until</dt>
            <dd>{s.paid_until ? date(s.paid_until) : "never paid"}</dd>
            <dt>Payroll add-on</dt>
            <dd>{s.payroll_enabled ? `On (${d.payroll_employees} people)` : "Off"}</dd>
            <dt>Cancelled</dt>
            <dd>
              {s.cancelled_at
                ? `${date(s.cancelled_at)}; data removed on ${date(s.data_removed_on)}`
                : "No"}
            </dd>
          </dl>
        </Panel>
      </div>
    </>
  );
}

/** What the end date means right now: how long to go, or how long ago it passed and what that has led to. */
function renewalHint(d: PlatformSubscriptionDetail, ends: string): string {
  const days = Math.ceil((new Date(ends).getTime() - Date.now()) / 86_400_000);
  if (d.access.state === "grace")
    return `${daysText(days)}; grace ends ${daysText(d.access.days_left ?? 0)}`;
  if (d.access.state === "read_only") return `${daysText(days)}; the account is read-only`;
  if (d.access.state === "complimentary") return "free account";
  return daysText(days);
}

function SubscriptionTab({
  d,
  onDialog,
}: {
  d: PlatformSubscriptionDetail;
  onDialog: (x: Dialog) => void;
}) {
  const q = d.quote;
  return (
    <>
      <Panel
        title="What this customer would be billed now"
        actions={
          <>
            <button className="pf-btn small" onClick={() => onDialog("edit")}>
              <Pencil size={13} /> Edit
            </button>
            <button className="pf-btn small" onClick={() => onDialog("advance")}>
              <CalendarPlus size={13} /> Advance renewal
            </button>
          </>
        }
      >
        <dl className="pf-kv">
          {q.lines.map((l) => (
            <div key={l.plan} style={{ display: "contents" }}>
              <dt>{l.plan}</dt>
              <dd>
                {l.vehicles} vehicles at {kes(l.unit_cents)} = {kes(l.cents)}
              </dd>
            </div>
          ))}
          {q.discount_cents > 0 && (
            <>
              <dt>Volume discount</dt>
              <dd>
                {q.discount_pct}% off: minus {kes(q.discount_cents)}
              </dd>
            </>
          )}
          {q.payroll_cents > 0 && (
            <>
              <dt>Payroll add-on</dt>
              <dd>{kes(q.payroll_cents)}</dd>
            </>
          )}
          <dt>Monthly</dt>
          <dd>
            <strong>{kes(q.monthly_cents)}</strong>
            {q.custom &&
              !q.agreed &&
              " (31 or more vehicles: priced by agreement, set an agreed price)"}
          </dd>
          <dt>Next invoice</dt>
          <dd>
            {kes(q.total_cents)} ({q.period})
          </dd>
        </dl>
      </Panel>
      <Panel title="Vehicles and their plans" flush>
        <DataTable
          rows={d.vehicles}
          rowKey={(v) => v.vehicle_id}
          searchText={(v) => v.registration}
          searchPlaceholder="Find a vehicle"
          empty="No vehicles yet."
          columns={[
            {
              key: "reg",
              header: "Vehicle",
              sort: (v) => v.registration,
              render: (v) => <strong>{v.registration}</strong>,
            },
            {
              key: "plan",
              header: "Billed at",
              sort: (v) => v.plan,
              render: (v) => <Badge tone="accent">{v.plan}</Badge>,
            },
            {
              key: "eff",
              header: "Has now",
              render: (v) =>
                v.effective_plan === v.plan ? (
                  <span className="pf-muted">same</span>
                ) : (
                  <Badge tone="warn">{v.effective_plan} (trial cap)</Badge>
                ),
            },
            {
              key: "act",
              header: "",
              render: (v) => (
                <button
                  className="pf-btn small"
                  onClick={() =>
                    onDialog({
                      kind: "plan",
                      vehicleId: v.vehicle_id,
                      registration: v.registration,
                      plan: v.plan,
                    })
                  }
                >
                  Change plan
                </button>
              ),
            },
          ]}
        />
      </Panel>
    </>
  );
}

function InvoicesTab({
  invoices,
  payments,
  onPay,
  onVoid,
}: {
  invoices: PlatformInvoiceRow[];
  payments: PlatformSubscriptionDetail["payments"];
  onPay: (i: PlatformInvoiceRow) => void;
  onVoid: (i: PlatformInvoiceRow) => void;
}) {
  return (
    <>
      <Panel flush>
        <DataTable
          rows={invoices}
          rowKey={(i) => i.id}
          initialSort={{ key: "issued", desc: true }}
          empty="No invoices yet."
          columns={[
            {
              key: "no",
              header: "Invoice",
              sort: (i) => i.number,
              render: (i) => <strong>{i.number}</strong>,
            },
            {
              key: "kind",
              header: "For",
              render: (i) =>
                i.kind === "sms_bundle"
                  ? `${i.sms_messages} text messages`
                  : i.period_start
                    ? `${date(i.period_start)} to ${date(i.period_end)}`
                    : "Subscription",
            },
            {
              key: "st",
              header: "Status",
              sort: (i) => i.status,
              render: (i) => (
                <>
                  <Badge tone={INVOICE_STATUS[i.status]?.tone}>
                    {INVOICE_STATUS[i.status]?.label}
                  </Badge>
                  {i.overdue && (
                    <>
                      {" "}
                      <Badge tone="bad">overdue</Badge>
                    </>
                  )}
                </>
              ),
            },
            {
              key: "tot",
              header: "Total",
              num: true,
              sort: (i) => i.total_cents,
              render: (i) => kes(i.total_cents),
            },
            {
              key: "issued",
              header: "Issued",
              sort: (i) => i.created_at,
              render: (i) => date(i.created_at),
            },
            {
              key: "due",
              nowrap: true,
              header: "Due",
              sort: (i) => i.due_date,
              render: (i) => date(i.due_date),
            },
            {
              key: "paid",
              header: "Paid",
              render: (i) =>
                i.paid_at ? (
                  <>
                    {date(i.paid_at)}
                    <div className="pf-muted">
                      {METHOD[i.payment_method ?? "other"] ?? i.payment_method} {i.reference}
                    </div>
                  </>
                ) : (
                  ""
                ),
            },
            {
              key: "kra",
              header: "KRA",
              render: (i) =>
                i.status === "paid" ? (
                  <Badge
                    tone={
                      i.tax_invoice === "submitted"
                        ? "ok"
                        : i.tax_invoice === "needs_review"
                          ? "bad"
                          : "warn"
                    }
                  >
                    {i.tax_invoice === "submitted" ? "filed" : (i.tax_invoice ?? "not queued")}
                  </Badge>
                ) : (
                  ""
                ),
            },
            {
              key: "act",
              header: "",
              render: (i) =>
                i.status === "issued" ? (
                  <span style={{ display: "flex", gap: 6 }}>
                    <button className="pf-btn small primary" onClick={() => onPay(i)}>
                      Mark paid
                    </button>
                    <button className="pf-btn small danger" onClick={() => onVoid(i)}>
                      Void
                    </button>
                  </span>
                ) : null,
            },
          ]}
        />
      </Panel>
      <Panel title="Payment attempts" flush>
        <DataTable
          rows={payments}
          rowKey={(p) => p.id}
          empty="No payment attempts."
          columns={[
            { key: "at", nowrap: true, header: "When", render: (p) => dateTime(p.created_at) },
            { key: "m", header: "Method", render: (p) => METHOD[p.method] ?? p.method },
            { key: "amt", header: "Amount", num: true, render: (p) => kes(p.amount_cents) },
            {
              key: "st",
              header: "Result",
              render: (p) => (
                <Badge tone={p.status === "paid" ? "ok" : p.status === "failed" ? "bad" : "warn"}>
                  {p.status}
                </Badge>
              ),
            },
            {
              key: "note",
              header: "Note",
              render: (p) => <span className="pf-muted">{p.note}</span>,
            },
          ]}
        />
      </Panel>
    </>
  );
}

function Notes({ id }: { id: string }) {
  const notes = useLoad(() => api.platformNotes(id), [id]);
  const [text, setText] = useState("");
  const [editing, setEditing] = useState<PlatformNote | null>(null);
  const [draft, setDraft] = useState("");
  const toast = useToast();

  async function run(work: () => Promise<unknown>) {
    try {
      await work();
      await notes.reload();
    } catch (e) {
      toast.err(e instanceof Error ? e.message : "That did not work.");
    }
  }

  return (
    <>
      <Panel
        title="Add a note"
        actions={
          <span className="pf-muted">Only platform admins see notes. The customer never does.</span>
        }
      >
        <form
          className="pf-stack"
          onSubmit={(e) => {
            e.preventDefault();
            if (!text.trim()) return;
            void run(async () => {
              await api.platformAddNote(id, text.trim());
              setText("");
            });
          }}
        >
          <textarea
            aria-label="Note"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="A call, a promise, a risk, something to remember"
            maxLength={2000}
            rows={3}
            style={{
              width: "100%",
              padding: 10,
              borderRadius: 9,
              border: "1px solid var(--pf-border)",
              background: "var(--pf-raised)",
              color: "var(--pf-text)",
              font: "inherit",
            }}
          />
          <div>
            <button className="pf-btn primary" disabled={!text.trim()}>
              Add note
            </button>
          </div>
        </form>
      </Panel>
      <div className="pf-stack">
        {notes.data?.length === 0 && <Empty>No notes yet.</Empty>}
        {notes.data?.map((n) => (
          <div key={n.id} className={`pf-note${n.pinned ? " pinned" : ""}`}>
            <header>
              {n.pinned && <Badge tone="warn">Pinned</Badge>}
              <strong>{n.author ?? "Someone"}</strong> {dateTime(n.created_at)}
              {n.updated_at !== n.created_at && " (edited)"}
              <span style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
                <button
                  className="pf-btn small"
                  aria-label={n.pinned ? "Unpin" : "Pin"}
                  onClick={() => void run(() => api.platformEditNote(n.id, { pinned: !n.pinned }))}
                >
                  {n.pinned ? <PinOff size={13} /> : <Pin size={13} />}
                </button>
                <button
                  className="pf-btn small"
                  aria-label="Edit"
                  onClick={() => {
                    setEditing(n);
                    setDraft(n.body);
                  }}
                >
                  <Pencil size={13} />
                </button>
                <button
                  className="pf-btn small danger"
                  aria-label="Delete"
                  onClick={() => {
                    if (window.confirm("Delete this note?"))
                      void run(() => api.platformDeleteNote(n.id));
                  }}
                >
                  <Trash2 size={13} />
                </button>
              </span>
            </header>
            {editing?.id === n.id ? (
              <form
                className="pf-stack"
                onSubmit={(e) => {
                  e.preventDefault();
                  void run(async () => {
                    await api.platformEditNote(n.id, { body: draft.trim() });
                    setEditing(null);
                  });
                }}
              >
                <textarea
                  aria-label="Edit note"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  rows={3}
                  maxLength={2000}
                  required
                  style={{
                    width: "100%",
                    padding: 10,
                    borderRadius: 9,
                    border: "1px solid var(--pf-border)",
                    background: "var(--pf-panel)",
                    color: "var(--pf-text)",
                    font: "inherit",
                  }}
                />
                <div style={{ display: "flex", gap: 8 }}>
                  <button className="pf-btn primary small">Save</button>
                  <button type="button" className="pf-btn small" onClick={() => setEditing(null)}>
                    Cancel
                  </button>
                </div>
              </form>
            ) : (
              <p>{n.body}</p>
            )}
          </div>
        ))}
      </div>
    </>
  );
}

function Activity({ id }: { id: string }) {
  const log = useLoad(
    () => api.platformAudit({ business_id: id, days: 730, page_size: 100 }),
    [id],
  );
  return (
    <Panel title="Everything the platform and the customer did to this subscription" flush>
      {log.data && (
        <DataTable
          rows={log.data.rows}
          rowKey={(r) => r.id}
          pageSize={20}
          empty="Nothing yet."
          columns={[
            { key: "at", nowrap: true, header: "When", render: (r) => dateTime(r.at) },
            { key: "who", header: "Who", render: (r) => r.actor ?? "The customer" },
            {
              key: "what",
              header: "What",
              render: (r) => (
                <>
                  <strong>{actionText(r.action)}</strong>
                  {r.note && <div className="pf-muted">{r.note}</div>}
                </>
              ),
            },
            {
              key: "detail",
              header: "Change",
              render: (r) =>
                r.before || r.after ? (
                  <div className="pf-diff">
                    {JSON.stringify({ before: r.before ?? undefined, after: r.after ?? undefined })}
                  </div>
                ) : null,
            },
          ]}
        />
      )}
    </Panel>
  );
}

function Account({
  d,
  p,
  id,
  onDialog,
}: {
  d: PlatformSubscriptionDetail;
  p: PlatformBusinessDetail;
  id: string;
  onDialog: (x: Dialog) => void;
}) {
  const nav = useNavigate();
  const { reload } = useAuth();
  const toast = useToast();
  async function enter() {
    try {
      await api.platformEnterSupport(id);
      await reload();
      nav("/");
    } catch (e) {
      toast.err(e instanceof Error ? e.message : "Could not enter.");
    }
  }
  return (
    <>
      <Panel
        title="Business details"
        actions={
          <button className="pf-btn small" onClick={() => onDialog("details")}>
            <Pencil size={13} /> Correct
          </button>
        }
      >
        <dl className="pf-kv">
          <dt>Name</dt>
          <dd>{p.name}</dd>
          <dt>KRA PIN</dt>
          <dd>{p.kra_pin ?? "not set"}</dd>
        </dl>
      </Panel>
      <Panel title="Support access">
        {d.support_grant.active ? (
          <>
            <p>
              The owner has allowed support access until{" "}
              <strong>{dateTime(d.support_grant.expires_at)}</strong>. Entering is read-only and
              every entry is logged in their audit trail.
            </p>
            <button className="pf-btn primary" onClick={enter}>
              <ShieldCheck size={15} /> Enter this account <ExternalLink size={13} />
            </button>
          </>
        ) : (
          <p className="pf-muted">
            The owner has not given support access. Ask them to allow it in Settings, Support
            access; you cannot see inside the account otherwise.
          </p>
        )}
      </Panel>
      <Panel title="Account controls">
        <div className="pf-stack">
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button className="pf-btn" onClick={() => onDialog("trial")}>
              Extend the trial
            </button>
            <button className="pf-btn" onClick={() => onDialog("complimentary")}>
              {d.complimentary ? "End free account" : "Make a free account"}
            </button>
            <button
              className={`pf-btn${d.suspended ? "" : " danger"}`}
              onClick={() => onDialog("suspend")}
            >
              {d.suspended ? "Lift the hold" : "Put on hold"}
            </button>
            {d.subscription.cancelled_at ? (
              <button className="pf-btn" onClick={() => onDialog("reactivate")}>
                Reactivate the subscription
              </button>
            ) : (
              <button className="pf-btn danger" onClick={() => onDialog("cancel")}>
                Cancel the subscription
              </button>
            )}
          </div>
          <p className="pf-muted" style={{ margin: 0 }}>
            Every change asks for a reason and is written to the customer's own audit trail.
          </p>
        </div>
      </Panel>
    </>
  );
}

// ---- small dialogs ------------------------------------------------------------------------------------------------------------

function ReasonAction({
  title,
  description,
  submit,
  danger,
  noReason,
  run,
  onClose,
  onDone,
}: {
  title: string;
  description: string;
  submit: string;
  danger?: boolean;
  noReason?: boolean;
  run: (reason: string) => Promise<unknown>;
  onClose: () => void;
  onDone: () => void | Promise<void>;
}) {
  const [reason, setReason] = useState("");
  return (
    <FormDialog
      title={title}
      description={description}
      submitLabel={submit}
      danger={danger}
      onClose={onClose}
      onSubmit={async () => {
        await run(reason);
        await onDone();
      }}
    >
      {!noReason && <ReasonField value={reason} onChange={setReason} />}
    </FormDialog>
  );
}

function TrialDialog({
  id,
  onClose,
  onDone,
}: {
  id: string;
  onClose: () => void;
  onDone: () => void | Promise<void>;
}) {
  const [days, setDays] = useState("14");
  const [reason, setReason] = useState("");
  return (
    <FormDialog
      title="Extend the trial"
      description="More time before the first payment is due, counted from today or the current trial end, whichever is later."
      submitLabel="Extend"
      onClose={onClose}
      onSubmit={async () => {
        await api.platformAct(id, "extend-trial", { days: Number(days), reason });
        await onDone();
      }}
    >
      <FormField label="Days (1 to 90)">
        <input
          type="number"
          min={1}
          max={90}
          value={days}
          onChange={(e) => setDays(e.target.value)}
          required
        />
      </FormField>
      <ReasonField value={reason} onChange={setReason} />
    </FormDialog>
  );
}

function PlanDialog({
  id,
  v,
  onClose,
  onDone,
}: {
  id: string;
  v: { vehicleId: string; registration: string; plan: PlanName };
  onClose: () => void;
  onDone: () => void | Promise<void>;
}) {
  const [plan, setPlan] = useState<PlanName>(v.plan);
  const [reason, setReason] = useState("");
  return (
    <FormDialog
      title={`Plan for ${v.registration}`}
      description="Applies at once and is billed on the next invoice."
      submitLabel="Change the plan"
      onClose={onClose}
      onSubmit={async () => {
        await api.platformVehiclePlan(id, v.vehicleId, plan, reason);
        await onDone();
      }}
    >
      <FormField label="Plan">
        <select value={plan} onChange={(e) => setPlan(e.target.value as PlanName)}>
          <option value="starter">Starter</option>
          <option value="standard">Standard</option>
          <option value="premium">Premium</option>
        </select>
      </FormField>
      <ReasonField value={reason} onChange={setReason} />
    </FormDialog>
  );
}

function RaiseInvoiceDialog({
  id,
  onClose,
  onDone,
}: {
  id: string;
  onClose: () => void;
  onDone: () => void | Promise<void>;
}) {
  const plans = useLoad(() => api.plans());
  const [kind, setKind] = useState<"subscription" | "sms_bundle">("subscription");
  const [messages, setMessages] = useState("500");
  const [total, setTotal] = useState("");
  const [reason, setReason] = useState("");
  return (
    <FormDialog
      title="Raise an invoice"
      description="From the plans the vehicles are on now, or a text bundle. Optionally at a total agreed with the customer instead of the price list."
      submitLabel="Raise the invoice"
      onClose={onClose}
      onSubmit={async () => {
        await api.platformRaiseInvoice(id, {
          kind,
          messages: kind === "sms_bundle" ? Number(messages) : undefined,
          total_cents: total.trim() ? Math.round(Number(total) * 100) : undefined,
          reason,
        });
        await onDone();
      }}
    >
      <FormField label="What for">
        <select value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
          <option value="subscription">The next subscription period</option>
          <option value="sms_bundle">A text message bundle</option>
        </select>
      </FormField>
      {kind === "sms_bundle" && (
        <FormField label="Bundle">
          <select value={messages} onChange={(e) => setMessages(e.target.value)}>
            {(plans.data?.sms_bundles ?? []).map((b) => (
              <option key={b.messages} value={b.messages}>
                {b.messages.toLocaleString()} messages, {kes(b.price_cents)}
              </option>
            ))}
          </select>
        </FormField>
      )}
      <FormField label="Agreed total (KES, optional)" hint="Leave empty to use the price list.">
        <input
          type="number"
          min={1}
          step="any"
          value={total}
          onChange={(e) => setTotal(e.target.value)}
        />
      </FormField>
      <ReasonField value={reason} onChange={setReason} />
    </FormDialog>
  );
}

function DetailsDialog({
  id,
  name,
  pin,
  onClose,
  onDone,
}: {
  id: string;
  name: string;
  pin: string | null;
  onClose: () => void;
  onDone: () => void | Promise<void>;
}) {
  const [newName, setNewName] = useState(name);
  const [newPin, setNewPin] = useState(pin ?? "");
  const [reason, setReason] = useState("");
  return (
    <FormDialog
      title="Correct the business details"
      description="For a typo at sign-up or a rename. The old values are kept in the customer's audit trail."
      submitLabel="Save"
      onClose={onClose}
      onSubmit={async () => {
        await api.platformEditBusiness(id, {
          name: newName !== name ? newName : undefined,
          kra_pin: newPin !== (pin ?? "") ? newPin || null : undefined,
          reason,
        });
        await onDone();
      }}
    >
      <FormField label="Business name">
        <input
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          minLength={2}
          maxLength={160}
          required
        />
      </FormField>
      <FormField label="KRA PIN">
        <input value={newPin} onChange={(e) => setNewPin(e.target.value)} maxLength={20} />
      </FormField>
      <ReasonField value={reason} onChange={setReason} />
    </FormDialog>
  );
}
