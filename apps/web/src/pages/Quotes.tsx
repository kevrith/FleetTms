import { quote as calculate, type BillingMethod as RuleMethod } from "@fleettms/business-rules";
import type {
  Client,
  Quote,
  QuoteDefaults,
  QuotePreview,
  SavedRoute,
  Vehicle,
} from "@fleettms/types";
import { Check, Send, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { BILLING_METHOD, BILLING_RATE_LABEL, QUOTE_STATUS, kes, nairobiTime } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

const cents = (kesText: string) => Math.round(Number(kesText || 0) * 100);
const toKes = (c: number) => String(c / 100);
const iso = (local: string) => (local ? new Date(local).toISOString() : null);

export function QuoteList() {
  const [rows, setRows] = useState<Quote[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api
      .quotes()
      .then(setRows)
      .catch((e) => setError(errorMessage(e)));
  }, []);
  return (
    <>
      <ErrorBanner message={error} />
      <p className="actions">
        <Link className="btn primary" to="/jobs/quotes/new">
          New quote
        </Link>
      </p>
      <Card title="Quotes">
        {rows.length === 0 && <p className="muted">No quotes yet.</p>}
        {rows.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Quote</th>
                  <th>Client</th>
                  <th>Price</th>
                  <th>Expected profit</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((q) => (
                  <tr key={q.id}>
                    <td>
                      <Link to={`/jobs/quotes/${q.id}`}>{q.number}</Link>
                    </td>
                    <td>{q.client_name}</td>
                    <td>{kes(q.price_cents)}</td>
                    <td>
                      <span className={q.expected_profit_cents < 0 ? "status bad" : ""}>
                        {kes(q.expected_profit_cents)}
                      </span>
                    </td>
                    <td>
                      {q.expired ? "Expired" : QUOTE_STATUS[q.status]}
                      {q.job_number && ` (job ${q.job_number})`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}

interface Form {
  clientId: string;
  routeId: string;
  vehicleId: string;
  cargo: string;
  weight: string;
  trips: string;
  returnEmpty: boolean;
  method: BillingMethod;
  rate: string;
  distance: string;
  kmplLoaded: string;
  kmplEmpty: string;
  fuelPrice: string;
  tolls: string;
  crew: string;
  other: string;
  validDays: string;
  pickup: string;
  deliverBy: string;
  instructions: string;
}
type BillingMethod = RuleMethod;

const blank: Form = {
  clientId: "",
  routeId: "",
  vehicleId: "",
  cargo: "",
  weight: "",
  trips: "1",
  returnEmpty: true,
  method: "per_trip",
  rate: "",
  distance: "",
  kmplLoaded: "4.5",
  kmplEmpty: "6",
  fuelPrice: "",
  tolls: "",
  crew: "",
  other: "",
  validDays: "14",
  pickup: "",
  deliverBy: "",
  instructions: "",
};

const fromDefaults = (d: QuoteDefaults): Partial<Form> => ({
  method: d.billing_method,
  rate: toKes(d.rate_cents),
  distance: String(d.distance_km),
  kmplLoaded: String(d.kmpl_loaded),
  kmplEmpty: String(d.kmpl_empty),
  fuelPrice: d.fuel_price_cents ? toKes(d.fuel_price_cents) : "",
  tolls: toKes(d.tolls_cents),
  crew: toKes(d.crew_cents),
  other: toKes(d.other_cents),
});

const FUEL_SOURCE: Record<string, string> = {
  learned: "Learned from this lorry's own trips",
  history: "From this lorry's own trips on this route and load",
  declared: "The consumption entered for the lorry",
  "fleet average": "The fleet's average",
  "typed in": "Typed in on this quote",
};

/** How the numbers were worked out: where the fuel estimate came from, and for a lorry hired in what its lease charges for the job. */
function QuoteWorking({ p }: { p: QuotePreview }) {
  return (
    <Card title="How this was worked out">
      <h4>Fuel: {p.fuel_source ? FUEL_SOURCE[p.fuel_source] : ""}</h4>
      <ul>
        {p.fuel_detail.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      <ul className="list">
        {p.lines.map((l) => (
          <li key={l.label}>
            <span>{l.total ? <strong>{l.label}</strong> : l.label}</span>
            <span className={l.cents < 0 ? "muted" : undefined}>
              {l.total ? <strong>{kes(l.cents)}</strong> : kes(l.cents)}
            </span>
          </li>
        ))}
      </ul>
      {p.lease_note && <p className="muted">{p.lease_note}</p>}
    </Card>
  );
}

/** Prices a job and shows the expected profit as you type, with the same calculation the server uses. */
export function QuoteForm() {
  const navigate = useNavigate();
  const [clients, setClients] = useState<Client[]>([]);
  const [routes, setRoutes] = useState<SavedRoute[]>([]);
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [f, setF] = useState<Form>(blank);
  const [typedFuel, setTypedFuel] = useState(false);
  const [preview, setPreview] = useState<QuotePreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    Promise.all([api.clients(), api.routes(), api.vehicles().catch(() => [])])
      .then(([c, r, v]) => {
        setClients(c);
        setRoutes(r);
        setVehicles(v);
      })
      .catch((e) => setError(errorMessage(e)));
  }, []);

  /** Choosing a client, route or vehicle fills the form from what is already known. */
  async function choose(patch: Partial<Form>) {
    const next = { ...f, ...patch };
    setF(next);
    setTypedFuel(false);
    if (!next.clientId) return;
    try {
      const d = await api.quoteDefaults(
        next.clientId,
        next.routeId || undefined,
        next.vehicleId || undefined,
      );
      setF((cur) => ({ ...cur, ...patch, ...fromDefaults(d) }));
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  const clientRoutes = routes.filter((r) => r.client_id === f.clientId);
  const live = useMemo(() => {
    const distance = Number(f.distance);
    const fuel = cents(f.fuelPrice);
    if (!distance || !fuel || Number(f.kmplLoaded) <= 0 || Number(f.kmplEmpty) <= 0) return null;
    return calculate({
      method: f.method,
      rate_cents: cents(f.rate),
      distance_km: distance,
      weight_tonnes: Number(f.weight || 0),
      trips: Math.max(1, Number(f.trips) || 1),
      return_empty: f.returnEmpty,
      kmpl_loaded: Number(f.kmplLoaded),
      kmpl_empty: Number(f.kmplEmpty),
      fuel_price_cents: fuel,
      tolls_cents: cents(f.tolls),
      crew_cents: cents(f.crew),
      other_cents: cents(f.other),
    });
  }, [f]);

  const on = (k: keyof Form) => (e: { target: { value: string } }) => {
    if (k === "kmplLoaded" || k === "kmplEmpty") setTypedFuel(true);
    setF({ ...f, [k]: e.target.value });
  };

  /** Asks the server for the working behind the numbers: where the fuel estimate came from, and any lease charge. The server is
   * left to estimate the fuel economy itself unless it was typed in here. */
  const previewKey = JSON.stringify([
    f.clientId,
    f.routeId,
    f.vehicleId,
    f.weight,
    f.trips,
    f.returnEmpty,
    f.method,
    f.rate,
    f.distance,
    f.fuelPrice,
    f.tolls,
    f.crew,
    f.other,
    typedFuel ? [f.kmplLoaded, f.kmplEmpty] : null,
  ]);
  useEffect(() => {
    if (!f.clientId || !Number(f.distance) || !cents(f.rate)) {
      setPreview(null);
      return;
    }
    const timer = setTimeout(() => {
      api
        .previewQuote({
          client_id: f.clientId,
          route_id: f.routeId || null,
          vehicle_id: f.vehicleId || null,
          weight_tonnes: f.weight || "0",
          trips: Math.max(1, Number(f.trips) || 1),
          return_empty: f.returnEmpty,
          billing_method: f.method,
          rate_cents: cents(f.rate),
          distance_km: Number(f.distance),
          fuel_price_cents: cents(f.fuelPrice) || null,
          tolls_cents: cents(f.tolls),
          crew_cents: cents(f.crew),
          other_cents: cents(f.other),
          ...(typedFuel ? { kmpl_loaded: f.kmplLoaded, kmpl_empty: f.kmplEmpty } : {}),
        })
        .then((p) => {
          setPreview(p);
          if (!typedFuel) {
            setF((cur) => ({
              ...cur,
              kmplLoaded: String(p.kmpl_loaded),
              kmplEmpty: String(p.kmpl_empty),
            }));
          }
        })
        .catch(() => setPreview(null));
    }, 500);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [previewKey]);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const q = await api.createQuote({
        client_id: f.clientId,
        route_id: f.routeId || null,
        vehicle_id: f.vehicleId || null,
        cargo_description: f.cargo || null,
        weight_tonnes: f.weight || "0",
        trips: Number(f.trips || 1),
        return_empty: f.returnEmpty,
        billing_method: f.method,
        rate_cents: cents(f.rate),
        distance_km: Number(f.distance),
        ...(typedFuel ? { kmpl_loaded: f.kmplLoaded, kmpl_empty: f.kmplEmpty } : {}),
        fuel_price_cents: cents(f.fuelPrice),
        tolls_cents: cents(f.tolls),
        crew_cents: cents(f.crew),
        other_cents: cents(f.other),
        valid_days: Number(f.validDays || 14),
        pickup_at: iso(f.pickup),
        deliver_by: iso(f.deliverBy),
        instructions: f.instructions || null,
      });
      navigate(`/jobs/quotes/${q.id}`);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <ErrorBanner message={error} />
      <Card title="New quote">
        <div className="form-grid">
          <Field label="Client">
            <select
              value={f.clientId}
              onChange={(e) => choose({ clientId: e.target.value, routeId: "" })}
            >
              <option value="">Choose a client</option>
              {clients.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Saved route">
            <select
              value={f.routeId}
              disabled={!f.clientId}
              onChange={(e) => choose({ routeId: e.target.value })}
            >
              <option value="">No saved route</option>
              {clientRoutes.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name} ({r.distance_km} km)
                </option>
              ))}
            </select>
          </Field>
          <Field label="Lorry (for its fuel economy)">
            <select value={f.vehicleId} onChange={(e) => choose({ vehicleId: e.target.value })}>
              <option value="">Fleet average</option>
              {vehicles.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.registration}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Cargo">
            <input value={f.cargo} onChange={on("cargo")} />
          </Field>
          <Field label="Total weight (tonnes)">
            <input type="number" min="0" step="0.01" value={f.weight} onChange={on("weight")} />
          </Field>
          <Field label="Number of trips">
            <input type="number" min="1" value={f.trips} onChange={on("trips")} />
          </Field>
          <Field label="How it is charged">
            <select
              value={f.method}
              onChange={(e) => setF({ ...f, method: e.target.value as BillingMethod })}
            >
              {Object.entries(BILLING_METHOD).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </Field>
          <Field label={BILLING_RATE_LABEL[f.method] ?? "Rate (KES)"}>
            <input type="number" min="0" step="0.01" value={f.rate} onChange={on("rate")} />
          </Field>
        </div>
        <h4>What it costs us (per trip)</h4>
        <div className="form-grid">
          <Field label="Distance one way (km)">
            <input type="number" min="0" value={f.distance} onChange={on("distance")} />
          </Field>
          <Field label="Comes back empty">
            <select
              value={f.returnEmpty ? "yes" : "no"}
              onChange={(e) => setF({ ...f, returnEmpty: e.target.value === "yes" })}
            >
              <option value="yes">Yes, same distance back</option>
              <option value="no">No return leg</option>
            </select>
          </Field>
          <Field label="Pump price per litre (KES)">
            <input
              type="number"
              min="0"
              step="0.01"
              value={f.fuelPrice}
              onChange={on("fuelPrice")}
            />
          </Field>
          <Field label="Loaded km per litre">
            <input
              type="number"
              min="0"
              step="0.1"
              value={f.kmplLoaded}
              onChange={on("kmplLoaded")}
            />
          </Field>
          <Field label="Empty km per litre">
            <input
              type="number"
              min="0"
              step="0.1"
              value={f.kmplEmpty}
              onChange={on("kmplEmpty")}
            />
          </Field>
          <Field label="Tolls (KES)">
            <input type="number" min="0" step="0.01" value={f.tolls} onChange={on("tolls")} />
          </Field>
          <Field label="Crew (KES)">
            <input type="number" min="0" step="0.01" value={f.crew} onChange={on("crew")} />
          </Field>
          <Field label="Other (KES)">
            <input type="number" min="0" step="0.01" value={f.other} onChange={on("other")} />
          </Field>
        </div>
        <h4>Timing and notes</h4>
        <div className="form-grid">
          <Field label="Pickup">
            <input type="datetime-local" value={f.pickup} onChange={on("pickup")} />
          </Field>
          <Field label="Deliver by">
            <input type="datetime-local" value={f.deliverBy} onChange={on("deliverBy")} />
          </Field>
          <Field label="Valid for (days)">
            <input type="number" min="1" value={f.validDays} onChange={on("validDays")} />
          </Field>
          <Field label="Instructions for the driver">
            <input value={f.instructions} onChange={on("instructions")} />
          </Field>
        </div>
      </Card>
      <Card title="Expected profit">
        {live ? (
          <ul className="list">
            <li>
              <span>Price to the client</span>
              <strong>{kes(live.price_cents)}</strong>
            </li>
            <li>
              <span>
                Fuel ({live.fuel_litres.toLocaleString()} litres per trip: {live.loaded_km} km
                loaded
                {live.empty_km > 0 && `, ${live.empty_km} km empty`})
              </span>
              <strong>{kes(live.fuel_cents)}</strong>
            </li>
            <li>
              <span>All costs per trip</span>
              <strong>{kes(live.cost_per_trip_cents)}</strong>
            </li>
            <li>
              <span>All costs, {f.trips || 1} trip(s)</span>
              <strong>{kes(live.total_cost_cents)}</strong>
            </li>
            <li>
              <span>Expected profit</span>
              <strong className={live.profit_cents < 0 ? "status bad" : "status ok"}>
                {kes(live.profit_cents)}
                {live.margin_pct !== null && ` (${live.margin_pct}%)`}
              </strong>
            </li>
          </ul>
        ) : (
          <p className="muted">
            Choose a client and route, and enter the pump price, to see the profit.
          </p>
        )}
        <p className="actions">
          <button className="btn primary" disabled={busy || !f.clientId || !live} onClick={save}>
            Save quote
          </button>
        </p>
      </Card>
      {preview && <QuoteWorking p={preview} />}
    </>
  );
}

export function QuoteDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [q, setQ] = useState<Quote | null>(null);
  const [channel, setChannel] = useState<"email" | "whatsapp" | "sms">("whatsapp");
  const [recipient, setRecipient] = useState("");
  const [note, setNote] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setQ(await api.quote(id!));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [id]);
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
  if (!q) return <ErrorBanner message={error} />;
  const open = q.status === "draft" || q.status === "sent";
  return (
    <>
      <p>
        <Link to="/jobs/quotes">Back to quotes</Link>
      </p>
      <ErrorBanner message={error} />
      {message && <p className="banner ok">{message}</p>}
      <Card title={`Quote ${q.number} for ${q.client_name}`}>
        <p>
          <strong>{q.expired ? "Expired" : QUOTE_STATUS[q.status]}</strong>
          {q.valid_until && `, valid until ${q.valid_until}`}
          {q.sent_at && `. Sent by ${q.sent_via} to ${q.sent_to} on ${nairobiTime(q.sent_at)}.`}
        </p>
        <ul className="list">
          <li>
            <span>
              {BILLING_METHOD[q.billing_method]}, {q.trips} trip(s), {q.weight_tonnes} t,{" "}
              {q.distance_km} km
              {q.route_name && `, ${q.route_name}`}
            </span>
            <strong>{kes(q.price_cents)}</strong>
          </li>
          <li>
            <span>
              Costs: fuel {kes(q.fuel_cents)} per trip, {kes(q.cost_per_trip_cents)} in all per trip
            </span>
            <strong>{kes(q.total_cost_cents)}</strong>
          </li>
          <li>
            <span>Expected profit</span>
            <strong className={q.expected_profit_cents < 0 ? "status bad" : "status ok"}>
              {kes(q.expected_profit_cents)}
              {q.margin_pct !== null && ` (${q.margin_pct}%)`}
            </strong>
          </li>
          {q.net_profit_cents !== null && (
            <li>
              <span>Expected profit after the lease charge of {kes(q.lease_charge_cents)}</span>
              <strong className={q.net_profit_cents < 0 ? "status bad" : "status ok"}>
                {kes(q.net_profit_cents)}
              </strong>
            </li>
          )}
        </ul>
        {q.job_id && (
          <p>
            Became job <Link to={`/jobs/view/${q.job_id}`}>{q.job_number}</Link>.
          </p>
        )}
      </Card>
      {q.fuel_detail && q.fuel_detail.length > 0 && (
        <Card title="How the costs were worked out">
          <h4>Fuel: {q.fuel_source ? FUEL_SOURCE[q.fuel_source] : ""}</h4>
          <ul>
            {q.fuel_detail.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
          {q.lease_detail && (
            <>
              <h4>The lease charge for this job</h4>
              <ul className="list">
                {q.lease_detail.lines.map((l) => (
                  <li key={l.label}>
                    <span>{l.label}</span>
                    <span>{kes(l.cents)}</span>
                  </li>
                ))}
              </ul>
              <p className="muted">{q.lease_detail.note}</p>
            </>
          )}
        </Card>
      )}
      {open && (
        <Card title="Send to the client">
          <div className="form-grid">
            <Field label="Send by">
              <select
                value={channel}
                onChange={(e) => setChannel(e.target.value as typeof channel)}
              >
                <option value="whatsapp">WhatsApp (PDF)</option>
                <option value="email">Email (PDF)</option>
                <option value="sms">SMS (price only)</option>
              </select>
            </Field>
            <Field label="To (the client's own if left blank)">
              <input value={recipient} onChange={(e) => setRecipient(e.target.value)} />
            </Field>
            <button
              className="btn"
              onClick={() => run(() => api.sendQuote(q.id, channel, recipient), "Quote sent.")}
            >
              <Send size={16} /> Send
            </button>
          </div>
          <h4>The client's answer</h4>
          <div className="form-grid">
            <button
              className="btn primary"
              disabled={q.expired}
              onClick={async () => {
                setError(null);
                try {
                  const done = await api.acceptQuote(q.id);
                  navigate(`/jobs/view/${done.job.id}`);
                } catch (e) {
                  setError(errorMessage(e));
                }
              }}
            >
              <Check size={16} /> Accepted: make it a job
            </button>
            <Field label="Reason (optional)">
              <input value={note} onChange={(e) => setNote(e.target.value)} />
            </Field>
            <button className="btn danger" onClick={() => run(() => api.declineQuote(q.id, note))}>
              <X size={16} /> Declined
            </button>
          </div>
          {q.expired && (
            <p className="muted">This quote has expired. Make a new one to accept it.</p>
          )}
        </Card>
      )}
    </>
  );
}
