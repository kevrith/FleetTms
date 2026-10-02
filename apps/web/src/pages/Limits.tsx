import type { ExpenseCategory, Role, RouteCost, SpendLimit } from "@fleettms/types";
import { Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { EXPENSE_CATEGORY, ROLE_NAMES, kes } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

/** The owner's spend limits, and what each category usually costs on a route. */
export default function Limits() {
  const { can } = useAuth();
  const [limits, setLimits] = useState<SpendLimit[]>([]);
  const [routes, setRoutes] = useState<RouteCost[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [rule, setRule] = useState({ category: "", role: "", kes: "" });
  const [route, setRoute] = useState({
    origin: "",
    destination: "",
    category: "toll",
    kes: "",
    tolerance: "50",
  });

  const load = useCallback(async () => {
    try {
      setLimits(await api.spendLimits());
      setRoutes(await api.routeCosts());
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  async function save(next: SpendLimit[]) {
    setError(null);
    setSaved(false);
    try {
      setLimits(await api.setSpendLimits(next));
      setSaved(true);
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  function addRule(e: FormEvent) {
    e.preventDefault();
    void save([
      ...limits,
      {
        category: (rule.category || null) as ExpenseCategory | null,
        role: (rule.role || null) as Role | null,
        limit_cents: Math.round(Number(rule.kes) * 100),
      },
    ]);
    setRule({ category: "", role: "", kes: "" });
  }

  async function addRoute(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.addRouteCost({
        origin: route.origin,
        destination: route.destination,
        category: route.category as ExpenseCategory,
        usual_cents: Math.round(Number(route.kes) * 100),
        tolerance_pct: Number(route.tolerance),
      });
      setRoute({ ...route, origin: "", destination: "", kes: "" });
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const owner = can("business.manage");
  return (
    <>
      <ErrorBanner message={error} />
      <Card title="Spend limits">
        <p className="muted">
          An expense above its limit waits for the owner's approval and does not count until
          approved. The most specific rule applies: a type and a role, then either one, then
          "everything".
        </p>
        {saved && <p className="status ok">Saved.</p>}
        {limits.length === 0 && (
          <p className="muted">No limits set. Every expense counts straight away.</p>
        )}
        <ul className="list">
          {limits.map((l, i) => (
            <li key={i}>
              <span>
                <strong>{l.category ? EXPENSE_CATEGORY[l.category] : "Any type"}</strong>,{" "}
                {l.role ? ROLE_NAMES[l.role] : "any role"}: {kes(l.limit_cents)}
              </span>
              {owner && (
                <button
                  className="btn danger"
                  onClick={() => save(limits.filter((_, j) => j !== i))}
                >
                  <Trash2 size={16} /> Remove
                </button>
              )}
            </li>
          ))}
        </ul>
        {owner && (
          <form onSubmit={addRule} className="form-grid">
            <Field label="Type">
              <select
                value={rule.category}
                onChange={(e) => setRule({ ...rule, category: e.target.value })}
              >
                <option value="">Any type</option>
                {Object.entries(EXPENSE_CATEGORY).map(([k, label]) => (
                  <option key={k} value={k}>
                    {label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Role">
              <select
                value={rule.role}
                onChange={(e) => setRule({ ...rule, role: e.target.value })}
              >
                <option value="">Any role</option>
                {Object.entries(ROLE_NAMES).map(([k, label]) => (
                  <option key={k} value={k}>
                    {label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Limit (KES)">
              <input
                type="number"
                min="1"
                step="0.01"
                value={rule.kes}
                onChange={(e) => setRule({ ...rule, kes: e.target.value })}
                required
              />
            </Field>
            <button className="btn primary">
              <Plus size={16} /> Add limit
            </button>
          </form>
        )}
      </Card>
      <Card title="Usual costs per route">
        <p className="muted">
          A claim well above the usual cost for its route is flagged (not blocked).
        </p>
        {routes.length === 0 && <p className="muted">None yet.</p>}
        <ul className="list">
          {routes.map((r) => (
            <li key={r.id}>
              <span>
                {r.origin} to {r.destination}, {EXPENSE_CATEGORY[r.category]}: usually{" "}
                {kes(r.usual_cents)} (flag above{" "}
                {kes((r.usual_cents * (100 + r.tolerance_pct)) / 100)})
              </span>
              {can("vehicles.manage") && (
                <button className="btn danger" onClick={() => api.deleteRouteCost(r.id).then(load)}>
                  <Trash2 size={16} /> Remove
                </button>
              )}
            </li>
          ))}
        </ul>
        {can("vehicles.manage") && (
          <form onSubmit={addRoute} className="form-grid">
            <Field label="From">
              <input
                value={route.origin}
                onChange={(e) => setRoute({ ...route, origin: e.target.value })}
                required
              />
            </Field>
            <Field label="To">
              <input
                value={route.destination}
                onChange={(e) => setRoute({ ...route, destination: e.target.value })}
                required
              />
            </Field>
            <Field label="Type">
              <select
                value={route.category}
                onChange={(e) => setRoute({ ...route, category: e.target.value })}
              >
                {Object.entries(EXPENSE_CATEGORY).map(([k, label]) => (
                  <option key={k} value={k}>
                    {label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Usual cost (KES)">
              <input
                type="number"
                min="1"
                step="0.01"
                value={route.kes}
                onChange={(e) => setRoute({ ...route, kes: e.target.value })}
                required
              />
            </Field>
            <Field label="Flag when above usual by (%)">
              <input
                type="number"
                min="0"
                max="500"
                value={route.tolerance}
                onChange={(e) => setRoute({ ...route, tolerance: e.target.value })}
              />
            </Field>
            <button className="btn primary">
              <Plus size={16} /> Add route cost
            </button>
          </form>
        )}
      </Card>
    </>
  );
}
