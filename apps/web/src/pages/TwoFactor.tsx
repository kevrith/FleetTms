import { ShieldCheck } from "lucide-react";
import { QRCodeSVG } from "qrcode.react";
import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorBanner, errorMessage, Field } from "../ui";

export default function TwoFactor() {
  const nav = useNavigate();
  const { me, reload } = useAuth();
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (me?.two_factor_enabled) return;
    api
      .twoFactorSetup()
      .then(setSetup)
      .catch((e) => setError(errorMessage(e)));
  }, [me?.two_factor_enabled]);

  async function confirm(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.twoFactorConfirm(code);
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
          Your role handles business money and staff, so we ask for a code from an authenticator app
          (Google Authenticator, Microsoft Authenticator, Authy) each time you sign in.
        </p>
        <ErrorBanner message={error} />
        {setup && (
          <>
            <ol>
              <li>Scan this code with your authenticator app.</li>
              <li>Enter the 6-digit code it shows.</li>
            </ol>
            <div className="qr">
              <QRCodeSVG value={setup.otpauth_uri} size={180} />
            </div>
            <p className="muted">
              Can't scan? Enter this key by hand: <code>{setup.secret}</code>
            </p>
            <Field label="6-digit code">
              <input
                value={code}
                onChange={(e) => setCode(e.target.value)}
                inputMode="numeric"
                maxLength={6}
                autoComplete="one-time-code"
                required
              />
            </Field>
            <button className="btn primary">
              <ShieldCheck size={18} /> Turn on two-step verification
            </button>
          </>
        )}
      </form>
    </main>
  );
}
