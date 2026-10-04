import type {
  PlatformBusinessDetail,
  PlatformBusinessRow,
  PlatformOverview,
} from "@fleettms/types";
import { useCallback, useEffect, useState } from "react";
import { NavLink, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { kes, nairobiTime } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";
import Breaches from "./Breaches";
import Partners from "./Partners";
import UsageReport from "./UsageReport";

const STATE: Record<string, [string, string]> = {
  trialing: ["On trial", "warn"],
  active: ["Paying", "ok"],
  grace: ["Overdue (grace)", "warn"],
  read_only: ["Read-only", "bad"],
  suspended: ["Suspended", "bad"],
  complimentary: ["Free", "ok"],
};

function Overview() {
  const [o, setO] = useState<PlatformOverview | null>(null);
  const [health, setHealth] = useState<{
    database: boolean;
    redis: boolean;
    version: string;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api
      .platformOverview()
      .then(setO)
      .catch((e) => setError(errorMessage(e)));
    void (async () => {
      try {
        setHealth(await api.platformHealth());
      } catch {
        setHealth(null);
      }
    })();
  }, []);
  return (
    <>
      <ErrorBanner message={error} />
      {o && (
        <>
          <Card title="Customers">
            <p>
              <strong>{o.businesses}</strong> businesses, <strong>{o.vehicles}</strong> vehicles.
              Recurring revenue from those paying: <strong>{kes(o.mrr_cents)}</strong> a month.{" "}
              {o.open_invoices} invoice(s) waiting for payment.
            </p>
            <ul className="list">
              {Object.entries(o.by_state).map(([k, n]) => (
                <li key={k}>
                  <span className={`status ${STATE[k]?.[1] ?? ""}`}>{STATE[k]?.[0] ?? k}</span>
                  <span>{n}</span>
                </li>
              ))}
            </ul>
          </Card>
          {(o.breaches_open ?? 0) > 0 && (
            <Card title="Data breaches">
              <p>
                {o.breaches_open} open.{" "}
                <span className={`status ${(o.breaches_overdue ?? 0) > 0 ? "bad" : "ok"}`}>
                  {o.breaches_overdue ?? 0} past the Commissioner's 72 hours
                </span>{" "}
                <NavLink to="/platform/breaches">Open the register</NavLink>
              </p>
            </Card>
          )}
          <Card title="Vehicles by plan">
            <ul className="list">
              {Object.entries(o.vehicles_by_plan).map(([k, n]) => (
                <li key={k}>
                  <span>{k}</span>
                  <span>{n}</span>
                </li>
              ))}
            </ul>
          </Card>
        </>
      )}
      {health && (
        <Card title="Platform health">
          <p>
            Database{" "}
            <span className={`status ${health.database ? "ok" : "bad"}`}>
              {health.database ? "up" : "down"}
            </span>
            , job queue{" "}
            <span className={`status ${health.redis ? "ok" : "bad"}`}>
              {health.redis ? "up" : "down"}
            </span>
            , version {health.version}
          </p>
        </Card>
      )}
    </>
  );
}

