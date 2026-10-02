import type { BillingMethod, Client, SavedRoute } from "@fleettms/types";
import { Plus } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, NavLink, Route, Routes, useParams } from "react-router-dom";
import { api } from "../api";
import { BILLING_METHOD, BILLING_RATE_LABEL, kes } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";
import { useAuth } from "../auth";
import { InvoiceDetail, InvoiceList } from "./Invoices";

const toCents = (kesText: string) => Math.round(Number(kesText || 0) * 100);

interface ClientForm {
  name: string;
  contact_name: string;
  phone: string;
  email: string;
  kra_pin: string;
  billing_method: BillingMethod;
  rate: string;
  payment_terms_days: string;
  vat_pct: string;
  notes: string;
}

const emptyForm: ClientForm = {
  name: "",
  contact_name: "",
  phone: "",
  email: "",
  kra_pin: "",
  billing_method: "per_trip",
  rate: "",
  payment_terms_days: "30",
  vat_pct: "0",
  notes: "",
};

const formFrom = (c: Client): ClientForm => ({
  name: c.name,
  contact_name: c.contact_name ?? "",
  phone: c.phone ?? "",
  email: c.email ?? "",
  kra_pin: c.kra_pin ?? "",
  billing_method: c.billing_method,
  rate: String(c.rate_cents / 100),
  payment_terms_days: String(c.payment_terms_days),
  vat_pct: String(c.vat_pct),
  notes: c.notes ?? "",
});

const payload = (f: ClientForm) => ({
  name: f.name,
  contact_name: f.contact_name || null,
  phone: f.phone || null,
  email: f.email || null,
  kra_pin: f.kra_pin || null,
  billing_method: f.billing_method,
  rate_cents: toCents(f.rate),
  payment_terms_days: Number(f.payment_terms_days || 30),
  vat_pct: f.vat_pct || "0",
  notes: f.notes || null,
});

