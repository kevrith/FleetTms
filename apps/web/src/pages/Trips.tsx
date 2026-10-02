import type { StaffProfile, Trip, TripInput, Vehicle } from "@fleettms/types";
import { Plus } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { fmtTime, TRIP_STATUS } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

const text = (v: string) => (v.trim() === "" ? null : v.trim());

export default function Trips() {
  const { can } = useAuth();
  const manage = can("trips.manage");
  const [trips, setTrips] = useState<Trip[]>([]);
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [staff, setStaff] = useState<StaffProfile[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({
    vehicle_id: "",
    driver: "",
    cargo: "",
    origin: "",
    destination: "",
  });

  const load = useCallback(async () => {
    try {
      setTrips(await api.trips());
      if (manage) {
        setVehicles(await api.vehicles());
        if (can("staff.view")) setStaff(await api.staff());
      }
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [manage, can]);
  useEffect(() => {
    void load();
  }, [load]);

  async function create(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const input: TripInput = {
      vehicle_id: form.vehicle_id,
      driver_membership_id: form.driver || null,
      cargo_description: text(form.cargo),
      origin: text(form.origin),
      destination: text(form.destination),
    };
    try {
      await api.createTrip(input);
      setAdding(false);
      setForm({ vehicle_id: "", driver: "", cargo: "", origin: "", destination: "" });
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const drivers = staff.filter((s) => s.roles.includes("driver"));

  return (
    <>
      <h2>Trips</h2>
      <ErrorBanner message={error} />
      {manage && (
        <p>
          <button className="btn primary" onClick={() => setAdding(!adding)}>
            <Plus size={18} /> {adding ? "Close" : "Schedule a trip"}
          </button>
        </p>
      )}
      {adding && (
        <Card title="New trip">
          <form onSubmit={create} className="form-grid">
            <Field label="Vehicle">
              <select
                value={form.vehicle_id}
                onChange={(e) => setForm({ ...form, vehicle_id: e.target.value })}
                required
              >
                <option value="">Choose...</option>
                {vehicles
                  .filter((v) => v.is_active)
                  .map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.registration}
                    </option>
                  ))}
              </select>
            </Field>
            <Field label="Driver (leave blank for the vehicle's driver)">
              <select
                value={form.driver}
                onChange={(e) => setForm({ ...form, driver: e.target.value })}
              >
                <option value="">Vehicle's driver</option>
                {drivers.map((d) => (
                  <option key={d.membership_id} value={d.membership_id}>
                    {d.name}
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
            <Field label="From">
              <input
                value={form.origin}
                onChange={(e) => setForm({ ...form, origin: e.target.value })}
              />
            </Field>
            <Field label="To">
              <input
                value={form.destination}
                onChange={(e) => setForm({ ...form, destination: e.target.value })}
              />
            </Field>
            <button className="btn primary">
              <Plus size={18} /> Save trip
            </button>
          </form>
        </Card>
      )}
      <Card>
        {trips.length === 0 && <p className="muted">No trips yet.</p>}
        {trips.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Vehicle</th>
                  <th>Route</th>
                  <th>Cargo</th>
                  <th>Status</th>
                  <th>Started</th>
                  <th>Distance</th>
                </tr>
              </thead>
              <tbody>
                {trips.map((t) => (
                  <tr key={t.id}>
                    <td>
                      <Link to={t.id}>{t.registration}</Link>
                    </td>
                    <td>{[t.origin, t.destination].filter(Boolean).join(" to ")}</td>
                    <td>{t.cargo_description}</td>
                    <td>{TRIP_STATUS[t.status]}</td>
                    <td>{fmtTime(t.started_at)}</td>
                    <td>{t.distance_km != null ? `${t.distance_km.toLocaleString()} km` : ""}</td>
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
