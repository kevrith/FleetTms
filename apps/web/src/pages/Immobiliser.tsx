import type { ImmobiliserCommand, ImmobiliserState } from "@fleettms/types";
import { OctagonX, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { IMMOBILISER_STATUS, nairobiTime } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

/**
 * Stop a vehicle's engine, or let it start again. Two steps on purpose: a request with a reason, then the number plate and the
 * owner's password. The server checks again that the vehicle is standing, so a lorry on the road is never stopped.
 */
export function ImmobiliserCard({ vehicleId }: { vehicleId: string }) {
  const { can } = useAuth();
  const [state, setState] = useState<ImmobiliserState | null>(null);
  const [action, setAction] = useState<"immobilise" | "release" | null>(null);
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState<ImmobiliserCommand | null>(null);
  const [registration, setRegistration] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const allowed = can("immobiliser.use");
  const load = useCallback(async () => {
    if (!allowed) return;
    try {
      setState(await api.immobiliserState(vehicleId));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [vehicleId, allowed]);
  useEffect(() => {
    void load();
  }, [load]);
  if (!allowed || !state?.has_tracker) return null;

  function reset() {
    setAction(null);
    setPending(null);
    setReason("");
    setRegistration("");
    setPassword("");
  }
  async function request(e: FormEvent) {
    e.preventDefault();
    if (!action) return;
    setError(null);
    setMessage(null);
    try {
      setPending(await api.requestImmobiliser(vehicleId, { action, reason }));
    } catch (err) {
      setError(errorMessage(err));
      await load();
    }
  }
  async function confirm(e: FormEvent) {
    e.preventDefault();
    if (!pending) return;
    setError(null);
    try {
      const done = await api.confirmImmobiliser(pending.id, { registration, password });
      setMessage(
        done.action === "immobilise"
          ? "The stop command was sent to the tracker. The engine is shown as stopped when the tracker confirms."
          : "The release command was sent to the tracker.",
      );
      reset();
    } catch (err) {
      setError(errorMessage(err));
      setPassword("");
    }
    await load();
  }
  async function cancel() {
    if (pending) await api.cancelImmobiliser(pending.id).catch(() => undefined);
    reset();
    await load();
  }
  return (
    <Card title="Engine immobiliser">
      <ErrorBanner message={error} />
      {message && (
        <p className="banner ok" role="status">
          {message}
        </p>
      )}
      <p>
        {state.immobilised ? (
          <span className="status bad">Engine stopped</span>
        ) : (
          <span className="status ok">Engine free to run</span>
        )}{" "}
        <span className="muted">
          {state.can_immobilise
            ? "The vehicle is standing, so the engine can be stopped."
            : (state.message ?? "")}
        </span>
      </p>
      {!action && (
        <p className="actions">
          <button
            className="btn"
            type="button"
            disabled={!state.can_immobilise}
            onClick={() => setAction("immobilise")}
          >
            <OctagonX size={16} /> Stop the engine
          </button>
          {state.immobilised && (
            <button className="btn" type="button" onClick={() => setAction("release")}>
              <ShieldCheck size={16} /> Let it start again
            </button>
          )}
        </p>
      )}
      {action && !pending && (
        <form className="form-grid" onSubmit={request}>
          <Field label={action === "immobilise" ? "Why stop this engine?" : "Why release it?"}>
            <input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              required
              minLength={3}
              maxLength={255}
            />
          </Field>
          <p className="actions">
            <button className="btn primary" type="submit">
              Continue
            </button>
            <button className="btn" type="button" onClick={reset}>
              Cancel
            </button>
          </p>
        </form>
      )}
      {pending && (
        <form className="form-grid" onSubmit={confirm}>
          <p className="banner bad">
            {pending.action === "immobilise"
              ? `This will stop the engine of ${state.registration}. It cannot be started again until you release it here. Type the number plate and your password to confirm. The request expires at ${nairobiTime(pending.expires_at)}.`
              : `This will let ${state.registration} start again. Type the number plate and your password to confirm.`}
          </p>
          <Field label="Number plate">
            <input
              value={registration}
              onChange={(e) => setRegistration(e.target.value)}
              required
              autoComplete="off"
            />
          </Field>
          <Field label="Your password">
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="current-password"
            />
          </Field>
          <p className="actions">
            <button className="btn primary" type="submit">
              Confirm
            </button>
            <button className="btn" type="button" onClick={cancel}>
              Cancel request
            </button>
          </p>
        </form>
      )}
      {state.history.length > 0 && (
        <>
          <h4>Recent requests</h4>
          <ul className="list">
            {state.history.slice(0, 6).map((c) => (
              <li key={c.id}>
                <span>
                  {c.action === "immobilise" ? "Stop engine" : "Release"}: {c.reason}
                </span>
                <span className="muted">
                  {IMMOBILISER_STATUS[c.status] ?? c.status}, {nairobiTime(c.requested_at)}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </Card>
  );
}