function ClientFields({ f, set }: { f: ClientForm; set: (f: ClientForm) => void }) {
  const on = (k: keyof ClientForm) => (e: { target: { value: string } }) =>
    set({ ...f, [k]: e.target.value });
  return (
    <div className="form-grid">
      <Field label="Name">
        <input value={f.name} onChange={on("name")} required />
      </Field>
      <Field label="Contact person">
        <input value={f.contact_name} onChange={on("contact_name")} />
      </Field>
      <Field label="Phone">
        <input value={f.phone} onChange={on("phone")} />
      </Field>
      <Field label="Email">
        <input type="email" value={f.email} onChange={on("email")} />
      </Field>
      <Field label="KRA PIN">
        <input value={f.kra_pin} onChange={on("kra_pin")} placeholder="P051234567K" />
      </Field>
      <Field label="How they are charged">
        <select value={f.billing_method} onChange={on("billing_method")}>
          {Object.entries(BILLING_METHOD).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </Field>
      <Field label={BILLING_RATE_LABEL[f.billing_method] ?? "Rate (KES)"}>
        <input type="number" min="0" step="0.01" value={f.rate} onChange={on("rate")} />
      </Field>
      <Field label="Payment terms (days)">
        <input
          type="number"
          min="0"
          value={f.payment_terms_days}
          onChange={on("payment_terms_days")}
        />
      </Field>
      <Field label="VAT added to invoices (%)">
        <input
          type="number"
          min="0"
          max="30"
          step="0.01"
          value={f.vat_pct}
          onChange={on("vat_pct")}
        />
      </Field>
      <Field label="Notes">
        <input value={f.notes} onChange={on("notes")} />
      </Field>
    </div>
  );
}

function ClientList() {
  const [rows, setRows] = useState<Client[]>([]);
  const [form, setForm] = useState<ClientForm>(emptyForm);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setRows(await api.clients());
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
      await api.addClient(payload(form));
      setForm(emptyForm);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }
  return (
    <>
      <ErrorBanner message={error} />
      <Card title="Clients">
        {rows.length === 0 && <p className="muted">No clients yet.</p>}
        {rows.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Client</th>
                  <th>Contact</th>
                  <th>Charged</th>
                  <th>Saved routes</th>
                  <th>Open jobs</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((c) => (
                  <tr key={c.id}>
                    <td>
                      <Link to={`view/${c.id}`}>{c.name}</Link>
                    </td>
                    <td>{[c.contact_name, c.phone].filter(Boolean).join(", ")}</td>
                    <td>
                      {BILLING_METHOD[c.billing_method]} {c.rate_cents > 0 && kes(c.rate_cents)}
                    </td>
                    <td>{c.routes}</td>
                    <td>{c.open_jobs}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <Card title="Add a client">
        <form onSubmit={add}>
          <ClientFields f={form} set={setForm} />
          <p className="actions">
            <button className="btn primary" type="submit">
              <Plus size={16} /> Add client
            </button>
          </p>
        </form>
      </Card>
    </>
  );
}

interface RouteForm {
  name: string;
  pickup: string;
  dropoff: string;
  distance_km: string;
  expected_hours: string;
  tolls: string;
  crew: string;
  other: string;
  lat: string;
  lng: string;
  radius: string;
  path_notes: string;
}
const emptyRoute: RouteForm = {
  name: "",
  pickup: "",
  dropoff: "",
  distance_km: "",
  expected_hours: "12",
  tolls: "",
  crew: "",
  other: "",
  lat: "",
  lng: "",
  radius: "500",
  path_notes: "",
};
const routePayload = (f: RouteForm) => ({
  name: f.name,
  pickup: f.pickup,
  dropoff: f.dropoff,
  distance_km: Number(f.distance_km || 0),
  expected_hours: Number(f.expected_hours || 12),
  tolls_cents: toCents(f.tolls),
  crew_cents: toCents(f.crew),
  other_cents: toCents(f.other),
  dropoff_lat: f.lat ? Number(f.lat) : null,
  dropoff_lng: f.lng ? Number(f.lng) : null,
  site_radius_m: Number(f.radius || 500),
  path_notes: f.path_notes || null,
});

function RouteFields({ f, set }: { f: RouteForm; set: (f: RouteForm) => void }) {
  const on = (k: keyof RouteForm) => (e: { target: { value: string } }) =>
    set({ ...f, [k]: e.target.value });
  return (
    <div className="form-grid">
      <Field label="Route name">
        <input value={f.name} onChange={on("name")} required />
      </Field>
      <Field label="Pickup">
        <input value={f.pickup} onChange={on("pickup")} required />
      </Field>
      <Field label="Drop-off">
        <input value={f.dropoff} onChange={on("dropoff")} required />
      </Field>
      <Field label="Distance one way (km)">
        <input type="number" min="0" value={f.distance_km} onChange={on("distance_km")} required />
      </Field>
      <Field label="Usually takes (hours)">
        <input
          type="number"
          min="1"
          step="0.5"
          value={f.expected_hours}
          onChange={on("expected_hours")}
        />
      </Field>
      <Field label="Tolls per trip (KES)">
        <input type="number" min="0" step="0.01" value={f.tolls} onChange={on("tolls")} />
      </Field>
      <Field label="Crew cost per trip (KES)">
        <input type="number" min="0" step="0.01" value={f.crew} onChange={on("crew")} />
      </Field>
      <Field label="Other costs per trip (KES)">
        <input type="number" min="0" step="0.01" value={f.other} onChange={on("other")} />
      </Field>
      <Field label="Client site latitude">
        <input
          type="number"
          step="0.00001"
          value={f.lat}
          onChange={on("lat")}
          placeholder="-1.29210"
        />
      </Field>
      <Field label="Client site longitude">
        <input
          type="number"
          step="0.00001"
          value={f.lng}
          onChange={on("lng")}
          placeholder="36.82190"
        />
      </Field>
      <Field label="Site radius (metres)">
        <input type="number" min="50" value={f.radius} onChange={on("radius")} />
      </Field>
      <Field label="Preferred path and notes">
        <input value={f.path_notes} onChange={on("path_notes")} />
      </Field>
    </div>
  );
}

function ClientDetail() {
  const { id } = useParams();
  const [client, setClient] = useState<Client | null>(null);
  const [form, setForm] = useState<ClientForm>(emptyForm);
  const [route, setRoute] = useState<RouteForm>(emptyRoute);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      const c = await api.client(id!);
      setClient(c);
      setForm(formFrom(c));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [id]);
  useEffect(() => {
    void load();
  }, [load]);
  async function run(action: () => Promise<unknown>, after?: () => void) {
    setError(null);
    setSaved(false);
    try {
      await action();
      after?.();
      await load();
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  if (!client) return <ErrorBanner message={error} />;
  const routes: SavedRoute[] = client.route_list ?? [];
  return (
    <>
      <p>
        <Link to="/clients">Back to clients</Link>
      </p>
      <ErrorBanner message={error} />
      <Card title={client.name}>
        <ClientFields f={form} set={setForm} />
        <p className="actions">
          <button
            className="btn primary"
            onClick={() =>
              run(
                () => api.updateClient(client.id, payload(form)),
                () => setSaved(true),
              )
            }
          >
            Save
          </button>
          {saved && <span className="muted">Saved.</span>}
        </p>
      </Card>
      <Card title="Saved routes">
        <p className="muted">Stored once, then reused on every quote and job for this client.</p>
        {routes.length === 0 && <p className="muted">No routes yet.</p>}
        {routes.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Route</th>
                  <th>Distance</th>
                  <th>Usually takes</th>
                  <th>Costs per trip</th>
                  <th>Notes</th>
                </tr>
              </thead>
              <tbody>
                {routes.map((r) => (
                  <tr key={r.id}>
                    <td>
                      {r.name}
                      <br />
                      <span className="muted">
                        {r.pickup} to {r.dropoff}
                      </span>
                    </td>
                    <td>{r.distance_km.toLocaleString()} km</td>
                    <td>{r.expected_hours} h</td>
                    <td>{kes(r.tolls_cents + r.crew_cents + r.other_cents)} before fuel</td>
                    <td>{r.path_notes}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <h4>Add a route</h4>
        <RouteFields f={route} set={setRoute} />
        <p className="actions">
          <button
            className="btn primary"
            disabled={!route.name || !route.pickup || !route.dropoff || route.distance_km === ""}
            onClick={() =>
              run(
                () => api.addRoute(client.id, routePayload(route)),
                () => setRoute(emptyRoute),
              )
            }
          >
            <Plus size={16} /> Save route
          </button>
        </p>
      </Card>
    </>
  );
}

/** Clients and their saved routes, and the invoices raised to them. */
export default function Clients() {
  const { can } = useAuth();
  return (
    <>
      <h2>Clients and invoices</h2>
      <nav className="tabs">
        <NavLink to="/clients" end>
          Clients
        </NavLink>
        {can("invoices.manage") && <NavLink to="/clients/invoices">Invoices</NavLink>}
      </nav>
      <Routes>
        <Route index element={<ClientList />} />
        <Route path="view/:id" element={<ClientDetail />} />
        {can("invoices.manage") && <Route path="invoices" element={<InvoiceList />} />}
        {can("invoices.manage") && <Route path="invoices/:id" element={<InvoiceDetail />} />}
      </Routes>
    </>
  );
}
