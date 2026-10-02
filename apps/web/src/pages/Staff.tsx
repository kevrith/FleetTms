import type { ProfileInput, StaffProfile } from "@fleettms/types";
import { Pencil } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { STAFF_DOC_TYPES } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";
import DocumentsPanel from "./DocumentsPanel";

const text = (v: string) => (v.trim() === "" ? null : v.trim());

function ProfileForm({
  person,
  canSeePay,
  onSaved,
}: {
  person: StaffProfile;
  canSeePay: boolean;
  onSaved: () => Promise<void>;
}) {
  const [f, setF] = useState({
    licence_number: person.licence_number ?? "",
    licence_class: person.licence_class ?? "",
    contact_name: person.emergency_contact_name ?? "",
    contact_phone: person.emergency_contact_phone ?? "",
    salary: person.monthly_salary_cents != null ? String(person.monthly_salary_cents / 100) : "",
  });
  const [error, setError] = useState<string | null>(null);

  async function save(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const input: ProfileInput = {
      licence_number: text(f.licence_number),
      licence_class: text(f.licence_class),
      emergency_contact_name: text(f.contact_name),
      emergency_contact_phone: text(f.contact_phone),
    };
    if (canSeePay)
      input.monthly_salary_cents =
        f.salary.trim() === "" ? null : Math.round(Number(f.salary) * 100);
    try {
      await api.updateStaffProfile(person.membership_id, input);
      await onSaved();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <form onSubmit={save} className="form-grid">
      <ErrorBanner message={error} />
      <Field label="Licence number">
        <input
          value={f.licence_number}
          onChange={(e) => setF({ ...f, licence_number: e.target.value })}
        />
      </Field>
      <Field label="Licence class">
        <input
          value={f.licence_class}
          onChange={(e) => setF({ ...f, licence_class: e.target.value })}
        />
      </Field>
      <Field label="Emergency contact">
        <input
          value={f.contact_name}
          onChange={(e) => setF({ ...f, contact_name: e.target.value })}
        />
      </Field>
      <Field label="Emergency contact phone">
        <input
          value={f.contact_phone}
          onChange={(e) => setF({ ...f, contact_phone: e.target.value })}
        />
      </Field>
      {canSeePay && (
        <Field label="Monthly salary (KES)">
          <input
            type="number"
            min="0"
            step="0.01"
            value={f.salary}
            onChange={(e) => setF({ ...f, salary: e.target.value })}
          />
        </Field>
      )}
      <button className="btn primary">Save profile</button>
    </form>
  );
}

export default function Staff() {
  const { can } = useAuth();
  const manage = can("staff.manage");
  const [rows, setRows] = useState<StaffProfile[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRows(await api.staff());
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  return (
    <>
      <h2>Staff</h2>
      <p className="muted">Invite people and set their roles under Settings, People.</p>
      <ErrorBanner message={error} />
      <Card>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Roles</th>
                <th>Phone</th>
                <th>Licence</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.membership_id}>
                  <td>{s.name}</td>
                  <td>{s.roles.join(", ")}</td>
                  <td>{s.phone}</td>
                  <td>{[s.licence_number, s.licence_class].filter(Boolean).join(" ")}</td>
                  <td>
                    <button
                      className="btn"
                      onClick={() => setOpen(open === s.membership_id ? null : s.membership_id)}
                    >
                      <Pencil size={16} /> {manage ? "Edit" : "View"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      {rows
        .filter((s) => s.membership_id === open)
        .map((s) => (
          <div key={s.membership_id}>
            <h3>{s.name}</h3>
            {manage && <ProfileForm person={s} canSeePay={can("payroll.view")} onSaved={load} />}
            <DocumentsPanel
              owner={{ membershipId: s.membership_id }}
              types={STAFF_DOC_TYPES}
              canManage={manage}
            />
          </div>
        ))}
    </>
  );
}
