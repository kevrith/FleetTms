import type { Part, StockCountResult, StockMovement, UnfittedPart } from "@fleettms/types";
import { ClipboardCheck, Plus } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { kes } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

function AddPart({ onAdded }: { onAdded: () => void }) {
  const [form, setForm] = useState({ name: "", unit: "pcs", reorder: "", supplier: "" });
  const [error, setError] = useState<string | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.addPart({
        name: form.name,
        unit: form.unit || "pcs",
        reorder_level: Number(form.reorder || 0),
        supplier: form.supplier || null,
      });
      setForm({ name: "", unit: "pcs", reorder: "", supplier: "" });
      onAdded();
    } catch (err) {
      setError(errorMessage(err));
    }
  }
  return (
    <Card title="Add a part to the store">
      <ErrorBanner message={error} />
      <form className="form-grid" onSubmit={submit}>
        <Field label="Name">
          <input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            required
          />
        </Field>
        <Field label="Unit">
          <input value={form.unit} onChange={(e) => setForm({ ...form, unit: e.target.value })} />
        </Field>
        <Field label="Reorder at">
          <input
            type="number"
            min="0"
            value={form.reorder}
            onChange={(e) => setForm({ ...form, reorder: e.target.value })}
          />
        </Field>
        <Field label="Supplier">
          <input
            value={form.supplier}
            onChange={(e) => setForm({ ...form, supplier: e.target.value })}
          />
        </Field>
        <button className="btn primary" type="submit">
          <Plus size={16} /> Add part
        </button>
      </form>
    </Card>
  );
}

function Receive({
  part,
  onDone,
  fail,
}: {
  part: Part;
  onDone: () => void;
  fail: (m: string | null) => void;
}) {
  const [qty, setQty] = useState("");
  const [cost, setCost] = useState(String(part.unit_cost_cents / 100));
  return (
    <div className="form-grid">
      <Field label={`Received (${part.unit})`}>
        <input type="number" min="1" value={qty} onChange={(e) => setQty(e.target.value)} />
      </Field>
      <Field label="Unit cost (KES)">
        <input
          type="number"
          min="0"
          step="0.01"
          value={cost}
          onChange={(e) => setCost(e.target.value)}
        />
      </Field>
      <button
        className="btn primary"
        disabled={!(Number(qty) > 0)}
        onClick={async () => {
          fail(null);
          try {
            await api.receivePart(part.id, {
              quantity: Number(qty),
              unit_cost_cents: Math.round(Number(cost || 0) * 100),
            });
            onDone();
          } catch (e) {
            fail(errorMessage(e));
          }
        }}
      >
        Receive stock
      </button>
    </div>
  );
}

