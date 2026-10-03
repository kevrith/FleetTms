/**
 * Driving behaviour and idling (masterplan 5.25): speeding, harsh braking, harsh acceleration, sharp cornering, idling with the
 * engine on, night driving and long driving without rest. Mirrored by apps/api/app/behaviour_rules.py and tested against
 * behaviour-cases.json on both sides. `step` takes a vehicle's remembered state and its next fix, in time order.
 */

export interface BehaviourConfig {
  speed_limit_kmh: number;
  over_speed_seconds: number;
  harsh_brake_kmh_s: number;
  harsh_accel_kmh_s: number;
  harsh_corner_ms2: number;
  corner_min_kmh: number;
  idle_minutes: number;
  moving_kmh: number;
  idle_kmh: number;
  night_from_hour: number;
  night_to_hour: number;
  long_drive_minutes: number;
  rest_minutes: number;
  gap_minutes: number;
  max_step_seconds: number;
  cooldown_seconds: number;
}

export const DEFAULT_BEHAVIOUR: BehaviourConfig = {
  speed_limit_kmh: 80,
  over_speed_seconds: 30,
  harsh_brake_kmh_s: 9,
  harsh_accel_kmh_s: 7,
  harsh_corner_ms2: 2.5,
  corner_min_kmh: 20,
  idle_minutes: 10,
  moving_kmh: 5,
  idle_kmh: 2,
  night_from_hour: 22,
  night_to_hour: 5,
  long_drive_minutes: 270,
  rest_minutes: 30,
  gap_minutes: 15,
  max_step_seconds: 5,
  cooldown_seconds: 10,
};

export interface BehaviourFix {
  /** ISO time. */
  at: string;
  speed: number | null;
  heading: number | null;
  ignition: boolean | null;
  lat?: number | null;
  lng?: number | null;
}

export interface BehaviourState {
  last: { at: string; speed: number | null; heading: number | null } | null;
  speeding: {
    since: string;
    max: number;
    lat?: number | null;
    lng?: number | null;
    last_over: string;
  } | null;
  idle: { since: string; lat?: number | null; lng?: number | null; last?: string } | null;
  drive: { since: string } | null;
  stop_since: string | null;
  long_fired: boolean;
  night: string | null;
  fired: Record<string, string>;
}

export interface BehaviourEvent {
  kind: string;
  at: string;
  ended_at: string | null;
  value: number | null;
  limit: number | null;
}

export const newBehaviourState = (): BehaviourState => ({
  last: null,
  speeding: null,
  idle: null,
  drive: null,
  stop_since: null,
  long_fired: false,
  night: null,
  fired: {},
});

const ms = (iso: string) => Date.parse(iso);
const seconds = (a: string, b: string) => (ms(a) - ms(b)) / 1000;
const iso = (t: number) => new Date(t).toISOString();
const round = (x: number, d: number) => Math.round(x * 10 ** d) / 10 ** d;

export function headingChange(a: number, b: number): number {
  const d = Math.abs(a - b) % 360;
  return d > 180 ? 360 - d : d;
}

function nairobiParts(t: string) {
  const hour = Number(
    new Intl.DateTimeFormat("en-GB", {
      timeZone: "Africa/Nairobi",
      hour: "2-digit",
      hourCycle: "h23",
    }).format(new Date(t)),
  );
  const day = new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Nairobi" }).format(new Date(t));
  return { hour, day };
}

function inNight(t: string, cfg: BehaviourConfig): { night: boolean; began: string } {
  const { hour, day } = nairobiParts(t);
  const night = hour >= cfg.night_from_hour || hour < cfg.night_to_hour;
  const began = hour >= cfg.night_from_hour ? day : nairobiParts(iso(ms(t) - 86_400_000)).day;
  return { night, began };
}

