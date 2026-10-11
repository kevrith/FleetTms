import type { Renewal, RenewalProof, StaffProfile, Vehicle } from "@fleettms/types";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

const DOC_TYPES = [
  { value: "driving_licence", label: "Driving licence", person: true },
  { value: "insurance", label: "Insurance", person: false },
  { value: "inspection", label: "Inspection", person: false },
  { value: "ntsa_licence", label: "NTSA licence", person: false },
  { value: "tlb_licence", label: "TLB licence", person: false },
  { value: "permit", label: "Permit", person: false },
];
const PROOFS: Record<string, { value: RenewalProof; label: string }[]> = {
  driving_licence: [
    { value: "receipt", label: "Payment receipt (the 3-year renewal, no card yet)" },
    { value: "digital_licence", label: "Digital licence from NTSA (the 1-year renewal)" },
  ],
  insurance: [{ value: "certificate", label: "Insurer's certificate" }],
};
const proofsFor = (doc: string) =>
  PROOFS[doc] ?? [
    { value: "certificate" as RenewalProof, label: "Certificate" },
    { value: "receipt" as RenewalProof, label: "Payment receipt" },
  ];

function ProofLink({ r }: { r: Renewal }) {
  if (!r.proof?.url) return <span className="muted">no file</span>;
  return (
    <a href={api.mediaUrl(r.proof.url)} target="_blank" rel="noreferrer">
      {r.proof.is_pdf ? "Open the PDF" : "Open the photo"}
    </a>
  );
}

function SendForm({ onSent }: { onSent: () => void }) {
  const [doc, setDoc] = useState("driving_licence");
  const [people, setPeople] = useState<StaffProfile[]>([]);
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [subject, setSubject] = useState("");
  const [date, setDate] = useState("");
  const [proof, setProof] = useState<RenewalProof>("receipt");
  const [reference, setReference] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const person = DOC_TYPES.find((d) => d.value === doc)?.person ?? false;

  useEffect(() => {
    void api
      .staff()
      .then(setPeople)
      .catch(() => undefined);
    void api
      .vehicles()
      .then(setVehicles)
      .catch(() => undefined);
  }, []);
  useEffect(() => {
    setSubject("");
    setProof(proofsFor(doc)[0]!.value);
  }, [doc]);

  async function send() {
    if (!file) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const photo = await api.uploadPhoto(file, { kind: "document", source: "web" });
      const renewal = await api.submitRenewal({
        doc_type: doc,
        ...(person ? { membership_id: subject } : { vehicle_id: subject }),
        new_expires_on: date,
        proof_kind: proof,
        ...(reference.trim() ? { reference: reference.trim() } : {}),
        photo_id: photo.id,
      });
      setMessage(
        renewal.status === "approved"
          ? "Saved. The new date is on the record."
          : "Sent. Someone else must approve it before the date changes.",
      );
      setFile(null);
      setDate("");
      setReference("");
      onSent();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Send a renewal with its proof">
      <ErrorBanner message={error} />
      <div className="form-grid">
        <Field label="Document">
          <select value={doc} onChange={(e) => setDoc(e.target.value)}>
            {DOC_TYPES.map((d) => (
              <option key={d.value} value={d.value}>
                {d.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label={person ? "Whose licence" : "Which lorry"}>
          <select value={subject} onChange={(e) => setSubject(e.target.value)}>
            <option value="">Choose</option>
            {person
              ? people.map((p) => (
                  <option key={p.membership_id} value={p.membership_id}>
                    {p.name}
                  </option>
                ))
              : vehicles.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.registration}
                  </option>
                ))}
          </select>
        </Field>
        <Field label="New expiry date">
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </Field>
        <Field label="Proof">
          <select value={proof} onChange={(e) => setProof(e.target.value as RenewalProof)}>
            {proofsFor(doc).map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Receipt or policy number (optional)">
          <input value={reference} onChange={(e) => setReference(e.target.value)} />
        </Field>
        <Field label="The proof (photo, screenshot or PDF)">
          <input
            type="file"
            accept="image/*,application/pdf"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </Field>
      </div>
      <button
        type="button"
        className="btn primary"
        disabled={busy || !file || !subject || !date}
        onClick={() => void send()}
      >
        Send for approval
      </button>
      {message && <p className="status ok">{message}</p>}
    </Card>
  );
}

function Row({ r, onChanged }: { r: Renewal; onChanged: () => void }) {
  const [date, setDate] = useState(r.new_expires_on);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  async function decide(approve: boolean) {
    setError(null);
    try {
      if (approve)
        await api.approveRenewal(r.id, { expires_on: date, note: note.trim() || undefined });
      else await api.rejectRenewal(r.id, note.trim());
      onChanged();
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  return (
    <li style={{ display: "block" }}>
      <ErrorBanner message={error} />
      <strong>
        {r.label} for {r.subject}
      </strong>{" "}
      <span className="muted">
        sent by {r.submitted_by ?? "someone"}; on record until {r.current_expires_on ?? "nothing"};{" "}
        {r.proof_kind.replace("_", " ")}
        {r.reference ? ` ${r.reference}` : ""}
      </span>{" "}
      <ProofLink r={r} />
      <div className="form-grid">
        <Field label="New expiry date (change it if the proof says otherwise)">
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </Field>
        <Field label="Note (needed to turn it down)">
          <input value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
      </div>
      <button type="button" className="btn primary" onClick={() => void decide(true)}>
        Approve
      </button>{" "}
      <button
        type="button"
        className="btn danger"
        disabled={note.trim().length < 3}
        onClick={() => void decide(false)}
      >
        Turn down
      </button>
    </li>
  );
}

/** Renewals of licences and insurance waiting for someone to look at the proof, and a form to send one. */
export default function Renewals() {
  const { can } = useAuth();
  const [pending, setPending] = useState<Renewal[]>([]);
  const [recent, setRecent] = useState<Renewal[]>([]);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setPending(await api.renewals("pending"));
      setRecent((await api.renewals("all")).filter((r) => r.status !== "pending").slice(0, 15));
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  return (
    <>
      <h2>Renewals</h2>
      <ErrorBanner message={error} />
      <p className="muted">
        NTSA renews a driving licence as soon as the fee is paid, so the payment receipt is proof
        that it is valid; a one-year renewal also comes as a digital licence. Look at the proof and
        the date before approving. Approving puts the date on the record, which clears the trip
        block.
      </p>
      <Card title={`Waiting for approval (${pending.length})`}>
        {pending.length === 0 && <p className="muted">Nothing is waiting.</p>}
        <ul className="list">
          {pending.map((r) => (
            <Row key={r.id} r={r} onChanged={() => void load()} />
          ))}
        </ul>
      </Card>
      {(can("staff.manage") || can("vehicles.manage")) && <SendForm onSent={() => void load()} />}
      {recent.length > 0 && (
        <Card title="Recently decided">
          <ul className="list">
            {recent.map((r) => (
              <li key={r.id}>
                <span>
                  {r.label} for {r.subject}, new date {r.new_expires_on}
                </span>
                <span className={`status ${r.status === "approved" ? "ok" : "bad"}`}>
                  {r.status}
                  {r.decision_note ? `: ${r.decision_note}` : ""}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}
