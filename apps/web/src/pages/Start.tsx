import type { Onboarding } from "@fleettms/types";
import { Check, Sparkles } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

const toCents = (kes: string) => Math.round(Number(kes || 0) * 100);

/**
 * Getting started, in the order a new owner needs it: a lorry, a driver, a first job. Each step shows when it is done; nothing is
 * required to be done in one sitting, and the sample data lets you look around first.
 */
export default function Start() {
  const navigate = useNavigate();
  const { me, reload } = useAuth();
  const [o, setO] = useState<Onboarding | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [vehicle, setVehicle] = useState({ registration: "", tank: "", kmpl: "" });
  const [driveIt, setDriveIt] = useState<boolean | null>(null);
  const iDrive = driveIt ?? me?.roles.includes("driver") ?? false;
  const [driver, setDriver] = useState({ name: "", phone: "" });
  const [job, setJob] = useState({
    client: "",
    pickup: "",
    dropoff: "",
    km: "",
    rate: "",
    cargo: "",
  });
  const load = useCallback(async () => {
    try {
      setO(await api.onboarding());
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);
  async function run(work: () => Promise<unknown>, done: string) {
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
  const done = (key: string) => o?.items.find((i) => i.key === key)?.done ?? false;

  function addVehicle(e: FormEvent) {
    e.preventDefault();
    void run(async () => {
      const made = await api.createVehicle({
        registration: vehicle.registration.trim().toUpperCase(),
        make: null,
        model: null,
        capacity_tonnes: null,
        fuel_type: "diesel",
        tank_litres: vehicle.tank ? Number(vehicle.tank) : null,
        expected_kmpl_loaded: vehicle.kmpl || null,
        expected_kmpl_empty: null,
        odometer_km: 0,
        tracking_tier: "basic",
        depot_id: null,
        ownership_type: "owned",
        party_id: null,
        gvw_limit_kg: null,
        tare_kg: null,
        axle_config: null,
        is_active: true,
      });
      if (iDrive) {
        await api.driveMyself(made.id);
        await reload();
      }
    }, "Vehicle added.").then(() => setVehicle({ registration: "", tank: "", kmpl: "" }));
  }
  function inviteDriver(e: FormEvent) {
    e.preventDefault();
    void run(
      () =>
        api.inviteUser({
          name: driver.name.trim(),
          phone: driver.phone.trim(),
          roles: ["driver"],
        }),
      "Driver invited: they sign in with their phone number and a code.",
    ).then(() => setDriver({ name: "", phone: "" }));
  }
  function firstJob(e: FormEvent) {
    e.preventDefault();
    void run(async () => {
      const made = await api.createFirstJob({
        client_name: job.client,
        pickup: job.pickup,
        dropoff: job.dropoff,
        distance_km: Number(job.km),
        rate_cents: toCents(job.rate),
        cargo_description: job.cargo || null,
      });
      navigate(`/jobs/view/${made.job.id}`);
    }, "Job created.");
  }
  return (
    <>
      <h2>Getting started</h2>
      <p className="muted">
        Three steps, in any order you like. You can leave and come back: what you have done stays
        done.
      </p>
      <ErrorBanner message={error} />
      {message && (
        <p className="banner ok" role="status">
          {message}
        </p>
      )}
      <Card title={`1. Add a vehicle ${done("vehicles") ? "(done)" : ""}`}>
        <form className="form-grid" onSubmit={addVehicle}>
          <Field label="Number plate">
            <input
              value={vehicle.registration}
              onChange={(e) => setVehicle({ ...vehicle, registration: e.target.value })}
              required
              minLength={3}
              placeholder="KCA 123A"
            />
          </Field>
          <Field label="Tank size (litres)">
            <input
              type="number"
              min="1"
              value={vehicle.tank}
              onChange={(e) => setVehicle({ ...vehicle, tank: e.target.value })}
            />
          </Field>
          <Field label="Kilometres a litre, loaded">
            <input
              type="number"
              min="0.1"
              step="0.1"
              value={vehicle.kmpl}
              onChange={(e) => setVehicle({ ...vehicle, kmpl: e.target.value })}
            />
          </Field>
          <label className="check">
            <input
              type="checkbox"
              checked={iDrive}
              onChange={(e) => setDriveIt(e.target.checked)}
            />
            <span>I drive this vehicle myself</span>
          </label>
          <button className="btn primary" type="submit">
            Add the vehicle
          </button>
        </form>
        <p className="muted">
          Many vehicles? <Link to="/settings/import">Import them from Excel</Link>.
        </p>
      </Card>
      <Card title={`2. Invite a driver ${done("team") ? "(done)" : ""}`}>
        <form className="form-grid" onSubmit={inviteDriver}>
          <Field label="Name">
            <input
              value={driver.name}
              onChange={(e) => setDriver({ ...driver, name: e.target.value })}
              required
              minLength={2}
            />
          </Field>
          <Field label="Phone number">
            <input
              value={driver.phone}
              onChange={(e) => setDriver({ ...driver, phone: e.target.value })}
              required
              inputMode="tel"
              placeholder="0712 345 678"
            />
          </Field>
          <button className="btn primary" type="submit">
            Invite the driver
          </button>
        </form>
      </Card>
      <Card title={`3. Your first job ${done("job") ? "(done)" : ""}`}>
        <p className="muted">
          Who it is for, where it goes, and what they pay. The client and the route are made for
          you.
        </p>
        <form className="form-grid" onSubmit={firstJob}>
          <Field label="Client">
            <input
              value={job.client}
              onChange={(e) => setJob({ ...job, client: e.target.value })}
              required
              minLength={2}
              placeholder="Bamburi Cement"
            />
          </Field>
          <Field label="From">
            <input
              value={job.pickup}
              onChange={(e) => setJob({ ...job, pickup: e.target.value })}
              required
              minLength={2}
              placeholder="Mombasa"
            />
          </Field>
          <Field label="To">
            <input
              value={job.dropoff}
              onChange={(e) => setJob({ ...job, dropoff: e.target.value })}
              required
              minLength={2}
              placeholder="Nairobi"
            />
          </Field>
          <Field label="Distance (km)">
            <input
              type="number"
              min="1"
              value={job.km}
              onChange={(e) => setJob({ ...job, km: e.target.value })}
              required
            />
          </Field>
          <Field label="What they pay for the trip (KES)">
            <input
              type="number"
              min="1"
              step="0.01"
              value={job.rate}
              onChange={(e) => setJob({ ...job, rate: e.target.value })}
              required
            />
          </Field>
          <Field label="Cargo">
            <input value={job.cargo} onChange={(e) => setJob({ ...job, cargo: e.target.value })} />
          </Field>
          <button className="btn primary" type="submit">
            Create the job
          </button>
        </form>
      </Card>
      <Card title="Or look around first">
        <p className="muted">
          Adds a sample lorry, client, route and job to click around in. None of it counts as set
          up, and you can remove it any time before a trip is started on it.
        </p>
        <p className="actions">
          {!o?.has_sample_data ? (
            <button
              className="btn"
              type="button"
              onClick={() => run(() => api.addSampleData(), "Sample data added.")}
            >
              <Sparkles size={16} /> Add the sample data
            </button>
          ) : (
            <button
              className="btn"
              type="button"
              onClick={() => run(() => api.removeSampleData(), "Sample data removed.")}
            >
              Remove the sample data
            </button>
          )}
        </p>
      </Card>
      {o && (
        <p className="muted">
          <Check size={14} /> {o.done} of {o.total} getting-started steps done.{" "}
          <Link to="/">Back to the home page</Link>
        </p>
      )}
    </>
  );
}
