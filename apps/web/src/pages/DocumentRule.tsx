import type { DocumentRule as Rule } from "@fleettms/types";
import { useEffect, useState } from "react";
import { api } from "../api";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

const MODES: { value: Rule["mode"]; label: string; help: string }[] = [
  {
    value: "off",
    label: "Off",
    help: "Nothing is checked or said when a trip is made or started.",
  },
  {
    value: "warn",
    label: "Warn",
    help: "The trip and the driver's phone say what has run out or is not recorded, but the trip can still start.",
  },
  {
    value: "block",
    label: "Block",
    help: "A trip cannot start while a required document has run out or is not recorded. Only the owner can allow one trip, with a reason.",
  },
];

/** Whether a trip may start with an expired driving licence or insurance, and which documents count. */
export default function DocumentRulePage() {
  const [rule, setRule] = useState<Rule | null>(null);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api
      .documentRule()
      .then(setRule)
      .catch((e) => setError(errorMessage(e)));
  }, []);
  if (!rule) return <ErrorBanner message={error} />;

  async function save(next: Pick<Rule, "mode" | "required">) {
    setError(null);
    setSaved(false);
    try {
      setRule(await api.saveDocumentRule(next));
      setSaved(true);
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  const toggle = (doc: string) =>
    save({
      mode: rule.mode,
      required: rule.required.includes(doc)
        ? rule.required.filter((d) => d !== doc)
        : [...rule.required, doc],
    });

  return (
    <>
      <ErrorBanner message={error} />
      <Card title="Expired documents and trips">
        <p className="muted">
          A document is valid through its expiry date and counts as run out from the next day. The
          driver, the owner and the managers are already reminded before a document runs out. Here
          you choose what happens when one has.
        </p>
        <div className="form-grid">
          <Field label="When a required document has run out">
            <select
              value={rule.mode}
              onChange={(e) =>
                save({ mode: e.target.value as Rule["mode"], required: rule.required })
              }
            >
              {MODES.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <p className="muted">{MODES.find((m) => m.value === rule.mode)?.help}</p>
        {rule.mode === "block" && (
          <p className="status warn">
            A driver with no licence on record, or a lorry with no insurance on record, is also
            stopped. Record them first (Vehicles, and People for licences) before you switch this
            on.
          </p>
        )}
      </Card>
      <Card title="Documents that count">
        <ul className="list">
          {rule.options.map((o) => (
            <li key={o.doc_type}>
              <label>
                <input
                  type="checkbox"
                  checked={rule.required.includes(o.doc_type)}
                  onChange={() => toggle(o.doc_type)}
                />{" "}
                {o.label}
              </label>
              <span className="muted">
                {o.subject === "driver" ? "the driver's" : "the lorry's"}
              </span>
            </li>
          ))}
        </ul>
        {saved && <p className="status ok">Saved.</p>}
      </Card>
    </>
  );
}
