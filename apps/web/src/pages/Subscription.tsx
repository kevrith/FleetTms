import { quoteSubscription } from "@fleettms/business-rules";
import type { PlanName, PlansInfo, SubscriptionInvoice, SubscriptionStatus } from "@fleettms/types";
import { CreditCard } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { kes, nairobiTime } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

const STATE_TEXT: Record<string, [string, string]> = {
  trialing: ["On the free trial", "ok"],
  active: ["Paid up", "ok"],
  grace: ["Payment overdue: everything still works for now", "warn"],
  read_only: ["Read-only: not paid", "bad"],
  suspended: ["On hold", "bad"],
  complimentary: ["Free account", "ok"],
};
const PLAN_NAME: Record<PlanName, string> = {
  starter: "Starter",
  standard: "Standard",
  premium: "Premium",
};

/** The owner's subscription: where it stands, each vehicle's plan, the price, and paying by M-Pesa. */
export default function SubscriptionPage() {
  const [s, setS] = useState<SubscriptionStatus | null>(null);
  const [plans, setPlans] = useState<PlansInfo | null>(null);
  const [phone, setPhone] = useState("");
  const [waiting, setWaiting] = useState<SubscriptionInvoice | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const load = useCallback(async () => {
    try {
      setS(await api.subscription());
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => {
    void load();
    api
      .plans()
      .then(setPlans)
      .catch(() => undefined);
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [load]);

  async function act(work: () => Promise<unknown>, done?: string) {
    setError(null);
    setMessage(null);
    try {
      await work();
      if (done) setMessage(done);
      await load();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  /** Asks the phone to pay, then watches the invoice until Safaricom says it was paid (or gives up). */
  async function pay(invoice: SubscriptionInvoice) {
    setError(null);
    try {
      const res = await api.payInvoice(invoice.id, phone);
      setMessage(res.message);
      setWaiting(invoice);
      let tries = 0;
      if (timer.current) clearInterval(timer.current);
      timer.current = setInterval(async () => {
        tries += 1;
        const now = await api.invoiceStatus(invoice.id).catch(() => null);
        if (now?.status === "paid" || tries > 40 || now?.last_payment?.status === "failed") {
          if (timer.current) clearInterval(timer.current);
          setWaiting(null);
          setMessage(
            now?.status === "paid"
              ? "Paid. Thank you: everything is switched on."
              : (now?.last_payment?.note ?? "The payment was not completed."),
          );
          await load();
        }
      }, 3000);
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  if (!s) return <ErrorBanner message={error} />;
  const [stateText, tone] = STATE_TEXT[s.access.state] ?? [s.access.state, "ok"];
  const q = s.quote;
  const preview = quoteSubscription(
    s.vehicles.map((v) => v.plan),
    { period: s.period, payroll_employees: s.payroll_enabled ? s.payroll_employees : 0 },
  );
  const owing = s.open_invoice;
  async function cancel() {
    const reason = window.prompt(
      "Why are you leaving? (optional) Your account becomes read-only now. You can still take all your data out.",
    );
    if (reason === null) return;
    if (
      !window.confirm(
        "Cancel the subscription? After 90 days your people's personal details and all photos are deleted. The records the law requires you to keep stay for their own period.",
      )
    )
      return;
    try {
      setS(await api.cancelSubscription(reason.trim() || undefined));
      setMessage("The subscription is cancelled. Nothing is deleted for 90 days.");
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  async function reactivate() {
    try {
      setS(await api.reactivateSubscription());
      setMessage("The cancellation is taken back.");
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  return (
    <>
      <ErrorBanner message={error} />
      {message && (
        <p className="banner ok" role="status">
          {message}
        </p>
      )}
      <Card title="Where you stand">
        <p>
          <span className={`status ${tone}`}>{stateText}</span>{" "}
          {s.access.days_left !== null && s.access.state !== "read_only" && (
            <span className="muted">
              {s.access.state === "grace"
                ? `${s.access.days_left} day(s) before the account becomes read-only. Nothing is deleted.`
                : `${s.access.days_left} day(s) left.`}
            </span>
          )}
        </p>
        {s.paid_until && <p className="muted">Paid until {nairobiTime(s.paid_until)}.</p>}
        {!s.paid_until && s.access.state !== "complimentary" && (
          <p className="muted">
            Free trial until {nairobiTime(s.trial_ends_at)}. No payment details were needed.
          </p>
        )}
        {s.access.state === "read_only" && (
          <p className="banner bad">
            You can see everything and take your data out, but not add anything, until the
            subscription is paid. Pay below and it works again at once.
          </p>
        )}
      </Card>

      <Card title="Each vehicle's plan">
        {s.vehicles.length === 0 && (
          <p className="muted">Add a vehicle first: the price is per vehicle.</p>
        )}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Vehicle</th>
                <th>Plan</th>
                <th>Price a month</th>
              </tr>
            </thead>
            <tbody>
              {s.vehicles.map((v) => (
                <tr key={v.vehicle_id}>
                  <td>{v.registration}</td>
                  <td>
                    <select
                      value={v.plan}
                      aria-label={`Plan for ${v.registration}`}
                      onChange={(e) =>
                        act(() =>
                          api.setVehiclePlans([
                            { vehicle_id: v.vehicle_id, plan: e.target.value as PlanName },
                          ]),
                        )
                      }
                    >
                      {(["starter", "standard", "premium"] as PlanName[]).map((p) => (
                        <option key={p} value={p}>
                          {PLAN_NAME[p]}
                        </option>
                      ))}
                    </select>
                    {v.effective_plan !== v.plan && (
                      <span className="muted">
                        {" "}
                        on trial: works as {PLAN_NAME[v.effective_plan]}
                      </span>
                    )}
                  </td>
                  <td>
                    {plans ? kes(plans.plans.find((p) => p.plan === v.plan)?.price_cents ?? 0) : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {plans && (
          <ul className="muted">
            {plans.plans.map((p) => (
              <li key={p.plan}>
                <strong>{p.name}</strong> {kes(p.price_cents)} a vehicle a month:{" "}
                {p.plan === "starter"
                  ? "trips, phone GPS, quotes and jobs, proof of delivery, inspections, fuel and expenses, floats, services, clients and debts, leasing, basic reports, owner and driver roles."
                  : p.plan === "standard"
                    ? "everything in Starter plus GPS trackers, the live map, replay, mapped areas, driver scorecards, fraud detection, tyres and parts, client tracking links, eTIMS, all roles and custom reports."
                    : "everything in Standard plus fuel sensors, the remote immobiliser, predictions and learned models, plain-English questions and scheduled reports."}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title="The price">
        <ul className="list">
          {preview.lines.map((l) => (
            <li key={l.plan}>
              <span>
                {l.vehicles} x {PLAN_NAME[l.plan]} at {kes(l.unit_cents)}
              </span>
              <span>{kes(l.cents)}</span>
            </li>
          ))}
          {preview.discount_cents > 0 && (
            <li>
              <span>
                {preview.discount_pct}% off for {preview.vehicles} vehicles
              </span>
              <span>-{kes(preview.discount_cents)}</span>
            </li>
          )}
          {preview.payroll_cents > 0 && (
            <li>
              <span>Payroll for {s.payroll_employees} people</span>
              <span>{kes(preview.payroll_cents)}</span>
            </li>
          )}
          <li>
            <strong>A month</strong>
            <strong>{kes(q.custom ? preview.monthly_cents : q.monthly_cents)}</strong>
          </li>
          {s.period === "annual" && (
            <li>
              <span>
                A year, paying {q.months_paid} months for {q.months_covered}
              </span>
              <strong>{kes(q.total_cents)}</strong>
            </li>
          )}
        </ul>
        {q.custom && !q.agreed && (
          <p className="banner warn">
            A fleet of {plans?.volume.custom_from ?? 31} or more vehicles is priced by agreement. We
            will contact you with the price.
          </p>
        )}
        <div className="form-grid">
          <Field label="Pay">
            <select
              value={s.period}
              onChange={(e) =>
                act(() =>
                  api.setSubscriptionSettings({ period: e.target.value as "monthly" | "annual" }),
                )
              }
            >
              <option value="monthly">Every month</option>
              <option value="annual">Once a year (10 months for 12)</option>
            </select>
          </Field>
          <label className="check">
            <input
              type="checkbox"
              checked={s.payroll_enabled}
              onChange={(e) =>
                act(() => api.setSubscriptionSettings({ payroll_enabled: e.target.checked }))
              }
            />
            <span>Payroll with statutory deductions (KES 100 a person a month)</span>
          </label>
        </div>
      </Card>

      <Card title="Pay by M-Pesa">
        {!owing && (
          <p className="actions">
            <button
              className="btn primary"
              type="button"
              disabled={s.vehicles.length === 0 || (q.custom && !q.agreed)}
              onClick={() => act(() => api.raiseInvoice())}
            >
              Get the invoice for the next period
            </button>
          </p>
        )}
        {owing && (
          <>
            <p>
              Invoice {owing.number}: <strong>{kes(owing.total_cents)}</strong>, covering{" "}
              {owing.period_start ? nairobiTime(owing.period_start) : ""} to{" "}
              {owing.period_end ? nairobiTime(owing.period_end) : ""}.
            </p>
            <div className="form-grid">
              <Field label="M-Pesa phone number">
                <input
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  inputMode="tel"
                  placeholder="0712 345 678"
                />
              </Field>
              <button
                className="btn primary"
                type="button"
                disabled={phone.trim().length < 9 || waiting !== null}
                onClick={() => pay(owing)}
              >
                <CreditCard size={16} /> Send the payment request
              </button>
            </div>
            <p className="muted">
              A prompt appears on that phone: enter your M-Pesa PIN. Card payments are not available
              yet; to pay by bank transfer, contact us with the invoice number.
            </p>
          </>
        )}
      </Card>

      <Card title="Text messages">
        <p>
          {s.sms.credits >= 0
            ? `${s.sms.credits} messages left`
            : `${-s.sms.credits} sent on account`}
          ; {s.sms.sent_this_month} sent this month.{" "}
          {s.sms.low && <span className="status warn">Running low</span>}
        </p>
        <p className="muted">
          Alerts and reminders are never held back for want of credit. Buy a bundle to keep the
          count positive.
        </p>
        <p className="actions">
          {plans?.sms_bundles.map((b) => (
            <button
              key={b.messages}
              className="btn"
              type="button"
              onClick={() =>
                act(
                  () => api.buySmsBundle(b.messages),
                  `Invoice raised for ${b.messages} messages.`,
                )
              }
            >
              {b.messages.toLocaleString()} messages, {kes(b.price_cents)}
            </button>
          ))}
        </p>
      </Card>

      <Card title="Invoices">
        {s.invoices.length === 0 && <p className="muted">None yet.</p>}
        <ul className="list">
          {s.invoices.map((i) => (
            <li key={i.id}>
              <span>
                {i.number}{" "}
                {i.kind === "sms_bundle" ? `(${i.sms_messages} text messages)` : "(subscription)"}
              </span>
              <span>
                {kes(i.total_cents)}{" "}
                <span className={`status ${i.status === "paid" ? "ok" : "warn"}`}>
                  {i.status === "paid"
                    ? `paid ${i.paid_at ? nairobiTime(i.paid_at) : ""}`
                    : "waiting for payment"}
                </span>
                {i.status === "issued" && i.kind === "sms_bundle" && (
                  <button
                    className="btn"
                    type="button"
                    onClick={() => pay(i)}
                    disabled={phone.trim().length < 9}
                  >
                    Pay
                  </button>
                )}
              </span>
            </li>
          ))}
        </ul>
      </Card>
      <Card title="Cancel">
        {s.cancelled_at ? (
          <>
            <p>
              The subscription was cancelled on {nairobiTime(s.cancelled_at)}. The account is
              read-only. On{" "}
              <strong>{s.data_removed_on ? nairobiTime(s.data_removed_on) : "the 90th day"}</strong>{" "}
              your people's personal details, photos and tracking are deleted. Take a full copy of
              your data under Your data before then.
            </p>
            <p className="actions">
              <button className="btn" type="button" onClick={reactivate}>
                Take the cancellation back
              </button>
            </p>
          </>
        ) : (
          <>
            <p>
              Ending the subscription makes the account read-only straight away. You can still take
              all your data out for 90 days, then personal details, photos and tracking are deleted.
              Records the law requires you to keep (invoices, payments, payroll, expenses) are kept
              for their own period.
            </p>
            <p className="actions">
              <button className="btn danger" type="button" onClick={cancel}>
                Cancel the subscription
              </button>
            </p>
          </>
        )}
      </Card>
    </>
  );
}
