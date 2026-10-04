import type { DataRequestKind, DataSubjectRequest } from "@fleettms/types";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { nairobiTime } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

export const KIND_LABEL: Record<DataRequestKind, string> = {
  access: "See what you hold about me",
  portability: "Give me a copy I can take elsewhere",
  correct: "Correct something that is wrong",
  delete: "Delete my data",
  object: "Stop using my data in a way I object to",
};

export const STATE_LABEL: Record<string, string> = {
  open: "Waiting for an answer",
  completed: "Answered",
  refused: "Refused, with a reason",
};

/** Anyone signed in can ask their employer what is held about them, have it corrected or removed, and see how the request is going. */
export default function MyDataCard() {
  const [rows, setRows] = useState<DataSubjectRequest[]>([]);
  const [kind, setKind] = useState<DataRequestKind>("access");
  const [details, setDetails] = useState("");
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setRows(await api.myDataRequests());
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.askAboutMyData(kind, details.trim() || undefined);
      setDetails("");
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }
  return (
    <Card title="Your data and your rights">
      <ErrorBanner message={error} />
      <p>
        Your employer decides how the information about you in FleetTms is used, and FleetTms keeps
        it safe on their behalf. You can ask them what is held about you, to correct it, to take it
        away, or to stop using it in a way you object to. They must answer, and give you a reason if
        they cannot do what you ask.
      </p>
      <form onSubmit={submit} className="form-grid">
        <Field label="What do you want?">
          <select value={kind} onChange={(e) => setKind(e.target.value as DataRequestKind)}>
            {Object.entries(KIND_LABEL).map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Anything they should know (optional)">
          <textarea value={details} maxLength={2000} onChange={(e) => setDetails(e.target.value)} />
        </Field>
        <p className="actions">
          <button className="btn primary" type="submit">
            Send the request
          </button>
        </p>
      </form>
      {rows.length > 0 && (
        <ul className="list">
          {rows.map((r) => (
            <li key={r.id}>
              <span>
                {KIND_LABEL[r.kind]} <span className="muted">sent {nairobiTime(r.created_at)}</span>
                {r.resolution && <span className="muted"> Answer: {r.resolution}</span>}
              </span>
              <span
                className={`status ${r.status === "completed" ? "ok" : r.status === "refused" ? "bad" : "warn"}`}
              >
                {STATE_LABEL[r.status]}
                {r.status === "open" && ` (answer due ${r.due_on})`}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
