import type { AskAnswer, AskExample, ReportData } from "@fleettms/types";
import { MessageCircleQuestion } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

const cell = (v: string | number | null) =>
  v === null ? "" : typeof v === "number" ? v.toLocaleString("en-KE") : v;

function Tables({ report }: { report: Pick<ReportData, "title" | "notes" | "sections"> }) {
  return (
    <>
      {report.sections.map((s) => (
        <div key={s.title}>
          <h4>{s.title}</h4>
          {s.rows.length === 0 ? (
            <p className="muted">Nothing found.</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    {s.columns.map((c) => (
                      <th key={c}>{c}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {s.rows.map((row, i) => (
                    <tr key={i}>
                      {row.map((v, j) => (
                        <td key={j}>{cell(v)}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ))}
      {report.notes.map((n) => (
        <p key={n} className="muted">
          {n}
        </p>
      ))}
    </>
  );
}

/** Ask a question in plain English. The answer comes with the figures it is built from, so it can always be checked. */
export default function Ask() {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<AskAnswer | null>(null);
  const [direct, setDirect] = useState<{ question: string; report: ReportData } | null>(null);
  const [examples, setExamples] = useState<AskExample[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api
      .askExamples()
      .then(setExamples)
      .catch((e) => setError(errorMessage(e)));
  }, []);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setDirect(null);
    try {
      setAnswer(await api.ask(question));
    } catch (err) {
      setAnswer(null);
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }
  async function runExample(x: AskExample) {
    setBusy(true);
    setError(null);
    setAnswer(null);
    try {
      setDirect({ question: x.question, report: await api.askLookup(x.lookup, x.args) });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <h2>
        <MessageCircleQuestion size={20} /> Ask a question
      </h2>
      <ErrorBanner message={error} />
      <Card title="Ask in plain English">
        <form className="form-grid" onSubmit={submit}>
          <Field label="Your question">
            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              minLength={3}
              maxLength={500}
              placeholder="Which lorry had the highest cost per km last month?"
              required
            />
          </Field>
          <button
            className="btn primary"
            type="submit"
            disabled={busy || question.trim().length < 3}
          >
            Ask
          </button>
        </form>
        <p className="muted">
          Answers come only from your own figures, shown below the answer. The assistant cannot
          change anything.
        </p>
        {examples.length > 0 && (
          <>
            <h4>Or try one of these (no waiting for an assistant)</h4>
            <ul className="list">
              {examples.map((x) => (
                <li key={x.question}>
                  <button
                    className="btn"
                    type="button"
                    disabled={busy}
                    onClick={() => runExample(x)}
                  >
                    {x.question}
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
      </Card>
      {answer && (
        <Card title="Answer">
          <p>
            <strong>{answer.answer}</strong>
          </p>
          <p className="muted">
            Looked up:{" "}
            {answer.lookups
              .map((l) => l.lookup.replace("report_", "").replace(/_/g, " "))
              .join(", ") || "nothing"}
            .
          </p>
          {answer.tables.map((t, i) => (
            <Tables key={i} report={t} />
          ))}
        </Card>
      )}
      {direct && (
        <Card title={direct.question}>
          <Tables report={direct.report} />
        </Card>
      )}
    </>
  );
}
