import type { PartsOrder, Part, Supplier } from "@fleettms/types";
import { MessageCircle, Plus } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { api } from "../api";
import { kes } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

const toCents = (kesText: string) => Math.round(Number(kesText || 0) * 100);
const STATUS: Record<string, string> = {
  draft: "Draft",
  sent: "Sent",
  confirmed: "Confirmed",
  collected: "Collected",
  paid: "Paid",
  cancelled: "Cancelled",
};
const NEXT: Record<string, [string, string][]> = {
  sent: [
    ["confirmed", "Supplier confirmed"],
    ["collected", "Collected"],
    ["cancelled", "Cancel"],
  ],
  confirmed: [
    ["collected", "Collected"],
    ["cancelled", "Cancel"],
  ],
  collected: [["paid", "Mark as paid"]],
  draft: [["cancelled", "Cancel"]],
};

function SupplierList() {
  const [rows, setRows] = useState<Supplier[]>([]);
  const [form, setForm] = useState({ name: "", phone: "", email: "", category: "" });
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setRows(await api.suppliers());
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
      await api.addSupplier({
        name: form.name,
        phone: form.phone || null,
        email: form.email || null,
        category: form.category || null,
      });
      setForm({ name: "", phone: "", email: "", category: "" });
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }
  return (
    <>
      <ErrorBanner message={error} />
      <Card title="Suppliers">
        {rows.length === 0 && <p className="muted">No suppliers yet.</p>}
        <ul className="list">
          {rows.map((s) => (
            <li key={s.id}>
              <span>
                {s.name}
                {s.category && <span className="muted"> ({s.category})</span>}
              </span>
              <span>{[s.phone, s.email].filter(Boolean).join(", ")}</span>
            </li>
          ))}
        </ul>
      </Card>
      <Card title="Add a supplier">
        <form className="form-grid" onSubmit={add}>
          <Field label="Name">
            <input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              required
              minLength={2}
            />
          </Field>
          <Field label="Phone (for WhatsApp orders)">
            <input
              value={form.phone}
              onChange={(e) => setForm({ ...form, phone: e.target.value })}
              inputMode="tel"
            />
          </Field>
          <Field label="Email">
            <input
              type="email"
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
            />
          </Field>
          <Field label="What they supply">
            <input
              value={form.category}
              onChange={(e) => setForm({ ...form, category: e.target.value })}
            />
          </Field>
          <button className="btn primary" type="submit">
            <Plus size={16} /> Add
          </button>
        </form>
      </Card>
    </>
  );
}

