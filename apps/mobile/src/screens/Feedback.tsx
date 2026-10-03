import { useState } from "react";
import { api } from "../api";
import { Body, Button, ErrorText, errorMessage, Input } from "../ui";

const KINDS: { kind: "problem" | "idea" | "praise"; label: string }[] = [
  { kind: "problem", label: "Something is wrong" },
  { kind: "idea", label: "Something is missing" },
  { kind: "praise", label: "Something works well" },
];

/** The beta feedback button: tell us what is wrong, what is missing or what works well. Needs a connection: it is not queued. */
export function FeedbackCard() {
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<"problem" | "idea" | "praise">("problem");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function send() {
    setBusy(true);
    setError(null);
    try {
      await api.sendFeedback({ kind, message: text.trim(), page: "mobile", app: "mobile" });
      setSent(true);
      setText("");
      setOpen(false);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  if (!open)
    return (
      <>
        {sent && <Body>Thank you. We read every one.</Body>}
        <Button
          kind="secondary"
          label="Send feedback"
          onPress={() => {
            setSent(false);
            setOpen(true);
          }}
        />
      </>
    );
  return (
    <>
      <Body>What is it?</Body>
      {KINDS.map((k) => (
        <Button
          key={k.kind}
          kind={k.kind === kind ? "primary" : "secondary"}
          label={k.label}
          onPress={() => setKind(k.kind)}
        />
      ))}
      <Input label="Tell us more" value={text} onChangeText={setText} multiline maxLength={2000} />
      <ErrorText message={error} />
      <Button label="Send" onPress={send} busy={busy} disabled={text.trim().length < 3} />
      <Button kind="secondary" label="Cancel" onPress={() => setOpen(false)} />
    </>
  );
}
