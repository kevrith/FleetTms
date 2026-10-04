import { ROLE_LABELS } from "@fleettms/business-rules";
import type { PendingDocument } from "@fleettms/types";
import type { SosAlert } from "@fleettms/types";
import { Building, HelpCircle, LogOut, Siren } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { api } from "./api";
import { useAuth } from "./auth";
import { FeedbackButton } from "./Feedback";
import { SubscriptionBanner } from "./SubscriptionBanner";
import { navItems } from "./nav";
import { ErrorBanner, errorMessage } from "./ui";

const DOC_TITLES: Record<string, string> = {
  terms: "Terms of Service",
  privacy: "Privacy Policy",
  dpa: "Data Processing Agreement",
  monitoring_notice: "Driver monitoring notice",
};

const DOC_SUMMARY: Record<string, string> = {
  monitoring_notice:
    "FleetTms records your phone's location while a trip is running, your odometer photos, fuel and expense entries. " +
    "Tracking starts when you start a trip and stops when you end it, the office and (on a link they send) the client's delivery " +
    "can see the lorry's position, and location points are deleted after 12 months.",
};

/** Shown on every page to people who respond to SOS alerts, so an alert is seen within seconds. */
function SosBanner() {
  const [alerts, setAlerts] = useState<SosAlert[]>([]);
  useEffect(() => {
    const poll = () =>
      api
        .sosAlerts()
        .then(setAlerts)
        .catch(() => undefined);
    void poll();
    const timer = setInterval(poll, 10000);
    return () => clearInterval(timer);
  }, []);
  if (alerts.length === 0) return null;
  const waiting = alerts.filter((a) => a.status === "active").length;
  return (
    <p className="banner bad" role="alert">
      <Siren size={18} /> SOS: {alerts.map((a) => a.driver_name).join(", ")}{" "}
      {waiting > 0 ? "needs help and nobody has answered yet." : "has an alert open."}{" "}
      <Link to="/incidents/sos">Open</Link>
    </p>
  );
}

function Notices({ docs, onDone }: { docs: PendingDocument[]; onDone: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function accept() {
    setBusy(true);
    setError(null);
    try {
      for (const d of docs) await api.acceptDocument(d);
      onDone();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop">
      <div
        className="card modal"
        role="dialog"
        aria-modal="true"
        aria-label="Please review and accept"
      >
        <h2>Please review and accept</h2>
        <ErrorBanner message={error} />
        <ul>
          {docs.map((d) => (
            <li key={d.document}>
              <strong>{DOC_TITLES[d.document] ?? d.document}</strong>{" "}
              <span className="muted">(version {d.version})</span>
              {DOC_SUMMARY[d.document] && <p>{DOC_SUMMARY[d.document]}</p>}
            </li>
          ))}
        </ul>
        <p className="muted">These documents are drafts pending legal review.</p>
        <button className="btn primary" onClick={accept} disabled={busy}>
          I have read and accept
        </button>
      </div>
    </div>
  );
}

export default function Layout() {
  const { me, can, signOut, reload } = useAuth();
  const nav = useNavigate();
  const [error, setError] = useState<string | null>(null);
  if (!me) return null;

  async function switchCompany(id: string) {
    setError(null);
    try {
      const res = await api.switchCompany(id);
      await reload();
      nav(res.mfa_setup_required ? "/two-factor" : "/", { replace: true });
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  const items = navItems.filter((n) =>
    n.platform
      ? me.is_platform_admin
      : (!n.permission || [n.permission].flat().some((p) => can(p))) &&
        (me.business !== null || n.path === "/settings"),
  );

  return (
    <div className="shell">
      <nav className="nav">
        <h1>FleetTms</h1>
        {me.companies.length > 1 ? (
          <label className="switcher">
            <Building size={16} />
            <select
              value={me.business?.id ?? ""}
              onChange={(e) => switchCompany(e.target.value)}
              aria-label="Company"
            >
              {me.companies.map((c) => (
                <option key={c.business_id} value={c.business_id}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <p className="company">
            <Building size={16} /> {me.business?.name}
          </p>
        )}
        {items.map(({ path, label, icon: Icon }) => (
          <NavLink
            key={path}
            to={path}
            end={path === "/"}
            className={({ isActive }) => (isActive ? "active" : "")}
          >
            <Icon size={18} /> {label}
          </NavLink>
        ))}
        <div className="spacer" />
        <p className="who">
          {me.user.name}
          <br />
          <span className="muted">{me.roles.map((r) => ROLE_LABELS[r]).join(", ")}</span>
        </p>
        <FeedbackButton />
        <a className="btn" href="/help" target="_blank" rel="noreferrer">
          <HelpCircle size={16} /> Help
        </a>
        <button className="btn" onClick={signOut}>
          <LogOut size={16} /> Sign out
        </button>
      </nav>
      <main className="main">
        <SubscriptionBanner />
        {me.permissions.includes("sos.respond") && <SosBanner />}
        <ErrorBanner message={error} />
        <Outlet />
      </main>
      {me.pending_documents.length > 0 && <Notices docs={me.pending_documents} onDone={reload} />}
    </div>
  );
}
