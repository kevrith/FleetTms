import { UserPlus } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorBanner, errorMessage, Field } from "../ui";
import PublicShell from "./PublicShell";

export default function Signup() {
  const nav = useNavigate();
  const [params] = useSearchParams();
  const { reload } = useAuth();
  const [referral, setReferral] = useState(params.get("ref") ?? "");
  const [partnerName, setPartnerName] = useState<string | null>(null);
  const [form, setForm] = useState({
    business_name: "",
    name: "",
    email: "",
    phone: "",
    password: "",
  });
  const [accepted, setAccepted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm({ ...form, [k]: e.target.value });

  async function checkCode() {
    setPartnerName(null);
    if (referral.trim().length < 4) return;
    try {
      setPartnerName((await api.partnerCodeOwner(referral.trim())).partner);
    } catch {
      /* an unknown code is simply not used */
    }
  }
  useEffect(() => {
    void checkCode();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.signup({
        ...form,
        phone: form.phone || null,
        referral_code: referral.trim() || null,
        accept_terms: accepted,
        accept_privacy: accepted,
        accept_dpa: accepted,
      });
      await reload();
      nav("/two-factor", { replace: true });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <PublicShell layout="form">
      <form className="card auth-card" onSubmit={submit}>
        <img className="auth-logo" src="/logo.png" alt="FleetTms" width={64} height={64} />
        <h1>Create your business account</h1>
        <ErrorBanner message={error} />
        <Field label="Business name">
          <input
            value={form.business_name}
            onChange={set("business_name")}
            required
            minLength={2}
          />
        </Field>
        <Field label="Your name">
          <input
            value={form.name}
            onChange={set("name")}
            required
            minLength={2}
            autoComplete="name"
          />
        </Field>
        <Field label="Email">
          <input
            type="email"
            value={form.email}
            onChange={set("email")}
            required
            autoComplete="email"
          />
        </Field>
        <Field label="Phone (optional)">
          <input
            value={form.phone}
            onChange={set("phone")}
            inputMode="tel"
            placeholder="0712 345 678"
            autoComplete="tel"
          />
        </Field>
        <Field label="Partner code (only if someone sent you)">
          <input
            value={referral}
            onChange={(e) => setReferral(e.target.value)}
            onBlur={checkCode}
            maxLength={20}
            autoCapitalize="characters"
          />
        </Field>
        {partnerName && <p className="status ok">Thank you for coming through {partnerName}.</p>}
        <Field label="Password (at least 10 characters)">
          <input
            type="password"
            value={form.password}
            onChange={set("password")}
            required
            minLength={10}
            autoComplete="new-password"
          />
        </Field>
        <label className="check">
          <input
            type="checkbox"
            checked={accepted}
            onChange={(e) => setAccepted(e.target.checked)}
          />
          <span>
            I accept the Terms of Service, the Privacy Policy and the Data Processing Agreement for
            my business.
          </span>
        </label>
        <button className="btn primary" disabled={busy || !accepted}>
          <UserPlus size={18} /> Create account
        </button>
        <p className="muted">
          Already have an account? <Link to="/login">Sign in</Link>
        </p>
      </form>
    </PublicShell>
  );
}
