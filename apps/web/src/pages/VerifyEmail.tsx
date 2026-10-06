import { CheckCircle2, LogOut, Mail, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, Navigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorBanner, errorMessage } from "../ui";
import PublicShell from "./PublicShell";

/** Two jobs: the page the emailed link opens (with ?token=), and the "check your inbox" page a signed-in person waits on until they have done that. */
export default function VerifyEmail() {
  const [params] = useSearchParams();
  const token = params.get("token");
  const { me, loading, reload, signOut } = useAuth();
  const [state, setState] = useState<"working" | "confirmed" | "failed">("working");
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  useEffect(() => {
    if (!token) return;
    api
      .verifyEmail(token)
      .then(async () => {
        await reload();
        setState("confirmed");
      })
      .catch((err) => {
        setError(errorMessage(err));
        setState("failed");
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  async function resend() {
    setError(null);
    setSent(false);
    try {
      await api.resendEmailVerification();
      setSent(true);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  if (!token) {
    if (loading) return <p className="main">Loading...</p>;
    if (!me) return <Navigate to="/login" replace />;
    if (!me.email_verification_pending) return <Navigate to="/" replace />;
    return (
      <PublicShell layout="form">
        <div className="card auth-card">
          <img className="auth-logo" src="/logo.png" alt="FleetTms" width={64} height={64} />
          <h1>Check your email</h1>
          <p>
            We sent a link to <strong>{me.user.email}</strong>. Open it to confirm that this address
            is yours, then come back here.
          </p>
          <ErrorBanner message={error} />
          {sent && <p className="status ok">A new link is on its way.</p>}
          <button className="btn primary" onClick={() => void reload()}>
            <CheckCircle2 size={18} /> I have confirmed it
          </button>
          <button className="btn" onClick={() => void resend()}>
            <RefreshCw size={18} /> Send the link again
          </button>
          <button className="btn" onClick={() => void signOut()}>
            <LogOut size={18} /> Sign out
          </button>
          <p className="muted">
            Wrong address? Sign out and create the account again with the right one.
          </p>
        </div>
      </PublicShell>
    );
  }

  return (
    <PublicShell layout="form">
      <div className="card auth-card">
        <img className="auth-logo" src="/logo.png" alt="FleetTms" width={64} height={64} />
        <h1>Confirm your email</h1>
        {state === "working" && (
          <p>
            <Mail size={16} /> Confirming...
          </p>
        )}
        {state === "confirmed" && (
          <>
            <p className="status ok">Your email address is confirmed.</p>
            <Link className="btn primary" to={me ? "/" : "/login"}>
              {me ? "Continue" : "Sign in"}
            </Link>
          </>
        )}
        {state === "failed" && (
          <>
            <ErrorBanner message={error} />
            <Link className="btn" to="/login">
              Sign in to get a new link
            </Link>
          </>
        )}
      </div>
    </PublicShell>
  );
}
