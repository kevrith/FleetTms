import type { DocumentReading, ReadableDocument } from "@fleettms/types";
import { FileSearch } from "lucide-react";
import { useState, type ChangeEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

const KINDS: Record<string, string> = {
  insurance_certificate: "Insurance certificate",
  logbook: "Logbook",
  weighbridge_ticket: "Weighbridge ticket",
  delivery_note: "Delivery note",
};
const FIELD_LABEL: Record<string, string> = {
  insurer: "Insurer",
  policy_no: "Policy number",
  registration: "Number plate",
  cover_type: "Type of cover",
  valid_from: "Valid from",
  valid_to: "Valid to",
  chassis_no: "Chassis number",
  engine_no: "Engine number",
  make: "Make",
  model: "Model",
  year: "Year",
  owner_name: "Owner",
  ticket_no: "Ticket number",
  gross_kg: "Gross weight (kg)",
  tare_kg: "Tare weight (kg)",
  net_kg: "Net weight (kg)",
  cargo: "Cargo",
  date: "Date",
  reference: "Reference",
  recipient_name: "Received by",
  description: "Goods",
  quantity: "Quantity",
  notes: "Notes",
};
const DATE_FIELDS = new Set(["valid_from", "valid_to", "date"]);
const NUMBER_FIELDS = new Set(["gross_kg", "tare_kg", "net_kg", "quantity", "year"]);

/**
 * Read a paper from a photo: the service suggests the fields, the person corrects them, and nothing is kept until they confirm.
 * An insurance certificate can be saved straight to the vehicle's records, with its expiry date so the reminders start.
 */
export function ReadDocumentCard({
  vehicleId,
  onSaved,
}: {
  vehicleId: string;
  onSaved?: () => void;
}) {
  const { can } = useAuth();
  const [kind, setKind] = useState<ReadableDocument>("insurance_certificate");
  const [reading, setReading] = useState<DocumentReading | null>(null);
  const [fields, setFields] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (!can("vehicles.manage")) return null;

  async function pick(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const photo = await api.uploadPhoto(file, { kind: "document", source: "web" });
      const r = await api.readDocument({ photo_id: photo.id, kind, vehicle_id: vehicleId });
      setReading(r);
      setFields(
        Object.fromEntries(
          Object.entries(r.fields).map(([k, v]) => [k, v == null ? "" : String(v)]),
        ),
      );
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  function typed(): Record<string, string | number | null> {
    return Object.fromEntries(
      Object.entries(fields).map(([k, v]) => [
        k,
        v.trim() === "" ? null : NUMBER_FIELDS.has(k) ? Number(v) : v.trim(),
      ]),
    );
  }

  async function confirm(save: boolean) {
    if (!reading) return;
    setBusy(true);
    setError(null);
    try {
      await api.confirmReading(reading.id, typed());
      if (save) {
        const done = await api.applyReading(reading.id);
        setMessage(`Saved as the vehicle's insurance record, expiring ${done.expires_on}.`);
        onSaved?.();
      } else {
        setMessage("Confirmed.");
      }
      setReading(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function discard() {
    if (reading) await api.rejectReading(reading.id).catch(() => undefined);
    setReading(null);
  }

  return (
    <Card title="Read a document from a photo">
      <ErrorBanner message={error} />
      {message && (
        <p className="banner ok" role="status">
          {message}
        </p>
      )}
      {!reading && (
        <div className="form-grid">
          <Field label="What is it?">
            <select value={kind} onChange={(e) => setKind(e.target.value as ReadableDocument)}>
              {Object.entries(KINDS).map(([k, label]) => (
                <option key={k} value={k}>
                  {label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Photo of the document">
            <input type="file" accept="image/*" onChange={pick} disabled={busy} />
          </Field>
          <p className="muted">
            The photo is sent to a document-reading service. It suggests what is written; you check
            and correct it before anything is saved.
          </p>
        </div>
      )}
      {reading && (
        <>
          <p>
            <FileSearch size={16} /> Here is what was read
            {reading.confidence !== null &&
              ` (the reader is ${Math.round(reading.confidence * 100)}% sure)`}
            . Check each line against the paper.
          </p>
          {reading.warnings.map((w) => (
            <p key={w} className="banner bad">
              {w}
            </p>
          ))}
          <div className="form-grid">
            {Object.keys(fields).map((k) => (
              <Field key={k} label={FIELD_LABEL[k] ?? k}>
                <input
                  type={DATE_FIELDS.has(k) ? "date" : NUMBER_FIELDS.has(k) ? "number" : "text"}
                  value={fields[k]}
                  onChange={(e) => setFields({ ...fields, [k]: e.target.value })}
                />
              </Field>
            ))}
          </div>
          <p className="actions">
            {reading.kind === "insurance_certificate" && (
              <button
                className="btn primary"
                type="button"
                disabled={busy}
                onClick={() => confirm(true)}
              >
                Confirm and save as the insurance record
              </button>
            )}
            <button className="btn" type="button" disabled={busy} onClick={() => confirm(false)}>
              Confirm
            </button>
            <button className="btn" type="button" disabled={busy} onClick={discard}>
              Discard
            </button>
          </p>
        </>
      )}
    </Card>
  );
}
