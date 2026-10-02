import type { ChecklistItem } from "@fleettms/types";
import { Plus } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

type Body = Omit<ChecklistItem, "id">;
const body = (i: ChecklistItem, patch: Partial<Body>): Body => ({
  label: i.label,
  critical: i.critical,
  photo_on_fault: i.photo_on_fault,
  is_active: i.is_active,
  sort_order: i.sort_order,
  ...patch,
});

/** The pre-trip checklist each business uses. Critical items block the trip when they fail. */
export default function Checklist() {
  const [items, setItems] = useState<ChecklistItem[]>([]);
  const [label, setLabel] = useState("");
  const [critical, setCritical] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setItems(await api.checklist(true));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  async function change(i: ChecklistItem, patch: Partial<Body>) {
    setError(null);
    try {
      await api.updateChecklistItem(i.id, body(i, patch));
      await load();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  async function add(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.addChecklistItem({
        label,
        critical,
        photo_on_fault: true,
        is_active: true,
        sort_order: (items.at(-1)?.sort_order ?? 0) + 10,
      });
      setLabel("");
      setCritical(false);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <>
      <ErrorBanner message={error} />
      <Card title="Pre-trip checklist">
        <p className="muted">
          Drivers answer every active item before their first trip of the day. A failed critical
          item blocks the trip until a manager overrides it with a reason.
        </p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Item</th>
                <th>Critical</th>
                <th>Photo needed on fault</th>
                <th>In use</th>
              </tr>
            </thead>
            <tbody>
              {items.map((i) => (
                <tr key={i.id}>
                  <td>{i.label}</td>
                  <td>
                    <input
                      type="checkbox"
                      aria-label={`${i.label} is critical`}
                      checked={i.critical}
                      onChange={(e) => change(i, { critical: e.target.checked })}
                    />
                  </td>
                  <td>
                    <input
                      type="checkbox"
                      aria-label={`${i.label} needs a photo on fault`}
                      checked={i.photo_on_fault}
                      onChange={(e) => change(i, { photo_on_fault: e.target.checked })}
                    />
                  </td>
                  <td>
                    <input
                      type="checkbox"
                      aria-label={`${i.label} is in use`}
                      checked={i.is_active}
                      onChange={(e) => change(i, { is_active: e.target.checked })}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <Card title="Add an item">
        <form onSubmit={add} className="form-grid">
          <Field label="What should be checked?">
            <input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              required
              minLength={2}
            />
          </Field>
          <label className="check">
            <input
              type="checkbox"
              checked={critical}
              onChange={(e) => setCritical(e.target.checked)}
            />
            <span>Critical (blocks the trip)</span>
          </label>
          <button className="btn primary">
            <Plus size={18} /> Add item
          </button>
        </form>
      </Card>
    </>
  );
}
