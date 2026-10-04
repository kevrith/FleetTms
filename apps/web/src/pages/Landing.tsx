import type { PlansInfo } from "@fleettms/types";
import { Fuel, MapPin, ReceiptText, ShieldCheck, Smartphone, Truck } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { kes } from "../labels";

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

/** The front page for people who are not signed in: what FleetTms is, what it costs, and how to start. Nothing here tracks the visitor. */
export default function Landing() {
  const [plans, setPlans] = useState<PlansInfo | null>(null);
  useEffect(() => {
    api
      .plans()
      .then(setPlans)
      .catch(() => setPlans(null));
  }, []);
  return (
    <div className="landing">
      <header className="landing-bar">
        <strong>FleetTms</strong>
        <nav>
          <Link to="/help">Help</Link>
          <Link to="/partners">Partners</Link>
          <Link to="/login">Sign in</Link>
        </nav>
      </header>
      <section className="hero">
        <h1>Run your lorries with a phone, not a pile of paper.</h1>
        <p>
          FleetTms is for Kenyan transport businesses: trips, fuel, expenses, tracking, invoices and
          profit for every vehicle, in one place that your drivers can use.
        </p>
        <p className="actions">
          <Link className="btn primary" to="/signup">
            Start your free {plans?.trial_days ?? 14} days
          </Link>
          <span className="muted">No payment details needed.</span>
        </p>
      </section>
      <section className="points">
        {POINTS.map(({ icon: Icon, title, text }) => (
          <div key={title} className="card">
            <h3>
              <Icon size={20} /> {title}
            </h3>
            <p>{text}</p>
          </div>
        ))}
      </section>
      <section id="pricing">
        <h2>Prices</h2>
        <p className="muted">
          Per vehicle per month, and each vehicle can be on a different plan.
          {plans &&
            ` Pay for a year and get ${plans.annual_months_paid} months charged for 12. From ${plans.volume.from} to ${plans.volume.to} vehicles, ${plans.volume.pct}% off. From ${plans.volume.custom_from} vehicles, we agree a price with you.`}
        </p>
        {plans ? (
          <div className="price-grid">
            {plans.plans.map((p) => (
              <div className="card" key={p.plan}>
                <h3>{p.name}</h3>
                <p className="price">{kes(p.price_cents)}</p>
                <ul>
                  {p.features.slice(-6).map((f) => (
                    <li key={f}>{plans.features[f]?.name ?? f}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        ) : (
          <p className="muted">Prices are shown here when you are online.</p>
        )}
        <p className="muted">
          Texts are sold in bundles. Payroll with the usual deductions is{" "}
          {plans ? kes(plans.payroll_cents) : "a small fee"} per employee a month. If you do not
          pay, your account turns read-only after {plans?.grace_days ?? 7} days of grace; nothing is
          deleted.
        </p>
      </section>
      <section className="card">
        <h3>Do you fit GPS trackers?</h3>
        <p>
          Bring your customers to FleetTms and earn a share of what they pay.{" "}
          <Link to="/partners">Become a partner</Link>.
        </p>
      </section>
      <footer className="landing-foot">
        <Link to="/help">Help and contact</Link> · <Link to="/login">Sign in</Link> · Kastra
        Enterprises
      </footer>
    </div>
  );
}
