import type { Job, JobSchedule, Vehicle } from "@fleettms/types";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function when(s: JobSchedule): string {
  const at = `at ${s.pickup_time}`;
  if (s.cadence === "daily") return `Every day ${at}`;
  if (s.cadence === "monthly") return `On day ${s.day_of_month} of each month ${at}`;
  return `Every ${s.weekdays.map((d) => DAYS[d]).join(", ")} ${at}`;
}

/** Work that comes round on its own: set a job up once and each coming day is put in the diary for you. */
export default function JobSchedules() {
  const [rows, setRows] = useState<JobSchedule[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [open, setOpen] = useState<JobSchedule | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({
    job: "",
    cadence: "weekly" as "daily" | "weekly" | "monthly",
    weekdays: [0],
    day: "1",
    time: "06:00",
    hours: "24",
    lead: "2",
    vehicle: "",
    ends: "",
  });

  const load = useCallback(async () => {
    try {
      const [s, j, v] = await Promise.all([
        api.jobSchedules(),
        api.jobs({ openOnly: false }),
        api.vehicles(),
      ]);
      setRows(s);
      setJobs(j.filter((x) => x.status !== "cancelled"));
      setVehicles(v.filter((x) => x.is_active));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const template = jobs.find((j) => j.id === form.job);
  const contract = template?.billing_method === "monthly_contract";

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
  async function create(e: FormEvent) {
    e.preventDefault();
    await act(
      () =>
        api.createJobSchedule({
          template_job_id: form.job,
          cadence: form.cadence,
          weekdays: form.cadence === "weekly" ? form.weekdays : undefined,
          day_of_month: form.cadence === "monthly" ? Number(form.day) : undefined,
          pickup_time: form.time,
          deliver_within_hours: Number(form.hours),
          lead_days: Number(form.lead),
          vehicle_id: form.vehicle || undefined,
          ends_on: form.ends || undefined,
        }),
      'Schedule made. Press "Put the coming days in the diary now" or wait for the early-morning run.',
    );
  }
  return (
    <>
      <ErrorBanner message={error} />
      {message && <p className="banner ok">{message}</p>}
      <Card title="Recurring work">
        <p>
          Set a job up once, and each coming day is put in the diary for you, a couple of days
          ahead. A per-trip, per-tonne or per-kilometre job is repeated as a new job each time. A
          monthly contract already bills itself every month, so its schedule sends a trip of the
          contract out each time, in the lorry you choose. If a day cannot be given a lorry the job
          is still made and the managers are texted.
        </p>
        {rows.length === 0 && <p className="muted">No schedules yet.</p>}
        <ul className="list">
          {rows.map((s) => (
            <li key={s.id}>
              <span>
                <strong>{s.client}</strong> <span className="muted">repeats {s.template}</span>{" "}
                {s.contract && <span className="status ok">contract</span>}{" "}
                <span className={`status ${s.is_active ? "ok" : "warn"}`}>
                  {s.is_active ? "running" : "paused"}
                </span>
                <br />
                {when(s)}
                {s.registration && <span className="muted">, in {s.registration}</span>}
                <br />
                <span className="muted">
                  Next: {s.next.slice(0, 4).join(", ") || "nothing coming"}
                </span>
              </span>
              <span className="actions">
                <button
                  className="btn"
                  type="button"
                  onClick={() =>
                    act(
                      () => api.updateJobSchedule(s.id, { is_active: !s.is_active }),
                      s.is_active ? "Paused." : "Running again.",
                    )
                  }
                >
                  {s.is_active ? "Pause" : "Resume"}
                </button>
                <button
                  className="btn"
                  type="button"
                  disabled={!s.is_active}
                  onClick={() =>
                    act(() => api.runJobSchedule(s.id), "The coming days are in the diary.")
                  }
                >
                  Put the coming days in the diary now
                </button>
                <button
                  className="btn"
                  type="button"
                  onClick={async () =>
                    setOpen(open?.id === s.id ? null : await api.jobSchedule(s.id))
                  }
                >
                  {open?.id === s.id ? "Hide" : "What it has made"}
                </button>
              </span>
              {open?.id === s.id && (
                <ul className="list">
                  {(open.runs ?? []).length === 0 && <li className="muted">Nothing yet.</li>}
                  {(open.runs ?? []).map((r) => (
                    <li key={r.day}>
                      <span>{r.day}</span>
                      <span className={r.note ? "status warn" : "muted"}>
                        {r.note ?? (r.trip_id ? "trip assigned" : "job made")}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      </Card>
      <Card title="Repeat a job on a schedule">
        <form onSubmit={create} className="form-grid">
          <Field label="Which job">
            <select
              value={form.job}
              onChange={(e) => setForm({ ...form, job: e.target.value })}
              required
            >
              <option value="">Choose</option>
              {jobs.map((j) => (
                <option key={j.id} value={j.id}>
                  {j.number}: {j.client_name} {j.route ? `, ${j.route.name}` : ""}
                </option>
              ))}
            </select>
          </Field>
          <Field label="How often">
            <select
              value={form.cadence}
              onChange={(e) => setForm({ ...form, cadence: e.target.value as typeof form.cadence })}
            >
              <option value="daily">Every day</option>
              <option value="weekly">On some days of the week</option>
              <option value="monthly">On a day of the month</option>
            </select>
          </Field>
          {form.cadence === "weekly" && (
            <Field label="Which days">
              <span className="actions">
                {DAYS.map((d, i) => (
                  <label key={d} className="check">
                    <input
                      type="checkbox"
                      checked={form.weekdays.includes(i)}
                      onChange={(e) =>
                        setForm({
                          ...form,
                          weekdays: e.target.checked
                            ? [...form.weekdays, i]
                            : form.weekdays.filter((x) => x !== i),
                        })
                      }
                    />
                    <span>{d}</span>
                  </label>
                ))}
              </span>
            </Field>
          )}
          {form.cadence === "monthly" && (
            <Field label="Day of the month (1 to 28)">
              <input
                type="number"
                min="1"
                max="28"
                value={form.day}
                onChange={(e) => setForm({ ...form, day: e.target.value })}
              />
            </Field>
          )}
          <Field label="Pick-up time (Nairobi)">
            <input
              type="time"
              value={form.time}
              onChange={(e) => setForm({ ...form, time: e.target.value })}
              required
            />
          </Field>
          <Field label="Deliver within (hours)">
            <input
              type="number"
              min="1"
              max="240"
              value={form.hours}
              onChange={(e) => setForm({ ...form, hours: e.target.value })}
            />
          </Field>
          <Field label="Put it in the diary this many days ahead">
            <input
              type="number"
              min="0"
              max="14"
              value={form.lead}
              onChange={(e) => setForm({ ...form, lead: e.target.value })}
            />
          </Field>
          <Field
            label={contract ? "Lorry to send (needed for a contract)" : "Lorry to send (optional)"}
          >
            <select
              value={form.vehicle}
              onChange={(e) => setForm({ ...form, vehicle: e.target.value })}
              required={contract}
            >
              <option value="">{contract ? "Choose" : "None: I will dispatch each one"}</option>
              {vehicles.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.registration}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Stop after (optional)">
            <input
              type="date"
              value={form.ends}
              onChange={(e) => setForm({ ...form, ends: e.target.value })}
            />
          </Field>
          <p className="actions">
            <button
              className="btn primary"
              type="submit"
              disabled={!form.job || (form.cadence === "weekly" && form.weekdays.length === 0)}
            >
              Make the schedule
            </button>
          </p>
        </form>
      </Card>
    </>
  );
}
