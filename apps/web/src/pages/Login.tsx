import { ApiError } from "@fleettms/api-client";
import { LogIn } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorBanner, errorMessage, Field } from "../ui";

export default function Login() {
  const nav = useNavigate();
  const { reload } = useAuth();
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [needsCode, setNeedsCode] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await api.login({
        identifier,
        password,
        totp_code: needsCode ? code : undefined,
      });
      await reload();
      nav(res.mfa_setup_required ? "/two-factor" : "/", { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.code === "two_factor_required") {
        setNeedsCode(true);
      } else {
        setError(errorMessage(err));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-page">
      <form className="card auth-card" onSubmit={submit}>
        <h1>Sign in to FleetTms</h1>
        <ErrorBanner message={error} />
        <Field label="Email or phone number">
          <input
            value={identifier}
            onChange={(e) => setIdentifier(e.target.value)}
            autoComplete="username"
            required
          />
        </Field>
        <Field label="Password">
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </Field>
        {needsCode && (
          <Field label="6-digit code from your authenticator app">
            <input
              value={code}
              onChange={(e) => setCode(e.target.value)}
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              autoFocus
              required
            />
          </Field>
        )}
        <button className="btn primary" disabled={busy}>
          <LogIn size={18} /> {needsCode ? "Verify and sign in" : "Sign in"}
        </button>
        <p className="muted">
          New to FleetTms? <Link to="/signup">Create your business account</Link>
        </p>
      </form>
    </main>
  );
}
