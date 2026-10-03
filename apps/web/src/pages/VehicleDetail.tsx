import type {
  Inspection,
  CrewAssignment,
  CrewRole,
  Depot,
  Party,
  StaffProfile,
  Vehicle,
  VehicleBaselines,
  VehicleInput,
  VehicleTrust,
} from "@fleettms/types";
import { UserMinus } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { CREW, DEVICE_FLAG, fmtTime, OWNERSHIP, TIER, TRUST, VEHICLE_DOC_TYPES } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "./../ui";
import DocumentsPanel from "./DocumentsPanel";
import { ImmobiliserCard } from "./Immobiliser";
import InspectionCard from "./InspectionCard";
import { ReplayCard } from "./Replay";
import ServiceCard from "./ServiceCard";
import { VehicleForm } from "./Vehicles";

function Crew({ vehicle, canManage }: { vehicle: Vehicle; canManage: boolean }) {
  const { can } = useAuth();
  const [history, setHistory] = useState<CrewAssignment[]>([]);
  const [staff, setStaff] = useState<StaffProfile[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setHistory(await api.crew(vehicle.id));
      if (can("staff.view")) setStaff(await api.staff());
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [vehicle.id, can]);
  useEffect(() => {
    void load();
  }, [load]);

  const name = (id: string) =>
    staff.find((s) => s.membership_id === id)?.name ?? "Former staff member";
  const current = (role: CrewRole) => history.find((h) => h.role === role && h.ended_at === null);

  async function assign(role: CrewRole, membershipId: string) {
    if (!membershipId) return;
    setError(null);
    try {
      await api.assignCrew(vehicle.id, membershipId, role);
      await load();
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  async function unassign(role: CrewRole) {
    try {
      await api.unassignCrew(vehicle.id, role);
      await load();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  return (
    <Card title="Crew">
      <ErrorBanner message={error} />
      {(["driver", "turnboy"] as CrewRole[]).map((role) => {
        const now = current(role);
        const options = staff.filter(
          (s) => s.roles.includes(role) && s.membership_id !== now?.membership_id,
        );
        return (
          <div key={role} className="form-grid">
            <Field label={CREW[role]}>
              <span>
                {now ? name(now.membership_id) : <span className="muted">Nobody assigned</span>}
              </span>
            </Field>
            {canManage && (
              <>
                <Field label={`Assign a ${role}`}>
                  <select value="" onChange={(e) => assign(role, e.target.value)}>
                    <option value="">Choose...</option>
                    {options.map((s) => (
                      <option key={s.membership_id} value={s.membership_id}>
                        {s.name}
                        {s.vehicle_id ? " (on another vehicle: will be moved)" : ""}
                      </option>
                    ))}
                  </select>
                </Field>
                {now && (
                  <button className="btn" onClick={() => unassign(role)}>
                    <UserMinus size={16} /> Remove
                  </button>
                )}
              </>
            )}
          </div>
        );
      })}
      <h4>History</h4>
      <ul className="list">
        {history.map((h) => (
          <li key={h.id}>
            <span>
              <strong>{name(h.membership_id)}</strong> <span className="muted">{CREW[h.role]}</span>
            </span>
            <span className="muted">
              {h.started_at.slice(0, 10)} to {h.ended_at ? h.ended_at.slice(0, 10) : "now"}
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function Trust({ vehicleId }: { vehicleId: string }) {
  const [trust, setTrust] = useState<VehicleTrust | null>(null);
  useEffect(() => {
    api
      .vehicleTrust(vehicleId)
      .then(setTrust)
      .catch(() => setTrust(null));
  }, [vehicleId]);
  if (!trust) return null;
  return (
    <Card title="Data trust">
      <p>
        <span
          className={`status ${trust.level === "high" ? "ok" : trust.level === "low" ? "bad" : "warn"}`}
        >
          {TRUST[trust.level]}
        </span>{" "}
        <span className="muted">
          Starts from the tracking tier ({TIER[trust.tier]}) and drops when a phone used on this
          vehicle is flagged or its tracker is cut, jammed or tampered with.
        </span>
      </p>
      {trust.flags.length === 0 && (
        <p className="muted">No phone or tracker checks have failed in the last 30 days.</p>
      )}
      <ul className="list">
        {trust.flags.map((f) => (
          <li key={f.flag}>
            <span>{DEVICE_FLAG[f.flag] ?? f.flag}</span>
            <span className="muted">
              {f.count} time{f.count === 1 ? "" : "s"}, last {fmtTime(f.last_at)}
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function Baselines({ vehicleId }: { vehicleId: string }) {
  const [data, setData] = useState<VehicleBaselines | null>(null);
  useEffect(() => {
    api
      .vehicleBaselines(vehicleId)
      .then(setData)
      .catch(() => setData(null));
  }, [vehicleId]);
  if (!data) return null;
  return (
    <Card title="Normal fuel use">
      <p className="muted">
        What this vehicle burns on each route and load, from its own finished trips with idling
        taken out. A trip well above this raises a fuel alert. It takes {data.needed_trips} similar
        trips with fuel recorded before the vehicle's own history is used
        {data.declared_kmpl_loaded || data.declared_kmpl_empty
          ? `; until then its declared ${data.declared_kmpl_loaded ?? "?"} km a litre loaded and ${data.declared_kmpl_empty ?? "?"} empty are used`
          : ""}
        .
      </p>
      {data.baselines.length === 0 && <p className="muted">No trips with fuel recorded yet.</p>}
      <ul className="list">
        {data.baselines.map((b) => (
          <li key={`${b.route}-${b.load_band}`}>
            <span>
              {b.route}{" "}
              <span className="muted">
                ({b.load_band === "empty" ? "empty" : `load ${b.load_band} and up`})
              </span>
            </span>
            <span>
              {b.km_per_litre} km a litre{" "}
              <span className="muted">
                from {b.trips} trip{b.trips === 1 ? "" : "s"}
                {b.established ? "" : ", not enough yet"}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function Inspections({ vehicleId }: { vehicleId: string }) {
  const [rows, setRows] = useState<Inspection[]>([]);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setRows((await api.inspections(vehicleId)).slice(0, 5));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [vehicleId]);
  useEffect(() => {
    void load();
  }, [load]);

  return (
    <Card title="Recent inspections">
      <ErrorBanner message={error} />
      {rows.length === 0 && <p className="muted">No inspections yet.</p>}
      {rows.map((i) => (
        <InspectionCard key={i.id} inspection={i} onChanged={load} />
      ))}
    </Card>
  );
}

export default function VehicleDetail() {
  const { id = "" } = useParams();
  const { can } = useAuth();
  const manage = can("vehicles.manage");
  const [vehicle, setVehicle] = useState<Vehicle | null>(null);
  const [depots, setDepots] = useState<Depot[]>([]);
  const [parties, setParties] = useState<Party[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const load = useCallback(async () => {
    try {
      const [v, d, p] = await Promise.all([
        api.vehicle(id),
        api.depots().catch(() => []),
        api.parties(),
      ]);
      setVehicle(v);
      setDepots(d);
      setParties(p);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [id]);
  useEffect(() => {
    void load();
  }, [load]);

  async function save(input: VehicleInput) {
    setError(null);
    setSaved(false);
    try {
      setVehicle(await api.updateVehicle(id, input));
      setSaved(true);
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  if (!vehicle) return error ? <ErrorBanner message={error} /> : <p>Loading...</p>;
  const { id: _id, ...initial } = vehicle;
  void _id;

  return (
    <>
      <p>
        <Link to="/vehicles">Back to vehicles</Link>
      </p>
      <h2>
        {vehicle.registration} <span className="muted">{OWNERSHIP[vehicle.ownership_type]}</span>
      </h2>
      <ErrorBanner message={error} />
      {saved && <p className="status ok">Saved.</p>}
      {manage ? (
        <Card title="Details">
          <VehicleForm
            key={JSON.stringify(vehicle)}
            initial={initial}
            depots={depots}
            parties={parties}
            submitLabel="Save changes"
            onSubmit={save}
          />
        </Card>
      ) : (
        <Card title="Details">
          <p>
            {[vehicle.make, vehicle.model].filter(Boolean).join(" ")},{" "}
            {vehicle.odometer_km.toLocaleString()} km
          </p>
        </Card>
      )}
      <Crew vehicle={vehicle} canManage={manage} />
      <ServiceCard vehicleId={vehicle.id} />
      <Trust vehicleId={vehicle.id} />
      <Baselines vehicleId={vehicle.id} />
      <ReplayCard vehicleId={vehicle.id} />
      <ImmobiliserCard vehicleId={vehicle.id} />
      <Inspections vehicleId={vehicle.id} />
      <DocumentsPanel
        owner={{ vehicleId: vehicle.id }}
        types={VEHICLE_DOC_TYPES}
        canManage={manage}
      />
    </>
  );
}
