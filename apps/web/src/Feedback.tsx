import { MessageSquarePlus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useLocation } from "react-router-dom";
import { api } from "./api";
import { ErrorBanner, errorMessage, Field } from "./ui";

/** The beta feedback button: tell us what is wrong, what is missing or what you like, from wherever you are in the app. */
export function FeedbackButton() {
  const here = useLocation();
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<"problem" | "idea" | "praise">("problem");
  const [text, setText] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function send(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.sendFeedback({ kind, message: text.trim(), page: here.pathname, app: "web" });
      setSent(true);
      setText("");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }
  function close() {
    setOpen(false);
    setSent(false);
    setError(null);
  }
  return (
    <>
      <button className="btn" type="button" onClick={() => setOpen(true)}>
        <MessageSquarePlus size={16} /> Send feedback
      </button>
      {open && (
        <div className="modal-backdrop">
          <div className="card modal" role="dialog" aria-modal="true" aria-label="Send feedback">
            <h2>Send feedback</h2>
            {sent ? (
              <>
                <p className="banner ok" role="status">
                  Thank you. We read every one.
                </p>
                <button className="btn" type="button" onClick={close}>
                  Close
                </button>
              </>
            ) : (
              <form className="form-grid" onSubmit={send}>
                <ErrorBanner message={error} />
                <Field label="What is it?">
                  <select value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
                    <option value="problem">Something is wrong</option>
                    <option value="idea">Something is missing</option>
                    <option value="praise">Something works well</option>
                  </select>
                </Field>
                <Field label="Tell us more">
                  <textarea
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    rows={5}
                    minLength={3}
                    maxLength={2000}
                    required
                  />
                </Field>
                <p className="muted">We note which page you were on ({here.pathname}).</p>
                <p className="actions">
                  <button
                    className="btn primary"
                    type="submit"
                    disabled={busy || text.trim().length < 3}
                  >
                    Send
                  </button>
                  <button className="btn" type="button" onClick={close}>
                    Cancel
                  </button>
                </p>
              </form>
            )}
          </div>
        </div>
      )}
    </>
  );
}