export function behaviourStep(
  state: BehaviourState,
  p: BehaviourFix,
  cfg: BehaviourConfig = DEFAULT_BEHAVIOUR,
): { state: BehaviourState; events: BehaviourEvent[] } {
  const s: BehaviourState = { ...state, fired: { ...state.fired } };
  const events: BehaviourEvent[] = [];
  const at = new Date(p.at).toISOString();
  const speed = p.speed;
  const last = s.last;
  if (last !== null && ms(at) <= ms(last.at)) return { state, events: [] };

  const fire = (kind: string, value: number | null, limit: number | null) => {
    const recent = s.fired[kind];
    if (recent && seconds(at, recent) < cfg.cooldown_seconds) return;
    s.fired[kind] = at;
    events.push({ kind, at, ended_at: null, value, limit });
  };
  const closeSpeeding = (end: string) => {
    const sp = s.speeding;
    if (sp === null) return;
    const secs = seconds(end, sp.since);
    if (secs >= cfg.over_speed_seconds) {
      events.push({
        kind: "speeding",
        at: sp.since,
        ended_at: end,
        value: sp.max,
        limit: cfg.speed_limit_kmh,
      });
    }
    s.speeding = null;
  };
  const closeIdle = (end: string) => {
    const idle = s.idle;
    if (idle === null) return;
    const minutes = seconds(end, idle.since) / 60;
    if (minutes >= cfg.idle_minutes) {
      events.push({
        kind: "idling",
        at: idle.since,
        ended_at: end,
        value: round(minutes, 1),
        limit: cfg.idle_minutes,
      });
    }
    s.idle = null;
  };

  if (last !== null && seconds(at, last.at) > cfg.gap_minutes * 60) {
    closeSpeeding(last.at);
    closeIdle(last.at);
    s.stop_since = s.stop_since ?? last.at;
  }
  const dt = last !== null ? seconds(at, last.at) : null;

  if (
    dt !== null &&
    dt > 0 &&
    dt <= cfg.max_step_seconds &&
    speed !== null &&
    last!.speed !== null
  ) {
    const accel = (speed - last!.speed) / dt;
    if (accel <= -cfg.harsh_brake_kmh_s)
      fire("harsh_braking", round(-accel, 1), cfg.harsh_brake_kmh_s);
    else if (accel >= cfg.harsh_accel_kmh_s)
      fire("harsh_acceleration", round(accel, 1), cfg.harsh_accel_kmh_s);
    if (
      p.heading !== null &&
      last!.heading !== null &&
      Math.min(speed, last!.speed) >= cfg.corner_min_kmh
    ) {
      const lateral =
        ((speed / 3.6) * ((headingChange(p.heading, last!.heading) * Math.PI) / 180)) / dt;
      if (lateral >= cfg.harsh_corner_ms2)
        fire("harsh_cornering", round(lateral, 2), cfg.harsh_corner_ms2);
    }
  }

  if (speed !== null) {
    if (speed > cfg.speed_limit_kmh) {
      const sp = s.speeding ?? { since: at, max: speed, lat: p.lat, lng: p.lng, last_over: at };
      s.speeding = { ...sp, max: Math.max(sp.max, speed), last_over: at };
    } else if (s.speeding !== null) {
      closeSpeeding(s.speeding.last_over);
    }
    if (p.ignition === true && speed < cfg.idle_kmh) {
      s.idle = { ...(s.idle ?? { since: at, lat: p.lat, lng: p.lng }), last: at };
    } else if (s.idle !== null) {
      closeIdle(s.idle.last ?? s.idle.since);
    }
    if (speed >= cfg.moving_kmh) {
      s.stop_since = null;
      if (s.drive === null) {
        s.drive = { since: at };
        s.long_fired = false;
      }
      const minutes = seconds(at, s.drive.since) / 60;
      if (minutes >= cfg.long_drive_minutes && !s.long_fired) {
        s.long_fired = true;
        fire("long_driving", round(minutes, 0), cfg.long_drive_minutes);
      }
      const { night, began } = inNight(at, cfg);
      if (night && s.night !== began) {
        s.night = began;
        fire("night_driving", speed, null);
      }
    } else {
      s.stop_since = s.stop_since ?? at;
      if (seconds(at, s.stop_since) / 60 >= cfg.rest_minutes) {
        s.drive = null;
        s.long_fired = false;
      }
    }
  }
  s.last = { at, speed, heading: p.heading };
  return { state: s, events };
}
