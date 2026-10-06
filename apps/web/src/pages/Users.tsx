import { ROLE_LABELS, isOtpOnly } from "@fleettms/business-rules";
import type { Depot, InviteInput, Party, Role, StaffMember } from "@fleettms/types";
import { Pencil, Trash2, UserPlus } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

const ROLES = Object.keys(ROLE_LABELS) as Role[];

function RolePicker({ value, onChange }: { value: Role[]; onChange: (r: Role[]) => void }) {
  const toggle = (r: Role) =>
    onChange(value.includes(r) ? value.filter((x) => x !== r) : [...value, r]);
  return (
    <div className="roles">
      {ROLES.map((r) => (
        <label key={r} className="check">
          <input type="checkbox" checked={value.includes(r)} onChange={() => toggle(r)} />
          <span>{ROLE_LABELS[r]}</span>
        </label>
      ))}
    </div>
  );
}

export default function Users() {
  const { can } = useAuth();
  const manage = can("users.manage");
  const [rows, setRows] = useState<StaffMember[]>([]);
  const [depots, setDepots] = useState<Depot[]>([]);
  const [lessors, setLessors] = useState<Party[]>([]);
  const [partyId, setPartyId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [inviteLink, setInviteLink] = useState<string | null>(null);
  const [inviteEmailed, setInviteEmailed] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [editRoles, setEditRoles] = useState<Role[]>([]);
  const [form, setForm] = useState({ name: "", email: "", phone: "", depot_id: "" });
  const [roles, setRoles] = useState<Role[]>([]);

  const load = useCallback(async () => {
    try {
      setRows(await api.users());
      if (can("depots.view")) setDepots(await api.depots());
      if (can("vehicles.view"))
        setLessors((await api.parties()).filter((p) => p.kind === "lessor"));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [can]);
  useEffect(() => {
    void load();
  }, [load]);

  async function invite(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setInviteLink(null);
    setInviteEmailed(null);
    const body: InviteInput = {
      name: form.name,
      email: form.email || null,
      phone: form.phone || null,
      roles,
      depot_id: form.depot_id || null,
      party_id: roles.includes("lessor") ? partyId || null : null,
    };
    try {
      const created = await api.inviteUser(body);
      if (created.invite_token) {
        setInviteLink(`${window.location.origin}/accept-invite?token=${created.invite_token}`);
        if (created.invite_emailed && body.email) setInviteEmailed(body.email);
      }
      setForm({ name: "", email: "", phone: "", depot_id: "" });
      setRoles([]);
      setPartyId("");
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function saveRoles(id: string) {
    try {
      await api.setRoles(id, editRoles);
      setEditing(null);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function remove(m: StaffMember) {
    if (!window.confirm(`Remove ${m.name} from your company? They lose access immediately.`))
      return;
    try {
      await api.removeUser(m.membership_id);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const phoneOnly = isOtpOnly(roles);

  return (
    <>
      <ErrorBanner message={error} />
      {manage && (
        <Card title="Invite someone">
          <form onSubmit={invite} className="form-grid">
            <Field label="Name">
              <input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                required
                minLength={2}
              />
            </Field>
            <Field label={phoneOnly ? "Phone number (required)" : "Email (required)"}>
              {phoneOnly ? (
                <input
                  value={form.phone}
                  onChange={(e) => setForm({ ...form, phone: e.target.value })}
                  inputMode="tel"
                  placeholder="0712 345 678"
                  required
                />
              ) : (
                <input
                  type="email"
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                  required
                />
              )}
            </Field>
            {roles.includes("lessor") && (
              <Field label="Which lessor is this login for?">
                <select value={partyId} onChange={(e) => setPartyId(e.target.value)} required>
                  <option value="">Choose a lessor</option>
                  {lessors.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </Field>
            )}
            <Field label="Depot (optional)">
              <select
                value={form.depot_id}
                onChange={(e) => setForm({ ...form, depot_id: e.target.value })}
              >
                <option value="">No depot</option>
                {depots.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
            </Field>
            <div className="span-all">
              <strong>Roles</strong>
              <RolePicker value={roles} onChange={setRoles} />
            </div>
            <button className="btn primary" disabled={roles.length === 0}>
              <UserPlus size={18} /> Send invitation
            </button>
          </form>
          {phoneOnly && (
            <p className="muted">
              Drivers and turnboys sign in with their phone number and a code sent by SMS.
            </p>
          )}
          {inviteLink && (
            <p className="banner ok">
              {inviteEmailed
                ? `We emailed an invitation to ${inviteEmailed}. If it does not arrive, share this link with them. `
                : "Share this link with them. "}
              It works once and expires in 3 days: <br />
              <code>{inviteLink}</code>
            </p>
          )}
        </Card>
      )}

      <Card title="People">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Contact</th>
                <th>Roles</th>
                <th>2-step</th>
                {manage && <th />}
              </tr>
            </thead>
            <tbody>
              {rows
                .filter((r) => r.status === "active")
                .map((m) => (
                  <tr key={m.membership_id}>
                    <td>{m.name}</td>
                    <td>{m.email ?? m.phone}</td>
                    <td>
                      {editing === m.membership_id ? (
                        <>
                          <RolePicker value={editRoles} onChange={setEditRoles} />
                          <button
                            className="btn"
                            onClick={() => saveRoles(m.membership_id)}
                            disabled={editRoles.length === 0}
                          >
                            Save
                          </button>{" "}
                          <button className="btn" onClick={() => setEditing(null)}>
                            Cancel
                          </button>
                        </>
                      ) : (
                        m.roles.map((r) => (
                          <span key={r} className="badge">
                            {ROLE_LABELS[r]}
                          </span>
                        ))
                      )}
                    </td>
                    <td>{m.two_factor_enabled ? "On" : "Off"}</td>
                    {manage && (
                      <td className="actions">
                        <button
                          className="btn"
                          onClick={() => {
                            setEditing(m.membership_id);
                            setEditRoles(m.roles);
                          }}
                        >
                          <Pencil size={16} /> Roles
                        </button>
                        <button className="btn danger" onClick={() => remove(m)}>
                          <Trash2 size={16} /> Remove
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
