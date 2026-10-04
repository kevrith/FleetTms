import type { Availability, Client, Job, SavedRoute } from "@fleettms/types";
import { Plus, Repeat, Truck } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import JobSchedules from "./JobSchedules";
import { Link, NavLink, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { BILLING_METHOD, JOB_STATUS, kes, nairobiTime } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";
import Calendar from "./DispatchCalendar";
import { QuoteDetail, QuoteForm, QuoteList } from "./Quotes";

const iso = (local: string) => (local ? new Date(local).toISOString() : null);

function tomorrowAt(hour: number) {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  d.setHours(hour, 0, 0, 0);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function JobList() {
  const { can } = useAuth();
  const money = can("clients.manage") || can("jobs.manage");
  const [rows, setRows] = useState<Job[]>([]);
  const [openOnly, setOpenOnly] = useState(true);
  const [clients, setClients] = useState<Client[]>([]);
  const [routes, setRoutes] = useState<SavedRoute[]>([]);
  const [form, setForm] = useState({
    clientId: "",
    routeId: "",
    cargo: "",
    weight: "",
    trips: "1",
  });
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setRows(await api.jobs({ openOnly }));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [openOnly]);
  useEffect(() => {
    void load();
  }, [load]);
  useEffect(() => {
    if (!can("jobs.manage")) return;
    Promise.all([api.clients(), api.routes()])
      .then(([c, r]) => {
        setClients(c);
        setRoutes(r);
      })
      .catch(() => undefined);
  }, [can]);
  return (
    <>
      <ErrorBanner message={error} />
      <Card title="Jobs">
        <label className="field">
          <span>
            <input
              type="checkbox"
              checked={openOnly}
              onChange={(e) => setOpenOnly(e.target.checked)}
            />{" "}
            Open jobs only
          </span>
        </label>
        {rows.length === 0 && <p className="muted">No jobs.</p>}
        {rows.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Job</th>
                  <th>Client</th>
                  <th>Route</th>
                  <th>Trips</th>
                  <th>Pickup</th>
                  {money && <th>Price</th>}
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((j) => (
                  <tr key={j.id}>
                    <td>
                      <Link to={`/jobs/view/${j.id}`}>{j.number}</Link>
                    </td>
                    <td>{j.client_name}</td>
                    <td>{j.route ? `${j.route.pickup} to ${j.route.dropoff}` : ""}</td>
                    <td>
                      {j.trips_dispatched}/{j.trips_planned} dispatched
                    </td>
                    <td>{nairobiTime(j.pickup_at)}</td>
                    {money && <td>{j.price_cents !== undefined ? kes(j.price_cents) : ""}</td>}
                    <td>{JOB_STATUS[j.status]}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {can("jobs.manage") && (
        <Card title="Set up a job without a quote">
          <p className="muted">
            For a contract job or work agreed by phone. Priced from the client's billing method.
          </p>
          <div className="form-grid">
            <Field label="Client">
              <select
                value={form.clientId}
                onChange={(e) => setForm({ ...form, clientId: e.target.value, routeId: "" })}
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
                value={form.routeId}
                onChange={(e) => setForm({ ...form, routeId: e.target.value })}
              >
                <option value="">Choose a route</option>
                {routes
                  .filter((r) => r.client_id === form.clientId)
                  .map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name}
                    </option>
                  ))}
              </select>
            </Field>
            <Field label="Cargo">
              <input
                value={form.cargo}
                onChange={(e) => setForm({ ...form, cargo: e.target.value })}
              />
            </Field>
            <Field label="Weight (tonnes)">
              <input
                type="number"
                min="0"
                value={form.weight}
                onChange={(e) => setForm({ ...form, weight: e.target.value })}
              />
            </Field>
            <Field label="Trips">
              <input
                type="number"
                min="1"
                value={form.trips}
                onChange={(e) => setForm({ ...form, trips: e.target.value })}
              />
            </Field>
            <button
              className="btn primary"
              disabled={!form.clientId || !form.routeId}
              onClick={async () => {
                setError(null);
                try {
                  await api.createJob({
                    client_id: form.clientId,
                    route_id: form.routeId,
                    cargo_description: form.cargo || null,
                    weight_tonnes: form.weight || "0",
                    trips: Number(form.trips || 1),
                  });
                  setForm({ clientId: "", routeId: "", cargo: "", weight: "", trips: "1" });
                  await load();
                } catch (e) {
                  setError(errorMessage(e));
                }
              }}
            >
              <Plus size={16} /> Create job
            </button>
          </div>
        </Card>
      )}
    </>
  );
}

function Dispatch({ job, onDone }: { job: Job; onDone: () => void }) {
  const [when, setWhen] = useState(tomorrowAt(6));
  const [avail, setAvail] = useState<Availability | null>(null);
  const [vehicleId, setVehicleId] = useState("");
  const [driverId, setDriverId] = useState("");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!when) return;
    api
      .available(new Date(when).toISOString(), 12)
      .then((a) => {
        setAvail(a);
        setVehicleId((cur) =>
          a.vehicles.find((v) => v.id === cur)?.free
            ? cur
            : (a.vehicles.find((v) => v.free)?.id ?? ""),
        );
      })
      .catch((e) => setError(errorMessage(e)));
  }, [when]);
  const left = job.trips_planned - job.trips_dispatched;
  if (left <= 0) return <p className="muted">Every trip of this job has a lorry.</p>;
  return (
    <>
      <ErrorBanner message={error} />
      <p className="muted">
        {left} of {job.trips_planned} trip(s) still need a lorry. Only lorries and crew free for the
        whole trip can be chosen.
      </p>
      <div className="form-grid">
        <Field label="Leaves">
          <input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} />
        </Field>
        <Field label="Lorry">
          <select value={vehicleId} onChange={(e) => setVehicleId(e.target.value)}>
            <option value="">Choose a lorry</option>
            {avail?.vehicles.map((v) => (
              <option key={v.id} value={v.id} disabled={!v.free}>
                {v.registration}
                {v.reason === "in_workshop"
                  ? " (in the workshop)"
                  : v.reason === "booked"
                    ? " (booked)"
                    : ""}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Driver (the lorry's own if blank)">
          <select value={driverId} onChange={(e) => setDriverId(e.target.value)}>
            <option value="">The lorry's driver</option>
            {avail?.crew
              .filter((c) => c.role === "driver")
              .map((c) => (
                <option key={c.membership_id} value={c.membership_id} disabled={!c.free}>
                  {c.name}
                  {!c.free ? " (booked)" : ""}
                </option>
              ))}
          </select>
        </Field>
        <button
          className="btn primary"
          disabled={!vehicleId}
          onClick={async () => {
            setError(null);
            try {
              await api.dispatchJob(job.id, {
                vehicle_id: vehicleId,
                scheduled_for: new Date(when).toISOString(),
                driver_membership_id: driverId || null,
              });
              onDone();
            } catch (e) {
              setError(errorMessage(e));
            }
          }}
        >
          <Truck size={16} /> Dispatch
        </button>
      </div>
    </>
  );
}

function JobDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { can } = useAuth();
  const manage = can("jobs.manage");
  const [job, setJob] = useState<Job | null>(null);
  const [again, setAgain] = useState({ pickup: tomorrowAt(6), deliverBy: tomorrowAt(20) });
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setJob(await api.job(id!));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [id]);
  useEffect(() => {
    void load();
  }, [load]);
  if (!job) return <ErrorBanner message={error} />;
  const closed = job.status === "completed" || job.status === "cancelled";
  return (
    <>
      <p>
        <Link to="/jobs">Back to jobs</Link>
      </p>
      <ErrorBanner message={error} />
      <Card title={`Job ${job.number} for ${job.client_name}`}>
        <p>
          <strong>{JOB_STATUS[job.status]}</strong>, {job.trips_completed}/{job.trips_planned} trips
          done.
        </p>
        <ul className="list">
          {job.route && (
            <li>
              <span>Route</span>
              <span>
                {job.route.name}: {job.route.pickup} to {job.route.dropoff} ({job.route.distance_km}{" "}
                km)
              </span>
            </li>
          )}
          <li>
            <span>Cargo</span>
            <span>
              {job.cargo_description} {job.weight_tonnes > 0 && `(${job.weight_tonnes} t)`}
            </span>
          </li>
          <li>
            <span>Window</span>
            <span>
              {nairobiTime(job.pickup_at)} to {nairobiTime(job.deliver_by)}
            </span>
          </li>
          {job.instructions && (
            <li>
              <span>Instructions</span>
              <span>{job.instructions}</span>
            </li>
          )}
          {job.price_cents !== undefined && (
            <li>
              <span>{BILLING_METHOD[job.billing_method]}</span>
              <strong>
                {kes(job.price_cents)}
                {job.expected_profit_cents != null &&
                  `, expected profit ${kes(job.expected_profit_cents)}`}
              </strong>
            </li>
          )}
        </ul>
        {job.quote_id && (
          <p>
            From <Link to={`/jobs/quotes/${job.quote_id}`}>its quote</Link>.
          </p>
        )}
      </Card>
      <Card title="Trips">
        {(job.trips ?? []).length === 0 && <p className="muted">Nothing dispatched yet.</p>}
        <ul className="list">
          {(job.trips ?? []).map((t) => (
            <li key={t.id}>
              <span>
                <Link to={`/trips/${t.id}`}>{t.registration}</Link>, {t.driver_name}:{" "}
                {nairobiTime(t.scheduled_for)} to {nairobiTime(t.planned_end)}
              </span>
              <span>{t.status.replace("_", " ")}</span>
            </li>
          ))}
        </ul>
      </Card>
      {manage && !closed && (
        <Card title="Dispatch">
          <Dispatch key={job.trips_dispatched} job={job} onDone={load} />
          {job.trips_dispatched === 0 && (
            <p className="actions">
              <button
                className="btn danger"
                onClick={async () => {
                  try {
                    await api.cancelJob(job.id);
                    await load();
                  } catch (e) {
                    setError(errorMessage(e));
                  }
                }}
              >
                Cancel this job
              </button>
            </p>
          )}
        </Card>
      )}
      {manage && (
        <Card title="Do this job again">
          <p className="muted">Same client, cargo, billing and saved route, with new dates.</p>
          <div className="form-grid">
            <Field label="Pickup">
              <input
                type="datetime-local"
                value={again.pickup}
                onChange={(e) => setAgain({ ...again, pickup: e.target.value })}
              />
            </Field>
            <Field label="Deliver by">
              <input
                type="datetime-local"
                value={again.deliverBy}
                onChange={(e) => setAgain({ ...again, deliverBy: e.target.value })}
              />
            </Field>
            <button
              className="btn"
              onClick={async () => {
                setError(null);
                try {
                  const next = await api.repeatJob(job.id, {
                    pickup_at: iso(again.pickup),
                    deliver_by: iso(again.deliverBy),
                  });
                  navigate(`/jobs/view/${next.id}`);
                } catch (e) {
                  setError(errorMessage(e));
                }
              }}
            >
              <Repeat size={16} /> Repeat
            </button>
          </div>
        </Card>
      )}
    </>
  );
}

/** Jobs, quotes and the dispatch calendar: work from quote to dispatched trip. */
export default function JobsArea() {
  const { can } = useAuth();
  return (
    <>
      <h2>Jobs and dispatch</h2>
      <nav className="tabs">
        <NavLink to="/jobs" end>
          Jobs
        </NavLink>
        {can("clients.manage") && <NavLink to="/jobs/quotes">Quotes</NavLink>}
        <NavLink to="/jobs/calendar">Calendar</NavLink>
        <NavLink to="/jobs/schedules">Recurring work</NavLink>
      </nav>
      <Routes>
        <Route index element={<JobList />} />
        <Route path="view/:id" element={<JobDetail />} />
        <Route path="calendar" element={<Calendar />} />
        <Route path="schedules" element={<JobSchedules />} />
        <Route path="quotes" element={<QuoteList />} />
        <Route path="quotes/new" element={<QuoteForm />} />
        <Route path="quotes/:id" element={<QuoteDetail />} />
      </Routes>
    </>
  );
}
