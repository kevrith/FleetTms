import type {
  ClaimStatus,
  FinesSummary,
  Incident,
  IncidentType,
  InsuranceClaim,
  SosAlert,
  Vehicle,
} from "@fleettms/types";
import { Check, ExternalLink, Plus, Siren } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, NavLink, Navigate, Route, Routes, useParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { CLAIM_STATUS, INCIDENT_TYPE, kes } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

const when = (iso: string) => new Date(iso).toLocaleString();
const FINE_TYPES: IncidentType[] = ["traffic_fine", "county_cess", "police_stop"];

function RecordIncident({ vehicles, onDone }: { vehicles: Vehicle[]; onDone: () => void }) {
  const [form, setForm] = useState({
    type: "traffic_fine" as IncidentType,
    vehicleId: vehicles[0]?.id ?? "",
    description: "",
    fine: "",
    payer: "business" as "business" | "driver",
    reference: "",
  });
  const [error, setError] = useState<string | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const fine = Number(form.fine);
      await api.reportIncident({
        type: form.type,
        vehicle_id: form.vehicleId || null,
        description: form.description || null,
        ...(FINE_TYPES.includes(form.type) && fine > 0
          ? {
              fine_amount_cents: Math.round(fine * 100),
              fine_payer: form.payer,
              deduct_from_payroll: form.payer === "driver",
              reference: form.reference || null,
            }
          : {}),
      });
      setForm({ ...form, description: "", fine: "", reference: "" });
      onDone();
    } catch (err) {
      setError(errorMessage(err));
    }
  }
  return (
    <Card title="Record an incident">
      <ErrorBanner message={error} />
      <form className="form-grid" onSubmit={submit}>
        <Field label="What happened">
          <select
            value={form.type}
            onChange={(e) => setForm({ ...form, type: e.target.value as IncidentType })}
          >
            {Object.entries(INCIDENT_TYPE).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Vehicle">
          <select
            value={form.vehicleId}
            onChange={(e) => setForm({ ...form, vehicleId: e.target.value })}
          >
            {vehicles.map((v) => (
              <option key={v.id} value={v.id}>
                {v.registration}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Notes">
          <input
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
          />
        </Field>
        {FINE_TYPES.includes(form.type) && (
          <>
            <Field label="Fine (KES)">
              <input
                type="number"
                min="0"
                step="0.01"
                value={form.fine}
                onChange={(e) => setForm({ ...form, fine: e.target.value })}
              />
            </Field>
            <Field label="Who pays">
              <select
                value={form.payer}
                onChange={(e) =>
                  setForm({ ...form, payer: e.target.value as "business" | "driver" })
                }
              >
                <option value="business">The business</option>
                <option value="driver">The driver (deduct from pay)</option>
              </select>
            </Field>
            <Field label="Ticket number">
              <input
                value={form.reference}
                onChange={(e) => setForm({ ...form, reference: e.target.value })}
              />
            </Field>
          </>
        )}
        <button className="btn primary" type="submit">
          <Plus size={16} /> Record
        </button>
      </form>
    </Card>
  );
}

function IncidentList() {
  const { can } = useAuth();
  const [rows, setRows] = useState<Incident[]>([]);
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [type, setType] = useState<IncidentType | "">("");
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setRows(await api.incidents(type ? { type } : {}));
      setVehicles(await api.vehicles());
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [type]);
  useEffect(() => {
    void load();
  }, [load]);
  return (
    <>
      <ErrorBanner message={error} />
      <Card title="Incidents">
        <Field label="Show">
          <select value={type} onChange={(e) => setType(e.target.value as IncidentType | "")}>
            <option value="">Everything</option>
            {Object.entries(INCIDENT_TYPE).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </Field>
        {rows.length === 0 && <p className="muted">Nothing reported.</p>}
        {rows.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>When</th>
                  <th>What</th>
                  <th>Vehicle</th>
                  <th>Driver</th>
                  <th>Fine</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((i) => (
                  <tr key={i.id}>
                    <td>{when(i.occurred_at)}</td>
                    <td>
                      <Link to={`/incidents/view/${i.id}`}>{INCIDENT_TYPE[i.type]}</Link>
                    </td>
                    <td>{i.registration}</td>
                    <td>{i.driver_name}</td>
                    <td>{i.fine_amount_cents ? kes(i.fine_amount_cents) : ""}</td>
                    <td>{i.status === "open" ? "Open" : "Closed"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {can("incidents.manage") && <RecordIncident vehicles={vehicles} onDone={load} />}
    </>
  );
}

function ClaimCard({ claim, onChanged }: { claim: InsuranceClaim; onChanged: () => void }) {
  const [status, setStatus] = useState<ClaimStatus>(claim.status);
  const [paid, setPaid] = useState(
    claim.amount_paid_cents ? String(claim.amount_paid_cents / 100) : "",
  );
  const [claimNo, setClaimNo] = useState(claim.claim_no ?? "");
  const [error, setError] = useState<string | null>(null);
  return (
    <div>
      <ErrorBanner message={error} />
      <p>
        <strong>{claim.insurer}</strong>
        {claim.policy_no && `, policy ${claim.policy_no}`}
        {claim.amount_claimed_cents !== null && `, claimed ${kes(claim.amount_claimed_cents)}`}
      </p>
      <div className="form-grid">
        <Field label="Status">
          <select value={status} onChange={(e) => setStatus(e.target.value as ClaimStatus)}>
            {Object.entries(CLAIM_STATUS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Claim number">
          <input value={claimNo} onChange={(e) => setClaimNo(e.target.value)} />
        </Field>
        <Field label="Paid by insurer (KES)">
          <input
            type="number"
            min="0"
            step="0.01"
            value={paid}
            onChange={(e) => setPaid(e.target.value)}
          />
        </Field>
        <button
          className="btn primary"
          onClick={async () => {
            setError(null);
            try {
              await api.updateClaim(claim.id, {
                status,
                claim_no: claimNo || undefined,
                amount_paid_cents: paid === "" ? undefined : Math.round(Number(paid) * 100),
              });
              onChanged();
            } catch (e) {
              setError(errorMessage(e));
            }
          }}
        >
          Save
        </button>
      </div>
    </div>
  );
}

function IncidentDetail() {
  const { id } = useParams();
  const { can } = useAuth();
  const manage = can("incidents.manage");
  const [i, setI] = useState<Incident | null>(null);
  const [note, setNote] = useState("");
  const [cost, setCost] = useState("");
  const [claim, setClaim] = useState({ insurer: "", policy: "", amount: "" });
  const [fine, setFine] = useState({
    amount: "",
    payer: "business" as "business" | "driver",
    reference: "",
  });
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      const next = await api.incident(id!);
      setI(next);
      setFine({
        amount: next.fine_amount_cents ? String(next.fine_amount_cents / 100) : "",
        payer: next.fine_payer ?? "business",
        reference: next.reference ?? "",
      });
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [id]);
  useEffect(() => {
    void load();
  }, [load]);
  async function run(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
      await load();
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  if (!i) return <ErrorBanner message={error} />;
  return (
    <>
      <ErrorBanner message={error} />
      <Card title={`${INCIDENT_TYPE[i.type]}: ${i.registration ?? "no vehicle"}`}>
        <p>
          {when(i.occurred_at)}, {i.driver_name ?? "driver not recorded"}.{" "}
          {i.status === "open" ? "Open." : `Closed. ${i.resolution_note ?? ""}`}
        </p>
        {i.description && <p>{i.description}</p>}
        {i.lat !== null && i.lng !== null && (
          <p>
            <a
              href={`https://maps.google.com/?q=${i.lat},${i.lng}`}
              target="_blank"
              rel="noreferrer"
            >
              <ExternalLink size={14} /> Where it happened
            </a>
          </p>
        )}
        {i.work_order_id && (
          <p>
            An urgent work order was raised. <Link to="/workshop/orders">Open work orders</Link>
          </p>
        )}
        <div className="photos">
          {i.photos.map((p) => (
            <a key={p.id} href={api.mediaUrl(p.url)} target="_blank" rel="noreferrer">
              <img src={api.mediaUrl(p.url)} alt="Incident" style={{ maxWidth: 220, margin: 4 }} />
            </a>
          ))}
        </div>
        {manage && i.status === "open" && (
          <div className="form-grid">
            <Field label="Resolution note">
              <input value={note} onChange={(e) => setNote(e.target.value)} />
            </Field>
            <Field label="Cost to the business (KES)">
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
              onClick={() =>
                run(() =>
                  api.resolveIncident(i.id, {
                    note: note || undefined,
                    cost_cents: cost === "" ? undefined : Math.round(Number(cost) * 100),
                  }),
                )
              }
            >
              <Check size={16} /> Close this incident
            </button>
          </div>
        )}
      </Card>
      {manage && FINE_TYPES.includes(i.type) && (
        <Card title="Fine">
          <p className="muted">
            A fine the business pays becomes a cost on the vehicle. One the driver pays is flagged
            for deduction from pay.
          </p>
          <div className="form-grid">
            <Field label="Amount (KES)">
              <input
                type="number"
                min="0"
                step="0.01"
                value={fine.amount}
                onChange={(e) => setFine({ ...fine, amount: e.target.value })}
              />
            </Field>
            <Field label="Who pays">
              <select
                value={fine.payer}
                onChange={(e) =>
                  setFine({ ...fine, payer: e.target.value as "business" | "driver" })
                }
              >
                <option value="business">The business</option>
                <option value="driver">The driver (deduct from pay)</option>
              </select>
            </Field>
            <Field label="Ticket number">
              <input
                value={fine.reference}
                onChange={(e) => setFine({ ...fine, reference: e.target.value })}
              />
            </Field>
            <button
              className="btn primary"
              onClick={() =>
                run(() =>
                  api.setFine(i.id, {
                    fine_amount_cents:
                      Number(fine.amount) > 0 ? Math.round(Number(fine.amount) * 100) : null,
                    fine_payer: Number(fine.amount) > 0 ? fine.payer : null,
                    deduct_from_payroll: fine.payer === "driver",
                    reference: fine.reference || undefined,
                  }),
                )
              }
            >
              Save fine
            </button>
          </div>
        </Card>
      )}
      {manage && ["accident", "cargo_theft", "breakdown"].includes(i.type) && (
        <Card title="Insurance claims">
          {(i.claims ?? []).map((c) => (
            <ClaimCard key={c.id + c.status} claim={c} onChanged={load} />
          ))}
          <h4>File a claim</h4>
          <div className="form-grid">
            <Field label="Insurer">
              <input
                value={claim.insurer}
                onChange={(e) => setClaim({ ...claim, insurer: e.target.value })}
              />
            </Field>
            <Field label="Policy number">
              <input
                value={claim.policy}
                onChange={(e) => setClaim({ ...claim, policy: e.target.value })}
              />
            </Field>
            <Field label="Amount claimed (KES)">
              <input
                type="number"
                min="0"
                step="0.01"
                value={claim.amount}
                onChange={(e) => setClaim({ ...claim, amount: e.target.value })}
              />
            </Field>
            <button
              className="btn primary"
              disabled={claim.insurer.trim().length < 2}
              onClick={() =>
                run(async () => {
                  await api.fileClaim(i.id, {
                    insurer: claim.insurer,
                    policy_no: claim.policy || undefined,
                    amount_claimed_cents: claim.amount
                      ? Math.round(Number(claim.amount) * 100)
                      : undefined,
                  });
                  setClaim({ insurer: "", policy: "", amount: "" });
                })
              }
            >
              File claim
            </button>
          </div>
        </Card>
      )}
    </>
  );
}

function SosList() {
  const [rows, setRows] = useState<SosAlert[]>([]);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setRows(await api.sosAlerts());
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), 8000);
    return () => clearInterval(timer);
  }, [load]);
  async function run(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
      await load();
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  return (
    <>
      <ErrorBanner message={error} />
      <Card title="Active SOS alerts">
        {rows.length === 0 && <p className="muted">No active alerts.</p>}
        {rows.map((a) => (
          <div key={a.id} className="banner bad">
            <p>
              <Siren size={18} />{" "}
              <strong>
                {a.driver_name} {a.registration && `(${a.registration})`}
              </strong>{" "}
              needs help. Pressed {when(a.sent_at)}
              {a.delay_s > 60 &&
                ` (reached us ${Math.round(a.delay_s / 60)} min later, when the phone got signal)`}
              . {a.notified} people were texted.
            </p>
            {a.map_url ? (
              <p>
                <a href={a.map_url} target="_blank" rel="noreferrer">
                  <ExternalLink size={14} /> Open the live location
                </a>
                {a.track.length > 0 && ` (${a.track.length} location updates)`}
              </p>
            ) : (
              <p>Location not known yet.</p>
            )}
            <p className="actions">
              {a.status === "active" && (
                <button className="btn" onClick={() => run(() => api.acknowledgeSos(a.id))}>
                  I am on it
                </button>
              )}
              {a.status === "acknowledged" && <span>Someone has answered.</span>}
              <button className="btn primary" onClick={() => run(() => api.resolveSos(a.id))}>
                <Check size={16} /> Safe, close it
              </button>
            </p>
          </div>
        ))}
      </Card>
    </>
  );
}

function Fines() {
  const [data, setData] = useState<FinesSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api
      .finesSummary()
      .then(setData)
      .catch((e) => setError(errorMessage(e)));
  }, []);
  const table = (title: string, rows: FinesSummary["by_driver"]) => (
    <Card title={title}>
      {rows.length === 0 && <p className="muted">No fines recorded.</p>}
      {rows.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Fines</th>
                <th>Total</th>
                <th>Business pays</th>
                <th>Driver pays</th>
                <th>To deduct from pay</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={String(r.id)}>
                  <td>{r.name}</td>
                  <td>{r.fines}</td>
                  <td>{kes(r.total_cents)}</td>
                  <td>{kes(r.business_cents)}</td>
                  <td>{kes(r.driver_cents)}</td>
                  <td>{kes(r.to_deduct_cents)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
  return (
    <>
      <ErrorBanner message={error} />
      {data && table("Fines per driver", data.by_driver)}
      {data && table("Fines per vehicle", data.by_vehicle)}
    </>
  );
}

function Claims() {
  const [rows, setRows] = useState<InsuranceClaim[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api
      .claims()
      .then(setRows)
      .catch((e) => setError(errorMessage(e)));
  }, []);
  return (
    <>
      <ErrorBanner message={error} />
      <Card title="Insurance claims">
        {rows.length === 0 && <p className="muted">No claims filed.</p>}
        {rows.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Vehicle</th>
                  <th>For</th>
                  <th>Insurer</th>
                  <th>Status</th>
                  <th>Claimed</th>
                  <th>Paid</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((c) => (
                  <tr key={c.id}>
                    <td>{c.registration}</td>
                    <td>
                      <Link to={`/incidents/view/${c.incident_id}`}>
                        {c.incident_type ? INCIDENT_TYPE[c.incident_type] : "Incident"}
                      </Link>
                    </td>
                    <td>{c.insurer}</td>
                    <td>{CLAIM_STATUS[c.status]}</td>
                    <td>{c.amount_claimed_cents !== null ? kes(c.amount_claimed_cents) : ""}</td>
                    <td>{c.amount_paid_cents !== null ? kes(c.amount_paid_cents) : ""}</td>
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

/** Incidents, breakdowns and fines, with SOS alerts and insurance claims. */
export default function Incidents() {
  const { can } = useAuth();
  return (
    <>
      <h2>Incidents and SOS</h2>
      <nav className="tabs">
        <NavLink to="/incidents" end>
          Incidents
        </NavLink>
        {can("sos.respond") && <NavLink to="/incidents/sos">SOS</NavLink>}
        {can("incidents.manage") && <NavLink to="/incidents/fines">Fines</NavLink>}
        {can("incidents.manage") && <NavLink to="/incidents/claims">Insurance claims</NavLink>}
      </nav>
      <Routes>
        <Route index element={<IncidentList />} />
        <Route path="view/:id" element={<IncidentDetail />} />
        <Route
          path="sos"
          element={can("sos.respond") ? <SosList /> : <Navigate to="/incidents" replace />}
        />
        <Route
          path="fines"
          element={can("incidents.manage") ? <Fines /> : <Navigate to="/incidents" replace />}
        />
        <Route
          path="claims"
          element={can("incidents.manage") ? <Claims /> : <Navigate to="/incidents" replace />}
        />
      </Routes>
    </>
  );
}
