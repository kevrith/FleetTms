import type {
  DataRequestKind,
  DataRequestSummary,
  DataSubjectRequest,
  StaffProfile,
} from "@fleettms/types";
import { Download } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { nairobiTime } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";
import { KIND_LABEL, STATE_LABEL } from "./MyData";

/** The owner answers the data protection requests of the business's own people. The clock runs from the day a request is made. */
export default function PrivacyRequests() {
  const [rows, setRows] = useState<DataSubjectRequest[]>([]);
  const [summary, setSummary] = useState<DataRequestSummary | null>(null);
  const [staff, setStaff] = useState<StaffProfile[]>([]);
  const [text, setText] = useState<Record<string, string>>({});
  const [log, setLog] = useState<{ membership: string; kind: DataRequestKind; details: string }>({
    membership: "",
    kind: "access",
    details: "",
  });
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [r, s, p] = await Promise.all([
        api.dataRequests(),
        api.dataRequestSummary(),
        api.staff(),
      ]);
      setRows(r);
      setSummary(s);
      setStaff(p);
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
  async function download(r: DataSubjectRequest) {
    setError(null);
    try {
      const url = URL.createObjectURL(await api.dataRequestFile(r.id));
      const a = document.createElement("a");
      a.href = url;
      a.download = `personal-data-${(r.person ?? "person").replace(/\W+/g, "-").toLowerCase()}.zip`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  async function record(e: FormEvent) {
    e.preventDefault();
    await act(
      () => api.logDataRequest(log.membership, log.kind, log.details.trim() || undefined),
      "Request recorded. The clock has started.",
    );
    setLog({ ...log, details: "" });
  }
  const note = (id: string) => text[id]?.trim() ?? "";
  return (
    <>
      <ErrorBanner message={error} />
      {message && <p className="banner ok">{message}</p>}
      <Card title="Privacy requests">
        <p>
          Your people can ask what you hold about them, to correct it, to take it away, or to stop
          using it. You are the one who answers, within {summary?.answer_within_days ?? 30} days. A
          copy of everything held about a person is one click, and removing someone keeps what they
          did (trips, fuel, expenses) as your business records under an anonymous name.{" "}
          {summary && (
            <strong>
              {summary.open} waiting, {summary.overdue} overdue.
            </strong>
          )}
        </p>
        {rows.length === 0 && <p className="muted">No requests yet.</p>}
        <ul className="list">
          {rows.map((r) => (
            <li key={r.id}>
              <span>
                <strong>{r.person ?? "Someone who has left"}</strong>: {KIND_LABEL[r.kind]}
                <span className="muted"> sent {nairobiTime(r.created_at)}. </span>
                {r.details && <span className="muted">"{r.details}" </span>}
                {r.resolution && <span className="muted">Answer: {r.resolution}</span>}
              </span>
              <span>
                <span
                  className={`status ${r.status === "completed" ? "ok" : r.status === "refused" || r.overdue ? "bad" : "warn"}`}
                >
                  {STATE_LABEL[r.status]}
                  {r.status === "open" &&
                    (r.overdue
                      ? ` (overdue by ${-(r.days_left ?? 0)} days)`
                      : ` (due ${r.due_on})`)}
                </span>
                {r.status === "open" && (
                  <span className="actions">
                    <button className="btn" type="button" onClick={() => download(r)}>
                      <Download size={16} /> Copy of their data
                    </button>
                    {r.kind === "delete" && (
                      <button
                        className="btn"
                        type="button"
                        onClick={() =>
                          window.confirm(
                            "Remove this person? Their staff details are deleted and they become anonymous. This cannot be undone.",
                          ) && act(() => api.applyDeletion(r.id), "The person has been removed.")
                        }
                      >
                        Remove the person
                      </button>
                    )}
                    <input
                      aria-label="Your answer or reason"
                      placeholder="What you did, or why not"
                      value={text[r.id] ?? ""}
                      onChange={(e) => setText({ ...text, [r.id]: e.target.value })}
                    />
                    <button
                      className="btn"
                      type="button"
                      disabled={note(r.id).length < 3}
                      onClick={() =>
                        act(() => api.completeDataRequest(r.id, note(r.id)), "Marked as answered.")
                      }
                    >
                      Mark as answered
                    </button>
                    <button
                      className="btn"
                      type="button"
                      disabled={note(r.id).length < 10}
                      onClick={() =>
                        act(
                          () => api.refuseDataRequest(r.id, note(r.id)),
                          "Refused, with your reason.",
                        )
                      }
                    >
                      Refuse (needs a reason)
                    </button>
                  </span>
                )}
              </span>
            </li>
          ))}
        </ul>
      </Card>
      <Card title="Record a request someone made in person">
        <form onSubmit={record} className="form-grid">
          <Field label="Who is it about?">
            <select
              value={log.membership}
              onChange={(e) => setLog({ ...log, membership: e.target.value })}
              required
            >
              <option value="">Choose</option>
              {staff.map((s) => (
                <option key={s.membership_id} value={s.membership_id}>
                  {s.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="What do they want?">
            <select
              value={log.kind}
              onChange={(e) => setLog({ ...log, kind: e.target.value as DataRequestKind })}
            >
              {Object.entries(KIND_LABEL).map(([k, label]) => (
                <option key={k} value={k}>
                  {label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="What they said (optional)">
            <input
              value={log.details}
              maxLength={2000}
              onChange={(e) => setLog({ ...log, details: e.target.value })}
            />
          </Field>
          <p className="actions">
            <button className="btn primary" type="submit" disabled={!log.membership}>
              Record it
            </button>
          </p>
        </form>
      </Card>
    </>
  );
}
