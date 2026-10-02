import type { Depot } from "@fleettms/types";
import { Check, MapPin, Pencil, Plus, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

export default function Depots() {
  const { can } = useAuth();
  const manage = can("depots.manage");
  const [rows, setRows] = useState<Depot[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "", location: "" });
  const [editing, setEditing] = useState<{ id: string; name: string; location: string } | null>(
    null,
  );

  const load = useCallback(async () => {
    try {
      setRows(await api.depots());
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  async function add(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.createDepot({ name: form.name, location: form.location || null });
      setForm({ name: "", location: "" });
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function save() {
    if (!editing) return;
    try {
      await api.updateDepot(editing.id, { name: editing.name, location: editing.location || null });
      setEditing(null);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function remove(d: Depot) {
    if (!window.confirm(`Delete the depot "${d.name}"?`)) return;
    try {
      await api.deleteDepot(d.id);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <>
      <ErrorBanner message={error} />
      {manage && (
        <Card title="Add a depot or branch">
          <form onSubmit={add} className="form-grid">
            <Field label="Name">
              <input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                required
              />
            </Field>
            <Field label="Location">
              <input
                value={form.location}
                onChange={(e) => setForm({ ...form, location: e.target.value })}
                placeholder="e.g. Naivasha, Mai Mahiu Road"
              />
            </Field>
            <button className="btn primary">
              <Plus size={18} /> Add depot
            </button>
          </form>
        </Card>
      )}
      <Card title="Depots and branches">
        {rows.length === 0 && <p className="muted">No depots yet.</p>}
        <ul className="list">
          {rows.map((d) => (
            <li key={d.id}>
              {editing?.id === d.id ? (
                <>
                  <input
                    value={editing.name}
                    onChange={(e) => setEditing({ ...editing, name: e.target.value })}
                  />
                  <input
                    value={editing.location}
                    onChange={(e) => setEditing({ ...editing, location: e.target.value })}
                  />
                  <button className="btn" onClick={save}>
                    <Check size={16} /> Save
                  </button>
                  <button className="btn" onClick={() => setEditing(null)}>
                    <X size={16} /> Cancel
                  </button>
                </>
              ) : (
                <>
                  <span>
                    <MapPin size={16} /> <strong>{d.name}</strong>
                    {d.location && <span className="muted"> {d.location}</span>}
                  </span>
                  {manage && (
                    <span className="actions">
                      <button
                        className="btn"
                        onClick={() =>
                          setEditing({ id: d.id, name: d.name, location: d.location ?? "" })
                        }
                      >
                        <Pencil size={16} /> Edit
                      </button>
                      <button className="btn danger" onClick={() => remove(d)}>
                        <Trash2 size={16} /> Delete
                      </button>
                    </span>
                  )}
                </>
              )}
            </li>
          ))}
        </ul>
      </Card>
    </>
  );
}