function StockCount({ parts, onDone }: { parts: Part[]; onDone: () => void }) {
  const [counted, setCounted] = useState<Record<string, string>>({});
  const [result, setResult] = useState<StockCountResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const lines = parts.filter((p) => counted[p.id] !== undefined && counted[p.id] !== "");
  return (
    <Card title="Stock count">
      <ErrorBanner message={error} />
      <p className="muted">
        Count what is on the shelf and enter it. Differences from the books are corrected and listed
        with their value.
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Part</th>
              <th>In the books</th>
              <th>Counted</th>
            </tr>
          </thead>
          <tbody>
            {parts.map((p) => (
              <tr key={p.id}>
                <td>{p.name}</td>
                <td>{p.quantity}</td>
                <td>
                  <input
                    type="number"
                    min="0"
                    value={counted[p.id] ?? ""}
                    onChange={(e) => setCounted({ ...counted, [p.id]: e.target.value })}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="actions">
        <button
          className="btn primary"
          disabled={lines.length === 0}
          onClick={async () => {
            setError(null);
            try {
              setResult(
                await api.countStock(
                  lines.map((p) => ({ part_id: p.id, counted: Number(counted[p.id]) })),
                ),
              );
              setCounted({});
              onDone();
            } catch (e) {
              setError(errorMessage(e));
            }
          }}
        >
          <ClipboardCheck size={16} /> Save the count
        </button>
      </p>
      {result && (
        <p className={result.variances.length ? "banner bad" : "banner ok"}>
          {result.variances.length === 0
            ? "Every part counted matched the books."
            : result.variances
                .map(
                  (v) =>
                    `${v.name}: ${v.difference > 0 ? "+" : ""}${v.difference} (${kes(v.value_cents)})`,
                )
                .join("; ") + `. Net ${kes(result.net_value_cents)}.`}
        </p>
      )}
    </Card>
  );
}

/** Spare parts store: stock, receiving, reorder alerts, stock counts and the issued-vs-fitted check. */
export default function Parts() {
  const [parts, setParts] = useState<Part[]>([]);
  const [moves, setMoves] = useState<StockMovement[]>([]);
  const [unfitted, setUnfitted] = useState<UnfittedPart[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [p, m, u] = await Promise.all([api.parts(), api.stockMovements(), api.unfittedParts()]);
      setParts(p);
      setMoves(m);
      setUnfitted(u);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const low = parts.filter((p) => p.low_stock);
  const current = parts.find((p) => p.id === selected);
  const name = (id: string) => parts.find((p) => p.id === id)?.name ?? "";
  return (
    <>
      <ErrorBanner message={error} />
      {low.length > 0 && (
        <p className="banner bad">
          Low on stock, time to order: {low.map((p) => `${p.name} (${p.quantity} left)`).join(", ")}
          .
        </p>
      )}
      {unfitted.length > 0 && (
        <Card title="Issued but never marked as fitted">
          <p className="muted">
            Parts taken from the store for a work order that nobody has confirmed as fitted. Check
            the parts really went on the vehicle.
          </p>
          <ul className="list">
            {unfitted.map((u) => (
              <li key={u.id}>
                <span>
                  {u.quantity} x {u.name} for {u.registration}: {u.work_order_title}{" "}
                  {u.closed && <span className="status bad">Work finished</span>}
                </span>
                <strong>{kes(u.value_cents)}</strong>
              </li>
            ))}
          </ul>
        </Card>
      )}
      <Card title="Stock">
        {parts.length === 0 && <p className="muted">No parts in the store yet.</p>}
        {parts.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Part</th>
                  <th>In stock</th>
                  <th>Unit cost</th>
                  <th>Value</th>
                  <th>Reorder at</th>
                </tr>
              </thead>
              <tbody>
                {parts.map((p) => (
                  <tr key={p.id}>
                    <td>
                      <button className="btn" onClick={() => setSelected(p.id)}>
                        {p.name}
                      </button>
                    </td>
                    <td>
                      {p.quantity} {p.unit} {p.low_stock && <span className="status bad">Low</span>}
                    </td>
                    <td>{kes(p.unit_cost_cents)}</td>
                    <td>{kes(p.stock_value_cents)}</td>
                    <td>{p.reorder_level || ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {current && (
        <Card title={`Receive ${current.name}`}>
          <Receive
            key={current.id + current.quantity}
            part={current}
            onDone={load}
            fail={setError}
          />
        </Card>
      )}
      <AddPart onAdded={load} />
      {parts.length > 0 && <StockCount parts={parts} onDone={load} />}
      <Card title="Recent movements">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>When</th>
                <th>Part</th>
                <th>What</th>
                <th>Change</th>
                <th>Balance</th>
              </tr>
            </thead>
            <tbody>
              {moves.slice(0, 30).map((m) => (
                <tr key={m.id}>
                  <td>{new Date(m.created_at).toLocaleString()}</td>
                  <td>{name(m.part_id)}</td>
                  <td>{m.kind}</td>
                  <td>{m.quantity_delta > 0 ? `+${m.quantity_delta}` : m.quantity_delta}</td>
                  <td>{m.balance_after}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
