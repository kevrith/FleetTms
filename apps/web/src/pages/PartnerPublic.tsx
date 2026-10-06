import type { PartnerPortal } from "@fleettms/types";
import { useState, type FormEvent } from "react";
import { api } from "../api";
import { kes, nairobiTime } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";
import PublicShell from "./PublicShell";

const STATE: Record<string, string> = {
  trialing: "On trial",
  active: "Paying",
  grace: "Overdue",
  read_only: "Read-only",
  suspended: "On hold",
  cancelled: "Cancelled",
  complimentary: "Free account",
};

/** For GPS tracker installers and others who bring customers to FleetTms: how to join, and the private report once you have a key. */
export default function PartnerPublic() {
  const [form, setForm] = useState({
    name: "",
    contact_name: "",
    phone: "",
    email: "",
    city: "",
    message: "",
  });
  const [sent, setSent] = useState(false);
  const [key, setKey] = useState(() => sessionStorage.getItem("fleettms.partner-key") ?? "");
  const [report, setReport] = useState<PartnerPortal | null>(null);
  const [error, setError] = useState<string | null>(null);
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm({ ...form, [k]: e.target.value });

  async function apply(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.applyAsPartner({
        ...form,
        email: form.email || undefined,
        city: form.city || undefined,
        message: form.message || undefined,
      });
      setSent(true);
    } catch (err) {
      setError(errorMessage(err));
    }
  }
  async function open(e?: FormEvent) {
    e?.preventDefault();
    setError(null);
    try {
      setReport(await api.partnerPortal(key.trim()));
      sessionStorage.setItem("fleettms.partner-key", key.trim());
    } catch (err) {
      setReport(null);
      setError(errorMessage(err));
    }
  }
  return (
    <PublicShell
      title={report ? report.partner.name : "Become a FleetTms partner"}
      intro={
        report
          ? undefined
          : "If you fit GPS trackers or fuel sensors for transport businesses, you can bring them to FleetTms and earn a share of what they pay for as long as the arrangement runs. Tell us about your business and we will call you."
      }
      crumbs={[{ label: "Partners" }]}
    >
      <ErrorBanner message={error} />
      {report ? (
        <>
          <Card title="Your code">
            <p>
              Give customers the code <strong>{report.partner.code}</strong> to type when they sign
              up. You earn <strong>{report.partner.commission_pct}%</strong> of what each customer
              pays
              {report.partner.commission_months > 0
                ? `, for ${report.partner.commission_months} months from their first payment`
                : ", for as long as they pay"}
              .
            </p>
            <p>
              Owed to you: <strong>{kes(report.totals.owed_cents)}</strong>. Already paid:{" "}
              <strong>{kes(report.totals.paid_cents)}</strong>. {report.totals.referred} referred,{" "}
              {report.totals.paying} paying.
            </p>
          </Card>
          <Card title="Businesses you brought in">
            {report.referrals.length === 0 && <p className="muted">None yet.</p>}
            <ul className="list">
              {report.referrals.map((r) => (
                <li key={`${r.business}${r.referred_at}`}>
                  <span>
                    {r.business}{" "}
                    <span className="muted">
                      joined {nairobiTime(r.referred_at)}, {r.vehicles} vehicles
                    </span>
                  </span>
                  <span className={`status ${r.state === "active" ? "ok" : "warn"}`}>
                    {STATE[r.state] ?? r.state}
                  </span>
                </li>
              ))}
            </ul>
            <p className="muted">
              You see the business name, how it stands and its size. Nothing about its people or
              records.
            </p>
          </Card>
          <Card title="What you have earned">
            {report.commissions.length === 0 && (
              <p className="muted">Commission appears here when a business you brought in pays.</p>
            )}
            <ul className="list">
              {report.commissions.map((c) => (
                <li key={c.id}>
                  <span>
                    {c.business}{" "}
                    <span className="muted">
                      {c.invoice}, they paid {kes(c.paid_by_business_cents)}
                    </span>
                  </span>
                  <span>
                    {kes(c.amount_cents)}{" "}
                    <span className={`status ${c.status === "paid" ? "ok" : "warn"}`}>
                      {c.status === "paid" ? `paid ${c.payout_reference ?? ""}` : "owed"}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          </Card>
        </>
      ) : (
        <>
          {sent ? (
            <p className="banner ok">Thank you. We have your details and will call you.</p>
          ) : (
            <Card title="Apply">
              <form onSubmit={apply} className="form-grid">
                <Field label="Your business">
                  <input value={form.name} onChange={set("name")} required minLength={2} />
                </Field>
                <Field label="Your name">
                  <input
                    value={form.contact_name}
                    onChange={set("contact_name")}
                    required
                    minLength={2}
                  />
                </Field>
                <Field label="Phone">
                  <input
                    value={form.phone}
                    onChange={set("phone")}
                    required
                    inputMode="tel"
                    placeholder="0712 345 678"
                  />
                </Field>
                <Field label="Email (optional)">
                  <input type="email" value={form.email} onChange={set("email")} />
                </Field>
                <Field label="Town (optional)">
                  <input value={form.city} onChange={set("city")} />
                </Field>
                <Field label="Tell us about your work (optional)">
                  <textarea value={form.message} onChange={set("message")} maxLength={1000} />
                </Field>
                <p className="actions">
                  <button className="btn primary" type="submit">
                    Send my application
                  </button>
                </p>
              </form>
            </Card>
          )}
          <Card title="Already a partner?">
            <form onSubmit={open} className="form-grid">
              <Field label="Your private key (we texted it to you)">
                <input
                  value={key}
                  onChange={(e) => setKey(e.target.value)}
                  type="password"
                  autoComplete="off"
                  required
                />
              </Field>
              <p className="actions">
                <button className="btn" type="submit">
                  See my report
                </button>
              </p>
            </form>
          </Card>
        </>
      )}
    </PublicShell>
  );
}
