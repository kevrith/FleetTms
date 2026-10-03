import type { SentMessage, StaffProfile } from "@fleettms/types";
import { Send } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { nairobiTime } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

/** Announcements and direct messages to drivers, with who has read each one. */
export default function Messages() {
  const [sent, setSent] = useState<SentMessage[]>([]);
  const [drivers, setDrivers] = useState<StaffProfile[]>([]);
  const [to, setTo] = useState<"all" | string[]>("all");
  const [body, setBody] = useState("");
  const [alsoSms, setAlsoSms] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setSent(await api.sentMessages());
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => {
    void load();
    api
      .staff()
      .then((s) =>
        setDrivers(
          s.filter(
            (p) => p.roles.some((r) => r === "driver" || r === "turnboy") && p.status !== "revoked",
          ),
        ),
      )
      .catch(() => undefined);
    const timer = setInterval(load, 30000);
    return () => clearInterval(timer);
  }, [load]);
  async function send(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setMessage(null);
    try {
      const m = await api.sendMessage({
        body,
        all_drivers: to === "all",
        membership_ids: to === "all" ? [] : to,
        also_sms: alsoSms,
      });
      setBody("");
      setMessage(`Sent to ${m.recipients} ${m.recipients === 1 ? "person" : "people"}.`);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }
  const choose = (id: string) =>
    setTo((cur) => {
      const list = cur === "all" ? [] : cur;
      const next = list.includes(id) ? list.filter((x) => x !== id) : [...list, id];
      return next.length === 0 ? "all" : next;
    });
  return (
    <>
      <h2>Driver messages</h2>
      <ErrorBanner message={error} />
      {message && (
        <p className="banner ok" role="status">
          {message}
        </p>
      )}
      <Card title="Send a message">
        <form className="form-grid" onSubmit={send}>
          <Field label="To">
            <select
              value={to === "all" ? "all" : "some"}
              onChange={(e) => setTo(e.target.value === "all" ? "all" : [])}
            >
              <option value="all">All my drivers</option>
              <option value="some">Chosen people</option>
            </select>
          </Field>
          {to !== "all" && (
            <fieldset>
              <legend>Who</legend>
              {drivers.map((d) => (
                <label key={d.membership_id} className="check">
                  <input
                    type="checkbox"
                    checked={to.includes(d.membership_id)}
                    onChange={() => choose(d.membership_id)}
                  />
                  <span>{d.name}</span>
                </label>
              ))}
            </fieldset>
          )}
          <Field label="Message">
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              rows={4}
              maxLength={2000}
              required
            />
          </Field>
          <label className="check">
            <input
              type="checkbox"
              checked={alsoSms}
              onChange={(e) => setAlsoSms(e.target.checked)}
            />
            <span>Also send a text message (for a driver not looking at the app)</span>
          </label>
          <button className="btn primary" type="submit" disabled={!body.trim()}>
            <Send size={16} /> Send
          </button>
        </form>
      </Card>
      <Card title="Sent">
        {sent.length === 0 && <p className="muted">Nothing sent yet.</p>}
        <ul className="list">
          {sent.map((m) => (
            <li key={m.id} style={{ display: "block" }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                <span>
                  <strong>{m.kind === "direct" ? "Direct" : "To everyone"}</strong> {m.body}
                </span>
                <span className="muted">{nairobiTime(m.created_at)}</span>
              </div>
              <button
                className="btn"
                type="button"
                onClick={() => setOpen(open === m.id ? null : m.id)}
              >
                Read by {m.read} of {m.recipients}
              </button>
              {open === m.id && (
                <ul className="list">
                  {m.receipts.map((r) => (
                    <li key={r.membership_id}>
                      <span>{r.name}</span>
                      <span className="muted">
                        {r.read_at ? `read ${nairobiTime(r.read_at)}` : "not read yet"}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      </Card>
    </>
  );
}