function Orders() {
  const [orders, setOrders] = useState<PartsOrder[]>([]);
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [parts, setParts] = useState<Part[]>([]);
  const [form, setForm] = useState({
    supplier_id: "",
    notes: "",
    lines: [{ part_id: "", description: "", quantity: "1", cost: "" }],
  });
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setOrders(await api.orders());
      setSuppliers(await api.suppliers());
      setParts(await api.parts());
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  async function run(action: () => Promise<unknown>, done?: string) {
    setError(null);
    setMessage(null);
    try {
      await action();
      if (done) setMessage(done);
      await load();
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  const setLine = (n: number, patch: Partial<(typeof form.lines)[number]>) =>
    setForm({ ...form, lines: form.lines.map((l, i) => (i === n ? { ...l, ...patch } : l)) });
  async function create(e: FormEvent) {
    e.preventDefault();
    await run(async () => {
      await api.createOrder({
        supplier_id: form.supplier_id,
        notes: form.notes || null,
        lines: form.lines
          .filter((l) => l.description.trim())
          .map((l) => ({
            part_id: l.part_id || null,
            description: l.description,
            quantity: Number(l.quantity || 1),
            unit_cost_cents: toCents(l.cost),
          })),
      });
      setForm({
        supplier_id: form.supplier_id,
        notes: "",
        lines: [{ part_id: "", description: "", quantity: "1", cost: "" }],
      });
    }, "Order saved as a draft.");
  }
  return (
    <>
      <ErrorBanner message={error} />
      {message && <p className="banner ok">{message}</p>}
      <Card title="Parts orders">
        <p className="actions">
          <button
            className="btn"
            onClick={() =>
              run(async () => {
                const made = await api.draftLowStockOrders();
                setMessage(
                  made.length
                    ? `${made.length} draft order${made.length === 1 ? "" : "s"} made from what is running low.`
                    : "Nothing is running low, or the low parts name no supplier.",
                );
              })
            }
          >
            Draft orders for what is running low
          </button>
        </p>
        {orders.length === 0 && <p className="muted">No orders yet.</p>}
        {orders.map((o) => (
          <div className="card" key={o.id}>
            <p>
              <strong>{o.number}</strong> to {o.supplier_name}, {kes(o.total_cents)}{" "}
              <span className="status">{STATUS[o.status]}</span>
            </p>
            <ul className="list">
              {o.lines.map((l) => (
                <li key={l.id}>
                  <span>
                    {l.quantity} x {l.description}
                  </span>
                  <span>{l.unit_cost_cents ? kes(l.unit_cost_cents) : ""}</span>
                </li>
              ))}
            </ul>
            <p className="actions">
              {(o.status === "draft" || o.status === "sent") && (
                <button
                  className="btn primary"
                  onClick={() =>
                    run(async () => {
                      const sent = await api.sendOrder(o.id);
                      if (sent.whatsapp_url) window.open(sent.whatsapp_url, "_blank", "noopener");
                    }, "WhatsApp is open with the order written. Press send there.")
                  }
                >
                  <MessageCircle size={16} />{" "}
                  {o.status === "draft" ? "Send by WhatsApp" : "Open WhatsApp again"}
                </button>
              )}{" "}
              {(NEXT[o.status] ?? []).map(([to, label]) => (
                <button
                  key={to}
                  className="btn"
                  onClick={() => {
                    const ref =
                      to === "paid"
                        ? window.prompt("M-Pesa code or cheque number (optional)")
                        : undefined;
                    if (ref === null) return;
                    void run(
                      () => api.moveOrder(o.id, to, ref || undefined),
                      to === "collected" ? "Collected. The parts are now in the store." : undefined,
                    );
                  }}
                >
                  {label}
                </button>
              ))}
            </p>
          </div>
        ))}
      </Card>
      <Card title="New order">
        <form onSubmit={create}>
          <div className="form-grid">
            <Field label="Supplier">
              <select
                value={form.supplier_id}
                onChange={(e) => setForm({ ...form, supplier_id: e.target.value })}
                required
              >
                <option value="">Choose a supplier</option>
                {suppliers
                  .filter((s) => s.is_active)
                  .map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
              </select>
            </Field>
            <Field label="Note to the supplier">
              <input
                value={form.notes}
                onChange={(e) => setForm({ ...form, notes: e.target.value })}
              />
            </Field>
          </div>
          {form.lines.map((l, n) => (
            <div className="form-grid" key={n}>
              <Field label="Store part (optional)">
                <select
                  value={l.part_id}
                  onChange={(e) => {
                    const p = parts.find((x) => x.id === e.target.value);
                    setLine(n, {
                      part_id: e.target.value,
                      description: p ? p.name : l.description,
                      cost: p ? String(p.unit_cost_cents / 100) : l.cost,
                    });
                  }}
                >
                  <option value="">Not a store part</option>
                  {parts.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} ({p.quantity} in store)
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="What">
                <input
                  value={l.description}
                  onChange={(e) => setLine(n, { description: e.target.value })}
                />
              </Field>
              <Field label="How many">
                <input
                  type="number"
                  min="1"
                  value={l.quantity}
                  onChange={(e) => setLine(n, { quantity: e.target.value })}
                />
              </Field>
              <Field label="Price each (KES, if known)">
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={l.cost}
                  onChange={(e) => setLine(n, { cost: e.target.value })}
                />
              </Field>
            </div>
          ))}
          <p className="actions">
            <button
              type="button"
              className="btn"
              onClick={() =>
                setForm({
                  ...form,
                  lines: [...form.lines, { part_id: "", description: "", quantity: "1", cost: "" }],
                })
              }
            >
              Add another line
            </button>{" "}
            <button className="btn primary" type="submit">
              Save order
            </button>
          </p>
        </form>
      </Card>
    </>
  );
}

/** Suppliers and the orders sent to them. */
export default function Suppliers() {
  return (
    <>
      <h2>Suppliers and parts orders</h2>
      <nav className="tabs">
        <NavLink to="/suppliers" end>
          Orders
        </NavLink>
        <NavLink to="/suppliers/list">Suppliers</NavLink>
      </nav>
      <Routes>
        <Route index element={<Orders />} />
        <Route path="list" element={<SupplierList />} />
      </Routes>
    </>
  );
}
