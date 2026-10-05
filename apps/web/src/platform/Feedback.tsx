import type { PlatformFeedbackItem } from "@fleettms/types";
import { useState } from "react";
import { api } from "../api";
import { ErrorBanner } from "../ui";
import { dateTime } from "./format";
import { Badge, Chips, Empty, FormDialog, FormField, Page, Panel, useLoad, useToast } from "./kit";

const KIND = {
  problem: ["Problem", "bad"],
  idea: ["Idea", "info"],
  praise: ["Praise", "ok"],
} as const;
const STATUS = {
  new: ["New", "warn"],
  read: ["Read", "info"],
  resolved: ["Resolved", "ok"],
} as const;

/** What customers send from the feedback button: read it, answer it, mark it done. */
export default function Feedback() {
  const { data, error, reload } = useLoad(() => api.platformFeedback());
  const [status, setStatus] = useState("all");
  const [kind, setKind] = useState("all");
  const [resolving, setResolving] = useState<PlatformFeedbackItem | null>(null);
  const [note, setNote] = useState("");
  const toast = useToast();
  const rows = (data ?? []).filter(
    (f) => (status === "all" || f.status === status) && (kind === "all" || f.kind === kind),
  );
  const count = (s: string) => (data ?? []).filter((f) => f.status === s).length;

  async function mark(f: PlatformFeedbackItem, next: "new" | "read") {
    try {
      await api.platformHandleFeedback(f.id, next);
      await reload();
    } catch (e) {
      toast.err(e instanceof Error ? e.message : "That did not work.");
    }
  }

  return (
    <Page
      title="Feedback"
      subtitle="Problems, ideas and praise from customers' people, newest first."
    >
      <ErrorBanner message={error} />
      <Panel flush>
        <div className="pf-tablebar">
          <Chips
            value={status}
            onChange={setStatus}
            options={[
              { id: "all", label: "All", count: data?.length ?? 0 },
              { id: "new", label: "New", count: count("new") },
              { id: "read", label: "Read", count: count("read") },
              { id: "resolved", label: "Resolved", count: count("resolved") },
            ]}
          />
          <select aria-label="Kind" value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="all">All kinds</option>
            <option value="problem">Problems</option>
            <option value="idea">Ideas</option>
            <option value="praise">Praise</option>
          </select>
        </div>
        {rows.length === 0 && <Empty>Nothing here.</Empty>}
        <div className="pf-stack" style={{ padding: rows.length ? 16 : 0 }}>
          {rows.map((f) => (
            <article key={f.id} className="pf-note">
              <header>
                <Badge tone={KIND[f.kind][1]}>{KIND[f.kind][0]}</Badge>
                <Badge tone={STATUS[f.status][1]}>{STATUS[f.status][0]}</Badge>
                <strong>{f.from ?? "Someone"}</strong> at {f.business ?? "a business"}
                <span>{dateTime(f.created_at)}</span>
                {f.page && <span>on {f.page}</span>}
                {f.app && <span>({f.app})</span>}
              </header>
              <p>{f.message}</p>
              {f.handled_note && <p className="pf-muted">Handled: {f.handled_note}</p>}
              <div style={{ display: "flex", gap: 6, marginTop: 10 }}>
                {f.status === "new" && (
                  <button className="pf-btn small" onClick={() => void mark(f, "read")}>
                    Mark read
                  </button>
                )}
                {f.status !== "resolved" && (
                  <button
                    className="pf-btn small primary"
                    onClick={() => {
                      setResolving(f);
                      setNote("");
                    }}
                  >
                    Resolve
                  </button>
                )}
                {f.status !== "new" && (
                  <button className="pf-btn small" onClick={() => void mark(f, "new")}>
                    Reopen
                  </button>
                )}
              </div>
            </article>
          ))}
        </div>
      </Panel>
      {resolving && (
        <FormDialog
          title="Resolve this feedback"
          description="Say what was done, for the record."
          submitLabel="Resolve"
          onClose={() => setResolving(null)}
          onSubmit={async () => {
            await api.platformHandleFeedback(resolving.id, "resolved", note.trim() || undefined);
            await reload();
            toast.ok("Resolved.");
          }}
        >
          <FormField label="What was done (optional)">
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              maxLength={500}
              rows={3}
            />
          </FormField>
        </FormDialog>
      )}
    </Page>
  );
}
