import { UserPlus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorBanner, errorMessage, Field } from "../ui";

export default function Signup() {
  const nav = useNavigate();
  const { reload } = useAuth();
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

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.signup({
        ...form,
        phone: form.phone || null,
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
    <main className="auth-page">
      <form className="card auth-card" onSubmit={submit}>
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
    </main>
  );
}
