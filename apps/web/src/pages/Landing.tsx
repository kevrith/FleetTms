import type { PlansInfo } from "@fleettms/types";
import {
  ArrowRight,
  Camera,
  CheckCircle2,
  ClipboardCheck,
  Download,
  FileCheck2,
  Fuel,
  LineChart,
  MapPin,
  ReceiptText,
  ShieldAlert,
  ShieldCheck,
  Smartphone,
  Truck,
  WifiOff,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { ANDROID_APP_URL } from "../appLinks";
import { kes } from "../labels";
import "./landing.css";
import { PublicFooter, PublicHeader } from "./PublicShell";

const CAPABILITIES = [
  { icon: WifiOff, label: "Works offline on drivers' phones" },
  { icon: FileCheck2, label: "KRA eTIMS invoicing" },
  { icon: ReceiptText, label: "M-Pesa payments matched for you" },
  { icon: ShieldCheck, label: "Full data export, any time" },
];

const POINTS = [
  {
    icon: Smartphone,
    title: "Drivers use a phone",
    text: "Photos of the odometer and receipts, trips, fuel and expenses, even with no signal.",
  },
  {
    icon: Fuel,
    title: "Catch fuel and money leaks",
    text: "Fuel against what each lorry normally uses, expenses against the route, every flag with its evidence.",
  },
  {
    icon: MapPin,
    title: "See where every lorry is",
    text: "Phone tracking on every plan, and a live map and replay with GPS trackers.",
  },
  {
    icon: ReceiptText,
    title: "Quote, bill and get paid",
    text: "Quotes, jobs, invoices, eTIMS and M-Pesa payments matched for you.",
  },
  {
    icon: Truck,
    title: "Know what each lorry earns",
    text: "Profit per vehicle, client and driver, with leases, loans and salaries counted.",
  },
  {
    icon: ShieldCheck,
    title: "Your data stays yours",
    text: "Take a full copy whenever you like. Your staff can ask what is held about them.",
  },
];

const STEPS = [
  {
    icon: Camera,
    title: "The driver records it on the spot",
    text: "Odometer, fuel, cargo and receipts are photographed and stamped with time and place. Nothing waits for paperwork at the end of the week.",
  },
  {
    icon: ClipboardCheck,
    title: "The office sees what needs attention",
    text: "Unusual fuel, expenses that do not fit the route and overdue documents are flagged, each with the photo behind it.",
  },
  {
    icon: LineChart,
    title: "The owner sees what was earned",
    text: "Invoices go out, payments are matched, and profit is worked out for each vehicle, client and driver.",
  },
];

const PREVIEW_ROWS = [
  { plate: "KAA 123A", state: "On trip, Nairobi to Mombasa", tone: "ok" },
  { plate: "KBB 456B", state: "In the workshop, brakes", tone: "warn" },
  { plate: "KCC 789C", state: "Fuel flagged for review", tone: "alert" },
];

/** The front page for people who are not signed in: what FleetTms is, what it costs, and how to start. Nothing here tracks the visitor. */
export default function Landing() {
  const [plans, setPlans] = useState<PlansInfo | null>(null);
  useEffect(() => {
    api
      .plans()
      .then(setPlans)
      .catch(() => setPlans(null));
  }, []);
  const trialDays = plans?.trial_days ?? 14;
  return (
    <div className="lp">
      <PublicHeader />

      <section className="lp-hero">
        <div className="lp-wrap lp-hero-grid">
          <div>
            <p className="lp-eyebrow">Fleet management for Kenyan transport businesses</p>
            <h1>Know where every lorry is, and what every lorry earns.</h1>
            <p className="lp-lead">
              Trips, fuel, expenses, tracking, invoicing and profit for every vehicle, in one place.
              Drivers work from a phone, the office works from here, and the owner sees the result.
            </p>
            <div className="lp-cta">
              <Link className="lp-btn lp-btn-primary lp-btn-lg" to="/signup">
                Start your free {trialDays} days <ArrowRight size={18} />
              </Link>
              <a className="lp-btn lp-btn-ghost lp-btn-lg" href="#how">
                See how it works
              </a>
              <a className="lp-btn lp-btn-ghost lp-btn-lg" href={ANDROID_APP_URL}>
                <Download size={18} /> Get the Android app
              </a>
            </div>
            <p className="lp-fine">No payment details needed to start.</p>
          </div>

          <figure className="lp-preview" aria-label="Example of the fleet overview">
            <div className="lp-preview-head">
              <span>Fleet today</span>
              <span className="lp-preview-live">Live</span>
            </div>
            <ul>
              {PREVIEW_ROWS.map((r) => (
                <li key={r.plate}>
                  <span className={`lp-dot lp-dot-${r.tone}`} />
                  <span className="lp-plate">{r.plate}</span>
                  <span className="lp-state">{r.state}</span>
                </li>
              ))}
            </ul>
            <div className="lp-flag">
              <ShieldAlert size={18} />
              <div>
                <strong>Fuel above normal for this route</strong>
                <span>Receipt photo and pump reading attached for review.</span>
              </div>
            </div>
            <figcaption>Sample data, for illustration.</figcaption>
          </figure>
        </div>
      </section>

      <section className="lp-strip" aria-label="Built for Kenya">
        <div className="lp-wrap lp-strip-row">
          {CAPABILITIES.map(({ icon: Icon, label }) => (
            <span key={label}>
              <Icon size={18} /> {label}
            </span>
          ))}
        </div>
      </section>

      <section id="features" className="lp-section">
        <div className="lp-wrap">
          <p className="lp-kicker">What you get</p>
          <h2>Everything a transport business runs on, connected</h2>
          <div className="lp-grid">
            {POINTS.map(({ icon: Icon, title, text }) => (
              <article key={title} className="lp-feature">
                <span className="lp-tile">
                  <Icon size={22} />
                </span>
                <h3>{title}</h3>
                <p>{text}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section id="how" className="lp-section lp-alt">
        <div className="lp-wrap">
          <p className="lp-kicker">How it works</p>
          <h2>From the road to the books, without the paperwork</h2>
          <ol className="lp-steps">
            {STEPS.map(({ icon: Icon, title, text }, i) => (
              <li key={title}>
                <span className="lp-step-no">{i + 1}</span>
                <Icon size={24} className="lp-step-icon" />
                <h3>{title}</h3>
                <p>{text}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section id="pricing" className="lp-section">
        <div className="lp-wrap">
          <p className="lp-kicker">Pricing</p>
          <h2>Pay per vehicle, only for what each one needs</h2>
          <p className="lp-sub">
            Prices are per vehicle per month, and each vehicle can be on a different plan.
            {plans &&
              ` Pay for a year and get ${plans.annual_months_paid} months charged for 12. From ${plans.volume.from} to ${plans.volume.to} vehicles, ${plans.volume.pct}% off. From ${plans.volume.custom_from} vehicles, we agree a price with you.`}
          </p>
          {plans ? (
            <div className="lp-prices">
              {plans.plans.map((p) => (
                <article className="lp-plan" key={p.plan}>
                  <h3>{p.name}</h3>
                  <p className="lp-price">
                    {kes(p.price_cents)}
                    <small>per vehicle, per month</small>
                  </p>
                  <ul>
                    {p.features.slice(-6).map((f) => (
                      <li key={f}>
                        <CheckCircle2 size={16} /> {plans.features[f]?.name ?? f}
                      </li>
                    ))}
                  </ul>
                  <Link className="lp-btn lp-btn-outline" to="/signup">
                    Start free trial
                  </Link>
                </article>
              ))}
            </div>
          ) : (
            <p className="lp-sub">Prices are shown here when you are online.</p>
          )}
          <p className="lp-note">
            Texts are sold in bundles. Payroll with the usual deductions is{" "}
            {plans ? kes(plans.payroll_cents) : "a small fee"} per employee a month. If you do not
            pay, your account turns read-only after {plans?.grace_days ?? 7} days of grace; nothing
            is deleted.
          </p>
        </div>
      </section>

      <section className="lp-wrap">
        <div className="lp-partner">
          <div>
            <h3>Do you fit GPS trackers?</h3>
            <p>Bring your customers to FleetTms and earn a share of what they pay.</p>
          </div>
          <Link className="lp-btn lp-btn-light" to="/partners">
            Become a partner <ArrowRight size={16} />
          </Link>
        </div>
      </section>

      <section className="lp-final">
        <div className="lp-wrap">
          <h2>Start with one lorry, or the whole fleet</h2>
          <p>
            Try everything free for {trialDays} days. If it is not for you, nothing is deleted and
            you can take a full copy of your data.
          </p>
          <Link className="lp-btn lp-btn-primary lp-btn-lg" to="/signup">
            Start your free {trialDays} days <ArrowRight size={18} />
          </Link>
        </div>
      </section>

      <PublicFooter />
    </div>
  );
}
