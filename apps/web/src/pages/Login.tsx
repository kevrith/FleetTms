import { ApiError } from "@fleettms/api-client";
import { Download, LogIn } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { ANDROID_APP_URL } from "../appLinks";
import { useAuth } from "../auth";
import { ErrorBanner, errorMessage, Field } from "../ui";
import GoogleButton from "./GoogleButton";
import PublicShell from "./PublicShell";

export default function Login() {
  const nav = useNavigate();
  const { reload } = useAuth();
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [step, setStep] = useState<null | "totp" | "sms">(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Set once Google has vouched for the person but their account also wants a second step: the code is sent along with the same token.
  const [googleToken, setGoogleToken] = useState<string | null>(null);

  async function attempt(run: () => Promise<{ mfa_setup_required: boolean }>, google?: string) {
    setBusy(true);
    setError(null);
    try {
      const res = await run();
      await reload();
      nav(res.mfa_setup_required ? "/two-factor" : "/", { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.code === "two_factor_required") {
        setGoogleToken(google ?? googleToken);
        setStep("totp");
      } else if (err instanceof ApiError && err.code === "sms_code_required") {
        setGoogleToken(google ?? googleToken);
        setStep("sms");
        setCode("");
        setError(err.message);
      } else {
        setError(errorMessage(err));
      }
    } finally {
      setBusy(false);
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    const second = {
      totp_code: step === "totp" ? code : undefined,
      sms_code: step === "sms" ? code : undefined,
    };
    void attempt(() =>
      googleToken
        ? api.googleAuth({ credential: googleToken, ...second })
        : api.login({ identifier, password, ...second }),
    );
  }

  function signInWithGoogle(credential: string) {
    setStep(null);
    setCode("");
    void attempt(() => api.googleAuth({ credential }), credential);
  }

  return (
    <PublicShell layout="form">
      <form className="card auth-card" onSubmit={submit}>
        <img className="auth-logo" src="/logo.png" alt="FleetTms" width={64} height={64} />
        <h1>Sign in to FleetTms</h1>
        <ErrorBanner message={error} />
        {!googleToken && (
          <>
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
          </>
        )}
        {step && (
          <Field
            label={
              step === "sms"
                ? "6-digit code we texted you"
                : "6-digit code from your authenticator app"
            }
          >
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
          <LogIn size={18} /> {step ? "Verify and sign in" : "Sign in"}
        </button>
        {!googleToken && <GoogleButton mode="signin" onCredential={signInWithGoogle} />}
        <p className="muted">
          New to FleetTms? <Link to="/signup">Create your business account</Link>
        </p>
        <p className="muted">
          <a href={ANDROID_APP_URL}>
            <Download size={14} /> Get the Android app
          </a>{" "}
          for drivers and owners on the road.
        </p>
      </form>
    </PublicShell>
  );
}
