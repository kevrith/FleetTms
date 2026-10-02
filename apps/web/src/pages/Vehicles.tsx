import type {
  Depot,
  OwnershipType,
  Party,
  PartyKind,
  Vehicle,
  VehicleInput,
} from "@fleettms/types";
import { Plus } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { FUEL, OWNERSHIP, PARTY_FOR_OWNERSHIP, PARTY_KIND, TIER, TRUST } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

export const EMPTY_VEHICLE: VehicleInput = {
  registration: "",
  make: null,
  model: null,
  capacity_tonnes: null,
  fuel_type: "diesel",
  tank_litres: null,
  expected_kmpl_loaded: null,
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
};

const text = (v: string) => (v.trim() === "" ? null : v.trim());
const num = (v: string) => (v.trim() === "" ? null : Number(v));

/** The vehicle form, shared by "add" here and "edit" on the detail page. */
export function VehicleForm({
  initial,
  depots,
  parties,
  submitLabel,
  onSubmit,
}: {
  initial: VehicleInput;
  depots: Depot[];
  parties: Party[];
  submitLabel: string;
  onSubmit: (v: VehicleInput) => Promise<void>;
}) {
  const [v, setV] = useState<VehicleInput>(initial);
  const set = <K extends keyof VehicleInput>(k: K, value: VehicleInput[K]) =>
    setV({ ...v, [k]: value });
  const partyKind = PARTY_FOR_OWNERSHIP[v.ownership_type];
  const choices = parties.filter((p) => p.kind === partyKind);

  async function submit(e: FormEvent) {
    e.preventDefault();
    await onSubmit(v);
  }

  return (
    <form onSubmit={submit} className="form-grid">
      <Field label="Registration">
        <input
          value={v.registration}
          onChange={(e) => set("registration", e.target.value)}
          placeholder="KCA 123A"
          required
        />
      </Field>
      <Field label="Make">
        <input value={v.make ?? ""} onChange={(e) => set("make", text(e.target.value))} />
      </Field>
      <Field label="Model">
        <input value={v.model ?? ""} onChange={(e) => set("model", text(e.target.value))} />
      </Field>
      <Field label="Capacity (tonnes)">
        <input
          type="number"
          step="0.01"
          min="0"
          value={v.capacity_tonnes ?? ""}
          onChange={(e) => set("capacity_tonnes", text(e.target.value))}
        />
      </Field>
      <Field label="Fuel type">
        <select
          value={v.fuel_type}
          onChange={(e) => set("fuel_type", e.target.value as Vehicle["fuel_type"])}
        >
          {Object.entries(FUEL).map(([k, label]) => (
            <option key={k} value={k}>
              {label}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Tank size (litres)">
        <input
          type="number"
          min="0"
          value={v.tank_litres ?? ""}
          onChange={(e) => set("tank_litres", num(e.target.value))}
        />
      </Field>
      <Field label="Expected km per litre, loaded">
        <input
          type="number"
          step="0.01"
          min="0"
          value={v.expected_kmpl_loaded ?? ""}
          onChange={(e) => set("expected_kmpl_loaded", text(e.target.value))}
        />
      </Field>
      <Field label="Expected km per litre, empty">
        <input
          type="number"
          step="0.01"
          min="0"
          value={v.expected_kmpl_empty ?? ""}
          onChange={(e) => set("expected_kmpl_empty", text(e.target.value))}
        />
      </Field>
      <Field label="Odometer (km)">
        <input
          type="number"
          min="0"
          value={v.odometer_km}
          onChange={(e) => set("odometer_km", Number(e.target.value))}
        />
      </Field>
      <Field label="Tracking tier">
        <select
          value={v.tracking_tier}
          onChange={(e) => set("tracking_tier", e.target.value as Vehicle["tracking_tier"])}
        >
          {Object.entries(TIER).map(([k, label]) => (
            <option key={k} value={k}>
              {label}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Home depot">
        <select value={v.depot_id ?? ""} onChange={(e) => set("depot_id", e.target.value || null)}>
          <option value="">None</option>
          {depots.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Ownership">
        <select
          value={v.ownership_type}
          onChange={(e) =>
            setV({ ...v, ownership_type: e.target.value as OwnershipType, party_id: null })
          }
        >
          {Object.entries(OWNERSHIP).map(([k, label]) => (
            <option key={k} value={k}>
              {label}
            </option>
          ))}
        </select>
      </Field>
      {partyKind && (
        <Field label={PARTY_KIND[partyKind]}>
          <select
            value={v.party_id ?? ""}
            onChange={(e) => set("party_id", e.target.value || null)}
            required
          >
            <option value="">Choose...</option>
            {choices.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </Field>
      )}
      <Field label="Legal gross weight limit (kg)">
        <input
          type="number"
          min="0"
          value={v.gvw_limit_kg ?? ""}
          onChange={(e) => set("gvw_limit_kg", num(e.target.value))}
        />
      </Field>
      <Field label="Empty weight of the lorry (kg)">
        <input
          type="number"
          min="0"
          value={v.tare_kg ?? ""}
          onChange={(e) => set("tare_kg", num(e.target.value))}
        />
      </Field>
      <Field label="Axle configuration">
        <input
          value={v.axle_config ?? ""}
          onChange={(e) => set("axle_config", text(e.target.value))}
          placeholder="e.g. 3 or 2+1"
        />
      </Field>
      <button className="btn primary">
        <Plus size={18} /> {submitLabel}
      </button>
    </form>
  );
}

function Parties({
  parties,
  canManage,
  reload,
}: {
  parties: Party[];
  canManage: boolean;
  reload: () => Promise<void>;
}) {
  const [form, setForm] = useState({
    kind: "lessor" as PartyKind,
    name: "",
    phone: "",
    kra_pin: "",
    payment_details: "",
  });
  const [error, setError] = useState<string | null>(null);

  async function add(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.createParty({
        kind: form.kind,
        name: form.name,
        phone: text(form.phone),
        kra_pin: text(form.kra_pin),
        payment_details: text(form.payment_details),
      });
      setForm({ ...form, name: "", phone: "", kra_pin: "", payment_details: "" });
      await reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <Card title="Lessors, lenders and lessees">
      <ErrorBanner message={error} />
      {parties.length === 0 && (
        <p className="muted">None yet. Add one before you set a vehicle as leased or financed.</p>
      )}
      <ul className="list">
        {parties.map((p) => (
          <li key={p.id}>
            <span>
              <strong>{p.name}</strong>{" "}
              <span className="muted">
                {PARTY_KIND[p.kind]}
                {p.phone ? `, ${p.phone}` : ""}
              </span>
            </span>
          </li>
        ))}
      </ul>
      {canManage && (
        <form onSubmit={add} className="form-grid">
          <Field label="Type">
            <select
              value={form.kind}
              onChange={(e) => setForm({ ...form, kind: e.target.value as PartyKind })}
            >
              {Object.entries(PARTY_KIND).map(([k, label]) => (
                <option key={k} value={k}>
                  {label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Name">
            <input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              required
            />
          </Field>
          <Field label="Phone">
            <input
              value={form.phone}
              onChange={(e) => setForm({ ...form, phone: e.target.value })}
            />
          </Field>
          <Field label="KRA PIN">
            <input
              value={form.kra_pin}
              onChange={(e) => setForm({ ...form, kra_pin: e.target.value })}
            />
          </Field>
          <Field label="M-Pesa or bank details">
            <input
              value={form.payment_details}
              onChange={(e) => setForm({ ...form, payment_details: e.target.value })}
            />
          </Field>
          <button className="btn primary">
            <Plus size={18} /> Add
          </button>
        </form>
      )}
    </Card>
  );
}

export default function Vehicles() {
  const { can } = useAuth();
  const manage = can("vehicles.manage");
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [depots, setDepots] = useState<Depot[]>([]);
  const [parties, setParties] = useState<Party[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  const load = useCallback(async () => {
    try {
      const [v, d, p] = await Promise.all([
        api.vehicles(),
        api.depots().catch(() => []),
        api.parties(),
      ]);
      setVehicles(v);
      setDepots(d);
      setParties(p);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  async function create(input: VehicleInput) {
    setError(null);
    try {
      await api.createVehicle(input);
      setAdding(false);
      await load();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  const depotName = (id: string | null) => depots.find((d) => d.id === id)?.name ?? "";

  return (
    <>
      <h2>Vehicles</h2>
      <ErrorBanner message={error} />
      {manage && (
        <p>
          <button className="btn primary" onClick={() => setAdding(!adding)}>
            <Plus size={18} /> {adding ? "Close" : "Add a vehicle"}
          </button>
        </p>
      )}
      {adding && (
        <Card title="New vehicle">
          <VehicleForm
            initial={EMPTY_VEHICLE}
            depots={depots}
            parties={parties}
            submitLabel="Save vehicle"
            onSubmit={create}
          />
        </Card>
      )}
      <Card>
        {vehicles.length === 0 && (
          <p className="muted">
            No vehicles yet. Add one, or import a whole fleet from Excel in Settings.
          </p>
        )}
        {vehicles.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Registration</th>
                  <th>Vehicle</th>
                  <th>Ownership</th>
                  <th>Depot</th>
                  <th>Odometer</th>
                  <th>Trust</th>
                </tr>
              </thead>
              <tbody>
                {vehicles.map((v) => (
                  <tr key={v.id}>
                    <td>
                      <Link to={v.id}>{v.registration}</Link>
                    </td>
                    <td>{[v.make, v.model].filter(Boolean).join(" ")}</td>
                    <td>{OWNERSHIP[v.ownership_type]}</td>
                    <td>{depotName(v.depot_id)}</td>
                    <td>{v.odometer_km.toLocaleString()} km</td>
                    <td>{v.trust_level ? TRUST[v.trust_level] : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <Parties parties={parties} canManage={manage} reload={load} />
    </>
  );
}
