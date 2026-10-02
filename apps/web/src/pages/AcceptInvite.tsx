import { KeyRound } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { ErrorBanner, errorMessage, Field } from "../ui";

export default function AcceptInvite() {
  const [params] = useSearchParams();
  const [password, setPassword] = useState("");
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.acceptInvite(params.get("token") ?? "", password);
      setDone(true);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <main className="auth-page">
      <form className="card auth-card" onSubmit={submit}>
        <h1>Welcome to FleetTms</h1>
        {done ? (
          <p>
            Your password is set. <Link to="/login">Sign in</Link>
          </p>
        ) : (
          <>
            <p>Choose a password to finish setting up your account.</p>
            <ErrorBanner message={error} />
            <Field label="Password (at least 10 characters)">
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                minLength={10}
                required
                autoComplete="new-password"
              />
            </Field>
            <button className="btn primary">
              <KeyRound size={18} /> Set password
            </button>
          </>
        )}
      </form>
    </main>
  );
}
