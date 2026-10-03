import type {
  FraudAlert,
  FraudSettings,
  FraudSummary,
  FraudThresholds,
  TrustLevel,
} from "@fleettms/types";
import { ChevronDown, ChevronRight, RefreshCw, Save } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, NavLink, Route, Routes } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { FRAUD_KIND, FRAUD_STATUS, nairobiTime, THRESHOLD_TEXT, TRUST } from "../labels";
import { Card, ErrorBanner, errorMessage, Field } from "../ui";

const ISO = /^\d{4}-\d\d-\d\dT/;
const UNITS: Record<string, string> = {
  litres: "litres",
  expected_litres: "litres",
  km: "km",
  gps_km: "km",
  expected_km: "km",
  extra_km: "km",
  odometer_km: "km",
  variance_pct: "%",
  over_pct: "%",
  share_pct: "%",
  threshold_pct: "%",
  minutes: "minutes",
  idle_minutes: "minutes",
  idle_hours: "hours",
  baseline_l_per_km: "litres per km",
  overload_kg: "kg",
  loaded_weight_kg: "kg",
  amount_cents: "KES",
};
const EVIDENCE_LABEL: Record<string, string> = {
  expected_litres: "Litres expected",
  variance_pct: "Over expected",
  baseline_l_per_km: "Normal use",
  baseline_source: "Normal worked out from",
  baseline_trips: "Trips behind that",
  threshold_pct: "Alert threshold",
  sources_km: "Distances",
  first_use: "First used",
  tracker_cut_at: "Tracker cut at",
  sha_prefix: "Photo fingerprint",
  serial_read: "Serial read",
  recorded_serial: "Serial on record",
};

