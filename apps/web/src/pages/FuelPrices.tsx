import type { FuelPrices } from "@fleettms/types";
import { Download, Plus } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { kes, todayIso } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

const toCents = (text: string) => Math.round(Number(text || 0) * 100);
const monthStart = () => `${todayIso().slice(0, 7)}-01`;

function monthName(iso: string): string {
  return new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-KE", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}

/** EPRA's monthly pump price for the business's town: what a new quote starts from. */
export default function FuelPricesPage() {
  const { can } = useAuth();
  const [data, setData] = useState<FuelPrices | null>(null);
  const [form, setForm] = useState({
    month: monthStart(),
    region: "Nairobi",
    diesel: "",
    petrol: "",
  });
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const manage = can("clients.manage");
  const load = useCallback(async () => {
    try {
      const d = await api.fuelPrices();
      setData(d);
      setForm((f) => ({ ...f, region: d.region }));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  async function run(action: () => Promise<unknown>, done: string) {
    setError(null);
    setMessage(null);
    try {
      await action();
      setMessage(done);
      await load();
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  function add(e: FormEvent) {
    e.preventDefault();
    void run(
      () =>
        api.saveFuelPrice({
          month: form.month,
          region: form.region,
          diesel_cents: toCents(form.diesel),
          petrol_cents: toCents(form.petrol),
        }),
      "Price saved.",
    );
  }
  return (
    <>
      <ErrorBanner message={error} />
      {message && (
        <p className="banner ok" role="status">
          {message}
        </p>
      )}
      <Card title="Pump price for quotes">
        {data?.current ? (
          <p>
            Diesel in <strong>{data.current.region}</strong>:{" "}
            <strong>{kes(data.current.cents)} a litre</strong>{" "}
            <span className="muted">
              ({monthName(data.current.month)},{" "}
              {data.current.source === "epra" ? "fetched" : "typed in"})
              {data.current_petrol && `. Petrol ${kes(data.current_petrol.cents)} a litre.`}
            </span>
          </p>
        ) : (
          <p className="muted">
            No price yet. Quotes use the average of your latest fuel receipts until you add EPRA's
            price for the month.
          </p>
        )}
        {manage && data && (
          <div className="form-grid">
            <Field label="Quotes start from the price in">
              <select
                value={data.region}
                onChange={(e) => void run(() => api.setFuelRegion(e.target.value), "Town changed.")}
              >
                {data.regions.map((r) => (
                  <option key={r}>{r}</option>
                ))}
              </select>
            </Field>
            <button
              className="btn"
              type="button"
              onClick={() => void run(() => api.fetchFuelPrices(), "Prices fetched.")}
            >
              <Download size={16} /> Fetch this month's prices
            </button>
          </div>
        )}
      </Card>
      {manage && data && (
        <Card title="Add a month's price">
          <p className="muted">
            EPRA announces new pump prices on the 14th of each month. Type in the price for your
            town per litre; a month and town already saved is replaced.
          </p>
          <form className="form-grid" onSubmit={add}>
            <Field label="Month">
              <input
                type="month"
                value={form.month.slice(0, 7)}
                onChange={(e) => setForm({ ...form, month: `${e.target.value}-01` })}
                required
              />
            </Field>
            <Field label="Town">
              <select
                value={form.region}
                onChange={(e) => setForm({ ...form, region: e.target.value })}
              >
                {data.regions.map((r) => (
                  <option key={r}>{r}</option>
                ))}
              </select>
            </Field>
            <Field label="Diesel (KES a litre)">
              <input
                type="number"
                step="0.01"
                min="1"
                value={form.diesel}
                onChange={(e) => setForm({ ...form, diesel: e.target.value })}
                required
              />
            </Field>
            <Field label="Petrol (KES a litre)">
              <input
                type="number"
                step="0.01"
                min="1"
                value={form.petrol}
                onChange={(e) => setForm({ ...form, petrol: e.target.value })}
                required
              />
            </Field>
            <button className="btn primary" type="submit">
              <Plus size={16} /> Save price
            </button>
          </form>
        </Card>
      )}
      <Card title="Prices">
        {data && data.prices.length === 0 && <p className="muted">Nothing saved yet.</p>}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Month</th>
                <th>Town</th>
                <th>Diesel</th>
                <th>Petrol</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {data?.prices.map((p) => (
                <tr key={p.id}>
                  <td>{monthName(p.month)}</td>
                  <td>{p.region}</td>
                  <td>{kes(p.diesel_cents)}</td>
                  <td>{kes(p.petrol_cents)}</td>
                  <td>{p.source === "epra" ? "Fetched" : "Typed in"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
