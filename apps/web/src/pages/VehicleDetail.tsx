import type {
  CrewAssignment,
  CrewRole,
  Depot,
  Party,
  StaffProfile,
  Vehicle,
  VehicleInput,
} from "@fleettms/types";
import { UserMinus } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { CREW, OWNERSHIP, VEHICLE_DOC_TYPES } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "./../ui";
import DocumentsPanel from "./DocumentsPanel";
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
      <DocumentsPanel
        owner={{ vehicleId: vehicle.id }}
        types={VEHICLE_DOC_TYPES}
        canManage={manage}
      />
    </>
  );
}
