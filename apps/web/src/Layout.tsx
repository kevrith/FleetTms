import { ROLE_LABELS } from "@fleettms/business-rules";
import type { PendingDocument } from "@fleettms/types";
import { Building, LogOut } from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { api } from "./api";
import { useAuth } from "./auth";
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
    "FleetTms records your location during active trips, your odometer photos, fuel and expense entries. " +
    "This is used for work purposes only, stops when your trip ends, and is visible to your employer.",
};

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

  const items = navItems.filter((n) => !n.permission || can(n.permission));

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
        <button className="btn" onClick={signOut}>
          <LogOut size={16} /> Sign out
        </button>
      </nav>
      <main className="main">
        <ErrorBanner message={error} />
        <Outlet />
      </main>
      {me.pending_documents.length > 0 && <Notices docs={me.pending_documents} onDone={reload} />}
    </div>
  );
}
