import type { ComplianceDocType, ComplianceDocument } from "@fleettms/types";
import { Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { DOC_TYPE, daysUntil } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

type Owner = { vehicleId: string } | { membershipId: string };

export function ExpiryBadge({ iso }: { iso: string }) {
  const days = daysUntil(iso);
  const cls = days < 0 ? "bad" : days <= 30 ? "warn" : "ok";
  const text =
    days < 0 ? `Expired ${-days} d ago` : days === 0 ? "Expires today" : `${days} d left`;
  return <span className={`status ${cls}`}>{text}</span>;
}

/** Insurance, inspection, licences and permits for one vehicle or one staff member. */
export default function DocumentsPanel({
  owner,
  types,
  canManage,
}: {
  owner: Owner;
  types: ComplianceDocType[];
  canManage: boolean;
}) {
  const [rows, setRows] = useState<ComplianceDocument[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState<{
    doc_type: ComplianceDocType;
    reference: string;
    expires_on: string;
  }>({
    doc_type: types[0] ?? "other",
    reference: "",
    expires_on: "",
  });
  const key = "vehicleId" in owner ? owner.vehicleId : owner.membershipId;

  const load = useCallback(async () => {
    try {
      setRows(
        await api.documents("vehicleId" in owner ? { vehicleId: key } : { membershipId: key }),
      );
    } catch (e) {
      setError(errorMessage(e));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  useEffect(() => {
    void load();
  }, [load]);

  async function add(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.createDocument({
        doc_type: form.doc_type,
        vehicle_id: "vehicleId" in owner ? owner.vehicleId : null,
        membership_id: "membershipId" in owner ? owner.membershipId : null,
        reference: form.reference || null,
        issued_on: null,
        expires_on: form.expires_on,
      });
      setForm({ ...form, reference: "", expires_on: "" });
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function remove(d: ComplianceDocument) {
    if (!window.confirm(`Delete this ${DOC_TYPE[d.doc_type]} record?`)) return;
    try {
      await api.deleteDocument(d.id);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <Card title="Documents and expiry dates">
      <ErrorBanner message={error} />
      {rows.length === 0 && <p className="muted">No documents recorded yet.</p>}
      <ul className="list">
        {rows.map((d) => (
          <li key={d.id}>
            <span>
              <strong>{DOC_TYPE[d.doc_type]}</strong>
              {d.reference && <span className="muted"> {d.reference}</span>}
              <span className="muted"> expires {d.expires_on}</span>{" "}
              <ExpiryBadge iso={d.expires_on} />
            </span>
            {canManage && (
              <button className="btn danger" onClick={() => remove(d)}>
                <Trash2 size={16} /> Delete
              </button>
            )}
          </li>
        ))}
      </ul>
      {canManage && (
        <form onSubmit={add} className="form-grid">
          <Field label="Type">
            <select
              value={form.doc_type}
              onChange={(e) => setForm({ ...form, doc_type: e.target.value as ComplianceDocType })}
            >
              {types.map((t) => (
                <option key={t} value={t}>
                  {DOC_TYPE[t]}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Reference or policy number">
            <input
              value={form.reference}
              onChange={(e) => setForm({ ...form, reference: e.target.value })}
            />
          </Field>
          <Field label="Expires on">
            <input
              type="date"
              value={form.expires_on}
              onChange={(e) => setForm({ ...form, expires_on: e.target.value })}
              required
            />
          </Field>
          <button className="btn primary">
            <Plus size={18} /> Add document
          </button>
        </form>
      )}
    </Card>
  );
}