function Businesses() {
  const navigate = useNavigate();
  const [rows, setRows] = useState<PlatformBusinessRow[]>([]);
  const [state, setState] = useState("");
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api
      .platformBusinesses(state || undefined, q || undefined)
      .then(setRows)
      .catch((e) => setError(errorMessage(e)));
  }, [state, q]);
  return (
    <Card title="Businesses">
      <ErrorBanner message={error} />
      <div className="form-grid">
        <Field label="State">
          <select value={state} onChange={(e) => setState(e.target.value)}>
            <option value="">All</option>
            {Object.entries(STATE).map(([k, [label]]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Name">
          <input value={q} onChange={(e) => setQ(e.target.value)} />
        </Field>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Business</th>
              <th>State</th>
              <th>Vehicles</th>
              <th>People</th>
              <th>A month</th>
              <th>Joined</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr
                key={r.id}
                onClick={() => navigate(`/platform/${r.id}`)}
                style={{ cursor: "pointer" }}
              >
                <td>{r.name}</td>
                <td>
                  <span className={`status ${STATE[r.state]?.[1] ?? ""}`}>
                    {STATE[r.state]?.[0] ?? r.state}
                  </span>
                </td>
                <td>
                  {r.vehicles}{" "}
                  <span className="muted">
                    {Object.entries(r.plans)
                      .map(([p, n]) => `${n} ${p}`)
                      .join(", ")}
                  </span>
                </td>
                <td>{r.people}</td>
                <td>{kes(r.monthly_cents)}</td>
                <td>{nairobiTime(r.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function Detail() {
  const { id } = useParams();
  const [b, setB] = useState<PlatformBusinessDetail | null>(null);
  const [days, setDays] = useState("14");
  const [reason, setReason] = useState("");
  const [price, setPrice] = useState("");
  const [reference, setReference] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setB(await api.platformBusiness(id!));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [id]);
  useEffect(() => {
    void load();
  }, [load]);
  async function act(work: () => Promise<unknown>, done: string) {
    setError(null);
    setMessage(null);
    try {
      await work();
      setMessage(done);
      await load();
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  if (!b) return <ErrorBanner message={error} />;
  const why = reason.trim().length >= 3;
  return (
    <>
      <ErrorBanner message={error} />
      {message && <p className="banner ok">{message}</p>}
      <Card title={b.name}>
        <p>
          <span className={`status ${STATE[b.state]?.[1] ?? ""}`}>
            {STATE[b.state]?.[0] ?? b.state}
          </span>{" "}
          {b.owner && (
            <span className="muted">
              Owner: {b.owner.name} {b.owner.email ?? ""} {b.owner.phone ?? ""}
            </span>
          )}
        </p>
        <p className="muted">
          {b.vehicles} vehicles (
          {Object.entries(b.plans)
            .map(([p, n]) => `${n} ${p}`)
            .join(", ") || "none"}
          ), {b.people} people, {kes(b.monthly_cents)} a month. Trial ends{" "}
          {b.trial_ends_at ? nairobiTime(b.trial_ends_at) : "-"}, paid until{" "}
          {b.paid_until ? nairobiTime(b.paid_until) : "never"}.
          {b.suspended_reason && ` Suspended: ${b.suspended_reason}.`}
        </p>
        <p className="muted">
          You see customer facts only. To look inside this business, it must grant support access.
          Everything you change is written to its own audit trail.
        </p>
      </Card>
      <Card title="What you can do">
        <div className="form-grid">
          <Field label="Reason (kept in their audit trail)">
            <input value={reason} onChange={(e) => setReason(e.target.value)} minLength={3} />
          </Field>
          <Field label="Extend the trial by (days)">
            <input
              type="number"
              min="1"
              max="90"
              value={days}
              onChange={(e) => setDays(e.target.value)}
            />
          </Field>
          <Field label="Agreed monthly price for a large fleet (KES)">
            <input
              type="number"
              min="1000"
              value={price}
              onChange={(e) => setPrice(e.target.value)}
            />
          </Field>
        </div>
        <p className="actions">
          <button
            className="btn"
            type="button"
            disabled={!why}
            onClick={() =>
              act(
                () => api.platformAct(b.id, "extend-trial", { days: Number(days), reason }),
                "Trial extended.",
              )
            }
          >
            Extend the trial
          </button>
          <button
            className="btn"
            type="button"
            disabled={!price}
            onClick={() =>
              act(
                () =>
                  api.platformAct(b.id, "custom-price", {
                    monthly_cents: Math.round(Number(price) * 100),
                  }),
                "Price set.",
              )
            }
          >
            Set the agreed price
          </button>
          <button
            className="btn"
            type="button"
            disabled={!why}
            onClick={() =>
              act(
                () => api.platformAct(b.id, "complimentary", { value: !b.complimentary, reason }),
                b.complimentary ? "Billing switched on." : "Now a free account.",
              )
            }
          >
            {b.complimentary ? "Start billing them" : "Make it a free account"}
          </button>
          {b.suspended ? (
            <button
              className="btn"
              type="button"
              onClick={() => act(() => api.platformAct(b.id, "unsuspend"), "Account released.")}
            >
              Release the hold
            </button>
          ) : (
            <button
              className="btn"
              type="button"
              disabled={!why}
              onClick={() =>
                act(
                  () => api.platformAct(b.id, "suspend", { reason }),
                  "Account put on hold (read-only).",
                )
              }
            >
              Put it on hold
            </button>
          )}
        </p>
      </Card>
      <Card title="Invoices">
        {b.invoices.length === 0 && <p className="muted">None.</p>}
        <ul className="list">
          {b.invoices.map((i) => (
            <li key={i.id}>
              <span>
                {i.number} ({i.kind}) {kes(i.total_cents)}{" "}
                <span className={`status ${i.status === "paid" ? "ok" : "warn"}`}>{i.status}</span>
                {i.payment_method && <span className="muted"> by {i.payment_method}</span>}
              </span>
              {i.status === "issued" && (
                <span className="actions">
                  <input
                    value={reference}
                    onChange={(e) => setReference(e.target.value)}
                    placeholder="Bank reference"
                    aria-label="Bank reference"
                  />
                  <button
                    className="btn"
                    type="button"
                    disabled={reference.trim().length < 3}
                    onClick={() =>
                      act(() => api.platformMarkPaid(i.id, reference), "Marked as paid.")
                    }
                  >
                    Mark paid (bank)
                  </button>
                </span>
              )}
            </li>
          ))}
        </ul>
      </Card>
    </>
  );
}

/** The platform admin console: how the businesses on the platform are doing as customers. */
export default function Platform() {
  return (
    <>
      <h2>Platform console</h2>
      <nav className="tabs">
        <NavLink to="/platform" end>
          Overview
        </NavLink>
        <NavLink to="/platform/businesses">Businesses</NavLink>
        <NavLink to="/platform/partners">Partners</NavLink>
        <NavLink to="/platform/usage">Usage</NavLink>
        <NavLink to="/platform/breaches">Data breaches</NavLink>
      </nav>
      <Routes>
        <Route index element={<Overview />} />
        <Route path="businesses" element={<Businesses />} />
        <Route path="breaches" element={<Breaches />} />
        <Route path="partners" element={<Partners />} />
        <Route path="usage" element={<UsageReport />} />
        <Route path=":id" element={<Detail />} />
      </Routes>
    </>
  );
}
