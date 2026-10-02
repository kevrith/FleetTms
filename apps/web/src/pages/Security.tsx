import type { SupportGrant } from "@fleettms/types";
import { LifeBuoy, LogOut, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

export default function Security() {
  const nav = useNavigate();
  const { me, can, reload } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [grants, setGrants] = useState<SupportGrant[]>([]);
  const [form, setForm] = useState({ hours: 2, reason: "" });

  const load = useCallback(async () => {
    if (!can("support.grant")) return;
    try {
      setGrants(await api.supportGrants());
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [can]);
  useEffect(() => {
    void load();
  }, [load]);

  async function signOutEverywhere() {
    if (!window.confirm("Sign out of every device where you are signed in?")) return;
    try {
      await api.logoutAll();
      await reload();
      nav("/login", { replace: true });
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  async function grant(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.grantSupport(form.hours, form.reason);
      setForm({ hours: 2, reason: "" });
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const active = grants.filter((g) => !g.revoked_at && new Date(g.expires_at) > new Date());

  return (
    <>
      <ErrorBanner message={error} />
      <Card title="Your sign-in">
        <p>
          <ShieldCheck size={18} /> Two-step verification:{" "}
          <strong>
            {me?.two_factor_enabled
              ? me.two_factor_method === "sms"
                ? "On (text message)"
                : "On (authenticator app)"
              : "Off"}
          </strong>
        </p>
        <button className="btn" onClick={signOutEverywhere}>
          <LogOut size={18} /> Sign out of all devices
        </button>
      </Card>
      {can("support.grant") && (
        <Card title="Support access">
          <p className="muted">
            FleetTms staff cannot see your business data unless you allow it. Access is read-only,
            expires on its own, and every visit is recorded in your audit trail.
          </p>
          <form onSubmit={grant} className="form-grid">
            <Field label="For how many hours (1 to 72)">
              <input
                type="number"
                min={1}
                max={72}
                value={form.hours}
                onChange={(e) => setForm({ ...form, hours: Number(e.target.value) })}
                required
              />
            </Field>
            <Field label="Why (so you remember later)">
              <input
                value={form.reason}
                onChange={(e) => setForm({ ...form, reason: e.target.value })}
                required
                minLength={3}
              />
            </Field>
            <button className="btn primary">
              <LifeBuoy size={18} /> Allow support access
            </button>
          </form>
          <ul className="list">
            {active.map((g) => (
              <li key={g.id}>
                <span>
                  {g.reason}{" "}
                  <span className="muted">
                    until{" "}
                    {new Date(g.expires_at).toLocaleString("en-KE", { timeZone: "Africa/Nairobi" })}
                  </span>
                </span>
                <button
                  className="btn danger"
                  onClick={async () => {
                    await api.revokeSupport(g.id);
                    await load();
                  }}
                >
                  Revoke now
                </button>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}