function label(key: string): string {
  if (EVIDENCE_LABEL[key]) return EVIDENCE_LABEL[key];
  const text = key.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function show(key: string, value: unknown): string {
  if (typeof value === "string" && ISO.test(value)) return nairobiTime(value);
  if (typeof value === "number") {
    if (key === "amount_cents")
      return `KES ${(value / 100).toLocaleString("en-KE", { minimumFractionDigits: 2 })}`;
    return `${value.toLocaleString("en-KE")}${UNITS[key] ? ` ${UNITS[key]}` : ""}`;
  }
  if (value && typeof value === "object")
    return Object.entries(value as Record<string, unknown>)
      .filter(([, v]) => v != null)
      .map(([k, v]) => `${label(k).toLowerCase()}: ${show(k, v)}`)
      .join(", ");
  return String(value);
}

/** The numbers, times and places behind a finding, as plain rows. */
function Evidence({ evidence }: { evidence: Record<string, unknown> }) {
  const rows = Object.entries(evidence).filter(
    ([k, v]) => v != null && v !== "" && k !== "lat" && k !== "lng",
  );
  const lat = evidence.lat as number | undefined;
  const lng = evidence.lng as number | undefined;
  return (
    <div className="table-wrap">
      <table>
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k}>
              <th scope="row" style={{ textAlign: "left", fontWeight: 500 }}>
                {label(k)}
              </th>
              <td>{show(k, v)}</td>
            </tr>
          ))}
          {lat != null && lng != null && (
            <tr>
              <th scope="row" style={{ textAlign: "left", fontWeight: 500 }}>
                Place
              </th>
              <td>
                <a
                  href={`https://www.openstreetmap.org/?mlat=${lat}&mlon=${lng}#map=16/${lat}/${lng}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  Show on the map
                </a>
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function TrustBadge({ level }: { level: TrustLevel | null }) {
  if (!level) return null;
  return (
    <span className={`status ${level === "high" ? "ok" : level === "low" ? "bad" : "warn"}`}>
      Data trust: {TRUST[level]}
    </span>
  );
}

function AlertRow({ a, onChanged }: { a: FraudAlert; onChanged: () => void }) {
  const { can } = useAuth();
  const [open, setOpen] = useState(false);
  const [asking, setAsking] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  async function answer(outcome: "explained" | "confirmed") {
    setError(null);
    try {
      await api.handleFraudAlert(a.id, { note, outcome });
      setAsking(false);
      setNote("");
      onChanged();
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  return (
    <li style={{ display: "block" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
        <span>
          <button
            type="button"
            className="btn"
            aria-expanded={open}
            aria-label={open ? "Hide the evidence" : "Show the evidence"}
            onClick={() => setOpen(!open)}
          >
            {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          </button>{" "}
          <span className={`status ${a.severity === "red" ? "bad" : "warn"}`}>{a.label}</span>{" "}
          <strong>{a.title}</strong>
        </span>
        <span className="muted">
          {nairobiTime(a.occurred_at)}, {FRAUD_STATUS[a.status]}
        </span>
      </div>
      {a.detail && <div className="muted">{a.detail}</div>}
      <div className="muted">
        {a.driver && <>Driver: {a.driver}. </>}
        <TrustBadge level={a.trust_level} />{" "}
        {a.trip_id && <Link to={`/trips/${a.trip_id}`}>Open the trip</Link>}{" "}
        {a.vehicle_id && <Link to={`/vehicles/${a.vehicle_id}`}>Open the vehicle</Link>}
      </div>
      {open && <Evidence evidence={a.evidence} />}
      {a.note && (
        <div className="muted">
          Answer: {a.note} ({a.handled_at ? nairobiTime(a.handled_at) : ""})
        </div>
      )}
      <ErrorBanner message={error} />
      {a.status === "open" && can("alerts.manage") && !asking && (
        <button className="btn" type="button" onClick={() => setAsking(true)}>
          Answer
        </button>
      )}
      {asking && (
        <div className="form-grid">
          <Field label="What is the answer?">
            <input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              minLength={3}
              maxLength={500}
              placeholder="For example: fuel for the generator was bought as well"
            />
          </Field>
          <p className="actions">
            <button
              className="btn"
              type="button"
              disabled={note.trim().length < 3}
              onClick={() => answer("explained")}
            >
              There is an explanation
            </button>
            <button
              className="btn"
              type="button"
              disabled={note.trim().length < 3}
              onClick={() => answer("confirmed")}
            >
              It was real
            </button>
            <button className="btn" type="button" onClick={() => setAsking(false)}>
              Cancel
            </button>
          </p>
        </div>
      )}
    </li>
  );
}

function AlertList() {
  const { can } = useAuth();
  const [rows, setRows] = useState<FraudAlert[]>([]);
  const [filter, setFilter] = useState<"open" | "all">("open");
  const [severity, setSeverity] = useState("");
  const [kind, setKind] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setRows(
        await api.fraudAlerts({
          status_filter: filter === "open" ? "open" : undefined,
          severity: severity || undefined,
          kind: kind || undefined,
        }),
      );
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [filter, severity, kind]);
  useEffect(() => {
    void load();
    const timer = setInterval(load, 60000);
    return () => clearInterval(timer);
  }, [load]);
  async function scan() {
    setError(null);
    setMessage(null);
    try {
      const { raised } = await api.scanNow();
      setMessage(raised ? `${raised} new alert${raised === 1 ? "" : "s"} found.` : "Nothing new.");
      await load();
    } catch (e) {
      setError(errorMessage(e));
    }
  }
  return (
    <>
      <ErrorBanner message={error} />
      {message && (
        <p className="banner ok" role="status">
          {message}
        </p>
      )}
      <Card title="Alerts">
        <p className="muted">
          Everything the fraud checks found, with the numbers behind it. Red ones are the serious
          ones. Say whether each was explained or real: the answers show which checks are worth
          their noise.
        </p>
        <div className="form-grid">
          <Field label="Show">
            <select value={filter} onChange={(e) => setFilter(e.target.value as "open" | "all")}>
              <option value="open">Waiting for an answer</option>
              <option value="all">All</option>
            </select>
          </Field>
          <Field label="Severity">
            <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
              <option value="">Red and amber</option>
              <option value="red">Red</option>
              <option value="amber">Amber</option>
            </select>
          </Field>
          <Field label="Kind">
            <select value={kind} onChange={(e) => setKind(e.target.value)}>
              <option value="">Everything</option>
              {Object.entries(FRAUD_KIND).map(([k, text]) => (
                <option key={k} value={k}>
                  {text}
                </option>
              ))}
            </select>
          </Field>
          {can("alerts.manage") && (
            <button className="btn" type="button" onClick={scan}>
              <RefreshCw size={16} /> Check now
            </button>
          )}
        </div>
        {rows.length === 0 && <p className="muted">No alerts.</p>}
        <ul className="list">
          {rows.map((a) => (
            <AlertRow key={a.id} a={a} onChanged={load} />
          ))}
        </ul>
      </Card>
    </>
  );
}

function Summary() {
  const [data, setData] = useState<FraudSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api
      .fraudSummary()
      .then(setData)
      .catch((e) => setError(errorMessage(e)));
  }, []);
  return (
    <Card title="How often each check is right (last 90 days)">
      <ErrorBanner message={error} />
      {data && (
        <p>
          <span className="status bad">{data.open.red} red</span>{" "}
          <span className="status warn">{data.open.amber} amber</span>{" "}
          <span className="muted">waiting for an answer</span>
        </p>
      )}
      <p className="muted">
        A check that is almost always explained is too sensitive: loosen its threshold in the
        settings. One that is often real is worth keeping, or tightening.
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Check</th>
              <th>Raised</th>
              <th>Waiting</th>
              <th>Explained</th>
              <th>Real</th>
              <th>Real, of those answered</th>
            </tr>
          </thead>
          <tbody>
            {data?.kinds.map((k) => (
              <tr key={k.kind}>
                <td>{k.label}</td>
                <td>{k.total}</td>
                <td>{k.open}</td>
                <td>{k.explained}</td>
                <td>{k.confirmed}</td>
                <td>{k.confirmed_pct === null ? "" : `${k.confirmed_pct}%`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function Settings() {
  const [data, setData] = useState<FraudSettings | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [channels, setChannels] = useState<FraudSettings["channels"] | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const adopt = useCallback((s: FraudSettings) => {
    setData(s);
    setChannels(s.channels);
    setValues(Object.fromEntries(Object.entries(s.thresholds).map(([k, v]) => [k, String(v)])));
  }, []);
  useEffect(() => {
    api
      .fraudSettings()
      .then(adopt)
      .catch((e) => setError(errorMessage(e)));
  }, [adopt]);
  const keys = useMemo(() => Object.keys(THRESHOLD_TEXT) as (keyof FraudThresholds)[], []);
  async function save(e: FormEvent) {
    e.preventDefault();
    if (!data || !channels) return;
    setError(null);
    setMessage(null);
    try {
      adopt(
        await api.saveFraudSettings({
          thresholds: Object.fromEntries(keys.map((k) => [k, Number(values[k])])),
          channels,
        }),
      );
      setMessage("Saved. The new thresholds apply from the next check.");
    } catch (err) {
      setError(errorMessage(err));
    }
  }
  function toggle(severity: "red" | "amber", field: "roles" | "channels", item: string) {
    if (!channels) return;
    const have = channels[severity][field];
    setChannels({
      ...channels,
      [severity]: {
        ...channels[severity],
        [field]: have.includes(item) ? have.filter((x) => x !== item) : [...have, item],
      },
    });
  }
  if (!data || !channels) return <ErrorBanner message={error} />;
  return (
    <form onSubmit={save}>
      <ErrorBanner message={error} />
      {message && (
        <p className="banner ok" role="status">
          {message}
        </p>
      )}
      <Card title="How strict the checks are">
        <p className="muted">
          Each has a built-in default (shown beside it). Change one to suit your routes and your
          lorries.
        </p>
        <div className="form-grid">
          {keys.map((k) => {
            const [title, unit, help] = THRESHOLD_TEXT[k]!;
            const [low, high] = data.limits[k];
            return (
              <Field key={k} label={`${title} (${unit})`}>
                <input
                  type="number"
                  step="any"
                  min={low}
                  max={high}
                  value={values[k] ?? ""}
                  onChange={(e) => setValues({ ...values, [k]: e.target.value })}
                  required
                />
                <small className="muted">
                  {help} Default {data.defaults[k]}; allowed {low} to {high}.
                </small>
              </Field>
            );
          })}
        </div>
      </Card>
      <Card title="Who is told, and how">
        <p className="muted">
          Every alert shows in the app. Choose who is also texted or emailed, for red and amber
          separately.
        </p>
        {(["red", "amber"] as const).map((sev) => (
          <fieldset key={sev}>
            <legend>{sev === "red" ? "Red alerts (serious)" : "Amber alerts"}</legend>
            <p>
              {data.roles.map((r) => (
                <label key={r} className="check">
                  <input
                    type="checkbox"
                    checked={channels[sev].roles.includes(r)}
                    onChange={() => toggle(sev, "roles", r)}
                  />
                  <span>{r}</span>
                </label>
              ))}
            </p>
            <p>
              {data.channel_names.map((c) => (
                <label key={c} className="check">
                  <input
                    type="checkbox"
                    checked={channels[sev].channels.includes(c)}
                    onChange={() => toggle(sev, "channels", c)}
                  />
                  <span>{c === "sms" ? "Text message" : "Email"}</span>
                </label>
              ))}
            </p>
          </fieldset>
        ))}
        <button className="btn primary" type="submit">
          <Save size={16} /> Save
        </button>
      </Card>
    </form>
  );
}

/** A trip's own alerts, on the trip page. */
export function TripAlertsCard({ tripId }: { tripId: string }) {
  const { can } = useAuth();
  const [rows, setRows] = useState<FraudAlert[]>([]);
  const load = useCallback(() => {
    if (can("alerts.view"))
      api
        .fraudAlerts({ trip_id: tripId })
        .then(setRows)
        .catch(() => undefined);
  }, [tripId, can]);
  useEffect(load, [load]);
  if (!can("alerts.view") || rows.length === 0) return null;
  return (
    <Card title="Alerts on this trip">
      <ul className="list">
        {rows.map((a) => (
          <AlertRow key={a.id} a={a} onChanged={load} />
        ))}
      </ul>
    </Card>
  );
}

export default function Alerts() {
  const { can } = useAuth();
  return (
    <>
      <h2>Alerts</h2>
      <nav className="tabs">
        <NavLink to="/alerts" end>
          Alerts
        </NavLink>
        <NavLink to="/alerts/summary">How often right</NavLink>
        {can("alerts.settings") && <NavLink to="/alerts/settings">Settings</NavLink>}
      </nav>
      <Routes>
        <Route index element={<AlertList />} />
        <Route path="summary" element={<Summary />} />
        {can("alerts.settings") && <Route path="settings" element={<Settings />} />}
      </Routes>
    </>
  );
}
