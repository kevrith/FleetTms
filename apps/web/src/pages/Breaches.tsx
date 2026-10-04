import type { BreachIncident, BreachSeverity, PlatformBusinessRow } from "@fleettms/types";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { nairobiTime } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

const SEVERITIES: BreachSeverity[] = ["low", "medium", "high", "critical"];

function Clock({ b }: { b: BreachIncident }) {
  if (!b.risk_to_people)
    return <span className="status ok">No one at risk: the Commissioner need not be told</span>;
  if (b.odpc_notified_at) {
    return (
      <span className={`status ${b.odpc_late ? "bad" : "ok"}`}>
        Commissioner told {nairobiTime(b.odpc_notified_at)}
        {b.odpc_late ? " (after the 72 hours)" : ""}
      </span>
    );
  }
  if (b.odpc_overdue)
    return <span className="status bad">Commissioner not told: the 72 hours have passed</span>;
  return (
    <span className="status warn">Tell the Commissioner within {b.odpc_hours_left} hours</span>
  );
}

/** The register of personal data breaches. The 72 hours for telling the Data Protection Commissioner run from the moment we became aware. */
export default function Breaches() {
  const [rows, setRows] = useState<BreachIncident[]>([]);
  const [businesses, setBusinesses] = useState<PlatformBusinessRow[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [text, setText] = useState<Record<string, string>>({});
  const [form, setForm] = useState({
    title: "",
    description: "",
    severity: "medium" as BreachSeverity,
    people: "",
    data: "",
    risk: true,
    affected: [] as string[],
  });

  const load = useCallback(async () => {
    try {
      const [b, c] = await Promise.all([api.breaches(), api.platformBusinesses()]);
      setRows(b);
      setBusinesses(c);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  async function act(work: () => Promise<unknown>, done: string) {
    setError(null);
    setMessage(null);
    try {
      await work();
      setMessage(done);
      await load();
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  async function record(e: FormEvent) {
    e.preventDefault();
    await act(
      () =>
        api.recordBreach({
          title: form.title,
          description: form.description,
          severity: form.severity,
          people_affected: form.people ? Number(form.people) : null,
          data_involved: form.data || null,
          risk_to_people: form.risk,
          businesses_affected: form.affected,
        }),
      "Written down. The 72 hours started when we became aware.",
    );
    setForm({ ...form, title: "", description: "", people: "", data: "", affected: [] });
  }
  return (
    <>
      <ErrorBanner message={error} />
      {message && <p className="banner ok">{message}</p>}
      <Card title="Data breaches">
        <p>
          Write a breach down the moment we become aware of it. If it is likely to put people at
          risk, the Data Protection Commissioner must be told within 72 hours, and the affected
          businesses without delay.
        </p>
        {rows.length === 0 && <p className="muted">None recorded.</p>}
        <ul className="list">
          {rows.map((b) => (
            <li key={b.id}>
              <span>
                <strong>{b.title}</strong> <span className="status warn">{b.severity}</span>{" "}
                <span className="muted">{b.status}</span>
                <br />
                <span className="muted">
                  Found {nairobiTime(b.discovered_at)}.{" "}
                  {b.people_affected !== null && `${b.people_affected} people. `}
                  {b.data_involved}
                </span>
                <br />
                {b.description}
                {b.root_cause && (
                  <>
                    <br />
                    <span className="muted">Cause: {b.root_cause}</span>
                  </>
                )}
              </span>
              <span>
                <Clock b={b} />
                <br />
                <span className="muted">
                  Businesses told:{" "}
                  {b.businesses_notified_at ? nairobiTime(b.businesses_notified_at) : "not yet"}.
                  People told:{" "}
                  {b.people_notified_at ? nairobiTime(b.people_notified_at) : "not yet"}.
                </span>
                <span className="actions">
                  {!b.odpc_notified_at && b.risk_to_people && (
                    <button
                      className="btn"
                      type="button"
                      onClick={() =>
                        act(
                          () => api.notifyBreach(b.id, "odpc"),
                          "Recorded: the Commissioner was told.",
                        )
                      }
                    >
                      The Commissioner has been told
                    </button>
                  )}
                  {!b.people_notified_at && (
                    <button
                      className="btn"
                      type="button"
                      onClick={() =>
                        act(
                          () => api.notifyBreach(b.id, "people"),
                          "Recorded: the people were told.",
                        )
                      }
                    >
                      The people have been told
                    </button>
                  )}
                  {b.status === "open" && (
                    <button
                      className="btn"
                      type="button"
                      onClick={() =>
                        act(
                          () => api.updateBreach(b.id, { status: "contained" }),
                          "Marked as contained.",
                        )
                      }
                    >
                      Contained
                    </button>
                  )}
                  {b.status !== "closed" && (
                    <button
                      className="btn"
                      type="button"
                      onClick={() =>
                        act(() => api.updateBreach(b.id, { status: "closed" }), "Closed.")
                      }
                    >
                      Close
                    </button>
                  )}
                </span>
                {b.businesses_affected.length > 0 && !b.businesses_notified_at && (
                  <span className="actions">
                    <input
                      aria-label="Message to the owners of the affected businesses"
                      placeholder="Message to their owners (a text)"
                      value={text[b.id] ?? ""}
                      onChange={(e) => setText({ ...text, [b.id]: e.target.value })}
                    />
                    <button
                      className="btn"
                      type="button"
                      disabled={(text[b.id] ?? "").trim().length < 10}
                      onClick={() =>
                        act(
                          () => api.notifyBreach(b.id, "businesses", text[b.id]),
                          "The owners were texted and their audit trails updated.",
                        )
                      }
                    >
                      Tell the businesses
                    </button>
                  </span>
                )}
              </span>
            </li>
          ))}
        </ul>
      </Card>
      <Card title="Write a breach down">
        <form onSubmit={record} className="form-grid">
          <Field label="What happened (short)">
            <input
              value={form.title}
              minLength={3}
              maxLength={200}
              required
              onChange={(e) => setForm({ ...form, title: e.target.value })}
            />
          </Field>
          <Field label="Details">
            <textarea
              value={form.description}
              minLength={10}
              maxLength={5000}
              required
              onChange={(e) => setForm({ ...form, description: e.target.value })}
            />
          </Field>
          <Field label="How serious">
            <select
              value={form.severity}
              onChange={(e) => setForm({ ...form, severity: e.target.value as BreachSeverity })}
            >
              {SEVERITIES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </Field>
          <Field label="How many people (if known)">
            <input
              type="number"
              min="0"
              value={form.people}
              onChange={(e) => setForm({ ...form, people: e.target.value })}
            />
          </Field>
          <Field label="What data was involved">
            <input
              value={form.data}
              maxLength={500}
              onChange={(e) => setForm({ ...form, data: e.target.value })}
            />
          </Field>
          <Field label="Businesses affected">
            <select
              multiple
              value={form.affected}
              onChange={(e) =>
                setForm({ ...form, affected: Array.from(e.target.selectedOptions, (o) => o.value) })
              }
            >
              {businesses.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </select>
          </Field>
          <label className="check">
            <input
              type="checkbox"
              checked={form.risk}
              onChange={(e) => setForm({ ...form, risk: e.target.checked })}
            />
            <span>
              Likely to put people at risk (the Commissioner must be told within 72 hours)
            </span>
          </label>
          <p className="actions">
            <button className="btn primary" type="submit">
              Write it down
            </button>
          </p>
        </form>
      </Card>
    </>
  );
}
