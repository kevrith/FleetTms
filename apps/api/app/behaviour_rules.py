"""Driving behaviour and idling (masterplan 5.25): speeding, harsh braking, harsh acceleration, sharp cornering, idling with the
engine on, night driving, and long driving without rest. The same rules as packages/business-rules/src/behaviour.ts, tested against
behaviour-cases.json on both sides.

`step` takes a vehicle's remembered state and its next fix and returns the new state and any events, so it works on fixes as they
arrive in batches, in time order. Episodes (speeding, idling) are reported when they end; the rest when they happen."""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

NAIROBI = ZoneInfo("Africa/Nairobi")


@dataclass(frozen=True)
class Config:
    speed_limit_kmh: float = 80  # the legal limit for a heavy lorry in Kenya
    over_speed_seconds: int = 30  # speeding must last this long to count
    harsh_brake_kmh_s: float = 9  # about 2.5 m/s squared
    harsh_accel_kmh_s: float = 7  # about 2.0 m/s squared
    harsh_corner_ms2: float = 2.5  # sideways acceleration
    corner_min_kmh: float = 20
    idle_minutes: int = 10
    moving_kmh: float = 5
    idle_kmh: float = 2
    night_from_hour: int = 22
    night_to_hour: int = 5
    long_drive_minutes: int = 270  # four and a half hours
    rest_minutes: int = 30
    gap_minutes: int = 15  # no fixes for this long closes any episode: we cannot say what happened in between
    max_step_seconds: int = 5  # harsh events need two fixes this close together
    cooldown_seconds: int = 10


DEFAULT = Config()


def new_state() -> dict:
    return {"last": None, "speeding": None, "idle": None, "drive": None, "stop_since": None, "long_fired": False, "night": None, "fired": {}}


def _iso(t: datetime) -> str:
    return t.isoformat()


def _parse(s: str) -> datetime:
    return datetime.fromisoformat(s)


def heading_change(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return 360 - d if d > 180 else d


def _in_night(t: datetime, cfg: Config) -> tuple[bool, str]:
    """(is it night in Nairobi, the date the night began on)."""
    local = t.astimezone(NAIROBI)
    hour = local.hour
    night = hour >= cfg.night_from_hour or hour < cfg.night_to_hour
    began = local.date() if hour >= cfg.night_from_hour else (local - timedelta(days=1)).date()
    return night, began.isoformat()


def step(state: dict, p: dict, cfg: Config = DEFAULT) -> tuple[dict, list[dict]]:
    """p is {at: datetime, speed: km/h or None, heading: degrees or None, ignition: bool or None, lat, lng}."""
    s = {**state, "fired": dict(state.get("fired", {}))}
    events: list[dict] = []
    at, speed = p["at"], p.get("speed")
    last = s["last"]
    if last is not None and at <= _parse(last["at"]):
        return state, []  # not newer than what we have: already counted
    where = {"lat": p.get("lat"), "lng": p.get("lng")}

    def fire(kind: str, **extra) -> None:
        recent = s["fired"].get(kind)
        if recent and (at - _parse(recent)).total_seconds() < cfg.cooldown_seconds:
            return
        s["fired"][kind] = _iso(at)
        events.append({"kind": kind, "at": at, "ended_at": None, **where, **extra})

    def close_speeding(end: datetime) -> None:
        sp = s["speeding"]
        if sp is None:
            return
        seconds = (end - _parse(sp["since"])).total_seconds()
        if seconds >= cfg.over_speed_seconds:
            events.append({"kind": "speeding", "at": _parse(sp["since"]), "ended_at": end, "value": sp["max"], "limit": cfg.speed_limit_kmh, "lat": sp["lat"], "lng": sp["lng"], "seconds": int(seconds)})
        s["speeding"] = None

    def close_idle(end: datetime) -> None:
        idle = s["idle"]
        if idle is None:
            return
        minutes = (end - _parse(idle["since"])).total_seconds() / 60
        if minutes >= cfg.idle_minutes:
            events.append({"kind": "idling", "at": _parse(idle["since"]), "ended_at": end, "value": round(minutes, 1), "limit": cfg.idle_minutes, "lat": idle["lat"], "lng": idle["lng"]})
        s["idle"] = None

    gap = last is not None and (at - _parse(last["at"])).total_seconds() > cfg.gap_minutes * 60
    if gap:
        end = _parse(last["at"])
        close_speeding(end)
        close_idle(end)
        s["stop_since"] = s["stop_since"] or last["at"]
    dt = (at - _parse(last["at"])).total_seconds() if last is not None else None

    # harsh events need two close fixes with speeds
    if dt is not None and 0 < dt <= cfg.max_step_seconds and speed is not None and last["speed"] is not None:
        accel = (speed - last["speed"]) / dt
        if accel <= -cfg.harsh_brake_kmh_s:
            fire("harsh_braking", value=round(-accel, 1), limit=cfg.harsh_brake_kmh_s)
        elif accel >= cfg.harsh_accel_kmh_s:
            fire("harsh_acceleration", value=round(accel, 1), limit=cfg.harsh_accel_kmh_s)
        if p.get("heading") is not None and last["heading"] is not None and min(speed, last["speed"]) >= cfg.corner_min_kmh:
            lateral = (speed / 3.6) * math.radians(heading_change(p["heading"], last["heading"])) / dt
            if lateral >= cfg.harsh_corner_ms2:
                fire("harsh_cornering", value=round(lateral, 2), limit=cfg.harsh_corner_ms2)

    if speed is not None:
        # speeding
        if speed > cfg.speed_limit_kmh:
            sp = s["speeding"] or {"since": _iso(at), "max": speed, "lat": where["lat"], "lng": where["lng"], "last_over": _iso(at)}
            sp = {**sp, "max": max(sp["max"], speed), "last_over": _iso(at)}
            s["speeding"] = sp
        elif s["speeding"] is not None:
            close_speeding(_parse(s["speeding"]["last_over"]))
        # idling: engine on, standing. Only a tracker knows the engine is on.
        ignition = p.get("ignition")
        if ignition is True and speed < cfg.idle_kmh:
            s["idle"] = s["idle"] or {"since": _iso(at), "lat": where["lat"], "lng": where["lng"]}
            s["idle"] = {**s["idle"], "last": _iso(at)}
        elif s["idle"] is not None:
            close_idle(_parse(s["idle"].get("last", s["idle"]["since"])))
        # long driving without rest
        moving = speed >= cfg.moving_kmh
        if moving:
            s["stop_since"] = None
            if s["drive"] is None:
                s["drive"] = {"since": _iso(at)}
                s["long_fired"] = False
            minutes = (at - _parse(s["drive"]["since"])).total_seconds() / 60
            if minutes >= cfg.long_drive_minutes and not s["long_fired"]:
                s["long_fired"] = True
                fire("long_driving", value=round(minutes, 0), limit=cfg.long_drive_minutes)
            night, began = _in_night(at, cfg)
            if night and s["night"] != began:
                s["night"] = began
                fire("night_driving", value=speed, limit=None)
        else:
            s["stop_since"] = s["stop_since"] or _iso(at)
            if (at - _parse(s["stop_since"])).total_seconds() / 60 >= cfg.rest_minutes:
                s["drive"], s["long_fired"] = None, False
    s["last"] = {"at": _iso(at), "speed": speed, "heading": p.get("heading")}
    return s, events
