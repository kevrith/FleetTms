import type { DataRequestKind, DataSubjectRequest } from "@fleettms/types";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { Body, Button, ErrorText, errorMessage, Input } from "../ui";

const KINDS: { kind: DataRequestKind; label: string }[] = [
  { kind: "access", label: "See what is held about me" },
  { kind: "correct", label: "Correct something" },
  { kind: "delete", label: "Delete my data" },
  { kind: "object", label: "Stop a use I object to" },
  { kind: "portability", label: "Give me a copy" },
];
const STATE = { open: "Waiting for an answer", completed: "Answered", refused: "Refused" } as const;

/** Ask your employer what is held about you, to correct it, to take it away or to stop using it. They must answer, and say why if they cannot. */
export function MyDataCard() {
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<DataRequestKind>("access");
  const [text, setText] = useState("");
  const [rows, setRows] = useState<DataSubjectRequest[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRows(await api.myDataRequests());
    } catch {
      /* offline: the list comes back next time */
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  async function send() {
    setBusy(true);
    setError(null);
    try {
      await api.askAboutMyData(kind, text.trim() || undefined);
      setText("");
      setOpen(false);
      await load();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {rows.map((r) => (
        <Body key={r.id}>
          {KINDS.find((k) => k.kind === r.kind)?.label}: {STATE[r.status]}
          {r.status === "open" ? ` (due ${r.due_on})` : r.resolution ? `. ${r.resolution}` : ""}
        </Body>
      ))}
      {!open ? (
        <Button kind="secondary" label="My data and my rights" onPress={() => setOpen(true)} />
      ) : (
        <>
          <Body>What do you want your employer to do?</Body>
          {KINDS.map((k) => (
            <Button
              key={k.kind}
              kind={k.kind === kind ? "primary" : "secondary"}
              label={k.label}
              onPress={() => setKind(k.kind)}
            />
          ))}
          <Input
            label="Anything they should know (optional)"
            value={text}
            onChangeText={setText}
            multiline
            maxLength={2000}
          />
          <ErrorText message={error} />
          <Button label="Send the request" onPress={send} busy={busy} />
          <Button kind="secondary" label="Cancel" onPress={() => setOpen(false)} />
        </>
      )}
    </>
  );
}
