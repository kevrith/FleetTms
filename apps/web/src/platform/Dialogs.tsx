import type { PlatformSubscriptionDetail } from "@fleettms/types";
import { useState } from "react";
import { api } from "../api";
import { dayValue, endOfDay } from "./format";
import { FormDialog, FormField, ReasonField } from "./kit";

type Done = () => void | Promise<void>;

/** Moves the renewal date forward without an invoice: a goodwill month, a delay on our side. */
export function AdvanceDialog({
  businessId,
  onClose,
  onDone,
}: {
  businessId: string;
  onClose: () => void;
  onDone: Done;
}) {
  const [months, setMonths] = useState("1");
  const [days, setDays] = useState("0");
  const [reason, setReason] = useState("");
  return (
    <FormDialog
      title="Advance the renewal"
      description="Moves the paid-until date forward without raising an invoice. It counts from the current paid-until date, or from today if that has passed or nothing has been paid."
      submitLabel="Advance"
      onClose={onClose}
      onSubmit={async () => {
        await api.platformAdvance(businessId, Number(months), Number(days), reason);
        await onDone();
      }}
    >
      <div className="pf-grid cols-2" style={{ marginBottom: 0 }}>
        <FormField label="Months">
          <input
            type="number"
            min={0}
            max={36}
            value={months}
            onChange={(e) => setMonths(e.target.value)}
          />
        </FormField>
        <FormField label="And days">
          <input
            type="number"
            min={0}
            max={1100}
            value={days}
            onChange={(e) => setDays(e.target.value)}
          />
        </FormField>
      </div>
      <ReasonField value={reason} onChange={setReason} />
    </FormDialog>
  );
}

/** Edits the recorded dates, billing period and agreed price by hand; only what changed is sent. */
export function EditSubscriptionDialog({
  detail,
  onClose,
  onDone,
}: {
  detail: PlatformSubscriptionDetail;
  onClose: () => void;
  onDone: Done;
}) {
  const s = detail.subscription;
  const [period, setPeriod] = useState<string>(s.period);
  const [paidUntil, setPaidUntil] = useState(dayValue(s.paid_until));
  const [trialEnds, setTrialEnds] = useState(dayValue(s.trial_ends_at));
  const [payroll, setPayroll] = useState(s.payroll_enabled);
  const [price, setPrice] = useState(
    s.custom_monthly_cents ? String(s.custom_monthly_cents / 100) : "",
  );
  const [reason, setReason] = useState("");
  return (
    <FormDialog
      title="Edit the subscription"
      description="For a correction or a deal. Each change is written, old value and new, into the customer's audit trail."
      submitLabel="Save changes"
      onClose={onClose}
      onSubmit={async () => {
        const body: Parameters<typeof api.platformEditSubscription>[1] = { reason };
        if (period !== s.period) body.period = period as "monthly" | "annual";
        if (payroll !== s.payroll_enabled) body.payroll_enabled = payroll;
        if (paidUntil !== dayValue(s.paid_until))
          body.paid_until = paidUntil ? endOfDay(paidUntil) : null;
        if (trialEnds && trialEnds !== dayValue(s.trial_ends_at))
          body.trial_ends_at = endOfDay(trialEnds);
        const cents = price.trim() ? Math.round(Number(price) * 100) : null;
        if (cents !== s.custom_monthly_cents) body.custom_monthly_cents = cents;
        await api.platformEditSubscription(detail.business.id, body);
        await onDone();
      }}
    >
      <FormField label="Billing period">
        <select value={period} onChange={(e) => setPeriod(e.target.value)}>
          <option value="monthly">Monthly</option>
          <option value="annual">Annual (10 months for 12)</option>
        </select>
      </FormField>
      <div className="pf-grid cols-2" style={{ marginBottom: 0 }}>
        <FormField label="Paid until" hint="Empty means nothing is paid for.">
          <input type="date" value={paidUntil} onChange={(e) => setPaidUntil(e.target.value)} />
        </FormField>
        <FormField label="Trial ends">
          <input
            type="date"
            value={trialEnds}
            onChange={(e) => setTrialEnds(e.target.value)}
            required
          />
        </FormField>
      </div>
      <FormField
        label="Agreed monthly price (KES)"
        hint="For a large fleet priced by agreement. Empty goes back to the price list."
      >
        <input
          type="number"
          min={1000}
          step="any"
          value={price}
          onChange={(e) => setPrice(e.target.value)}
        />
      </FormField>
      <label
        className="pf-field"
        style={{ gridAutoFlow: "column", justifyContent: "start", alignItems: "center", gap: 8 }}
      >
        <input type="checkbox" checked={payroll} onChange={(e) => setPayroll(e.target.checked)} />
        <span>Payroll add-on on</span>
      </label>
      <ReasonField value={reason} onChange={setReason} />
    </FormDialog>
  );
}

/** A bank transfer or card payment arrived outside the system. */
export function MarkPaidDialog({
  invoiceId,
  number,
  onClose,
  onDone,
}: {
  invoiceId: string;
  number: string;
  onClose: () => void;
  onDone: Done;
}) {
  const [method, setMethod] = useState<"bank" | "manual" | "card">("bank");
  const [reference, setReference] = useState("");
  return (
    <FormDialog
      title={`Mark ${number} as paid`}
      description="The invoice is paid, the period starts, and the tax invoice is queued for KRA. Do this only when the money has arrived."
      submitLabel="Mark as paid"
      onClose={onClose}
      onSubmit={async () => {
        await api.platformMarkPaid(invoiceId, reference.trim(), method);
        await onDone();
      }}
    >
      <FormField label="How it was paid">
        <select value={method} onChange={(e) => setMethod(e.target.value as typeof method)}>
          <option value="bank">Bank transfer</option>
          <option value="card">Card, taken outside the system</option>
          <option value="manual">Cash or cheque</option>
        </select>
      </FormField>
      <FormField
        label="Reference"
        hint="The transfer reference or cheque number, 3 to 12 characters."
      >
        <input
          value={reference}
          onChange={(e) => setReference(e.target.value)}
          minLength={3}
          maxLength={12}
          required
        />
      </FormField>
    </FormDialog>
  );
}

/** Cancels an invoice nobody has paid. */
export function VoidDialog({
  invoiceId,
  number,
  onClose,
  onDone,
}: {
  invoiceId: string;
  number: string;
  onClose: () => void;
  onDone: Done;
}) {
  const [reason, setReason] = useState("");
  return (
    <FormDialog
      title={`Void ${number}`}
      description="Only an invoice nobody has paid can be voided. A paid one needs a refund, outside FleetTms."
      submitLabel="Void the invoice"
      danger
      onClose={onClose}
      onSubmit={async () => {
        await api.platformVoidInvoice(invoiceId, reason);
        await onDone();
      }}
    >
      <ReasonField value={reason} onChange={setReason} />
    </FormDialog>
  );
}
