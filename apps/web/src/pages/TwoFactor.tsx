import { MessageSquare, ShieldCheck, Smartphone } from "lucide-react";
import { QRCodeSVG } from "qrcode.react";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorBanner, errorMessage, Field } from "../ui";

type Method = "totp" | "sms";

export default function TwoFactor() {
  const nav = useNavigate();
  const { me, reload } = useAuth();
  const [method, setMethod] = useState<Method | null>(null);
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const hasPhone = Boolean(me?.user.phone);

  async function choose(next: Method) {
    setError(null);
    setCode("");
    try {
      if (next === "totp") setSetup(await api.twoFactorSetup());
      else await api.smsTwoFactorSetup();
      setMethod(next);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function confirm(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      if (method === "sms") await api.smsTwoFactorConfirm(code);
      else await api.twoFactorConfirm(code);
      await reload();
      nav("/", { replace: true });
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <main className="auth-page">
      <form className="card auth-card" onSubmit={confirm}>
        <h1>Set up two-step verification</h1>
        <p>
          Your role handles business money and staff, so we ask for a second code each time you sign
          in.
        </p>
        <ErrorBanner message={error} />
        {method === null && (
          <>
            <p className="actions">
              <button type="button" className="btn primary" onClick={() => choose("totp")}>
                <Smartphone size={18} /> Authenticator app
              </button>
              <button
                type="button"
                className="btn"
                onClick={() => choose("sms")}
                disabled={!hasPhone}
              >
                <MessageSquare size={18} /> Text message
              </button>
            </p>
            {!hasPhone && (
              <p className="muted">
                Text messages need a phone number on your account. Use an authenticator app, or ask
                your owner to add your number.
              </p>
            )}
          </>
        )}
        {method === "totp" && setup && (
          <>
            <ol>
              <li>
                Scan this code with an authenticator app (Google Authenticator, Microsoft
                Authenticator, Authy).
              </li>
              <li>Enter the 6-digit code it shows.</li>
            </ol>
            <div className="qr">
              <QRCodeSVG value={setup.otpauth_uri} size={180} />
            </div>
            <p className="muted">
              Can't scan? Enter this key by hand: <code>{setup.secret}</code>
            </p>
          </>
        )}
        {method === "sms" && <p>We texted a 6-digit code to your phone. Enter it below.</p>}
        {method !== null && (
          <>
            <Field label="6-digit code">
              <input
                value={code}
                onChange={(e) => setCode(e.target.value)}
                inputMode="numeric"
                maxLength={6}
                autoComplete="one-time-code"
                autoFocus
                required
              />
            </Field>
            <button className="btn primary">
              <ShieldCheck size={18} /> Turn on two-step verification
            </button>
            <button type="button" className="btn" onClick={() => setMethod(null)}>
              Choose a different method
            </button>
          </>
        )}
      </form>
    </main>
  );
}
