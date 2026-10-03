"""A tracker data simulator (Sprint 12 brief). Builds what Traccar's forwarder would post for a tracker doing something: driving a
route with speeding, a hard stop and an idle stop, or having its power cut. Used by the tests and from the command line, so the map,
replay and alerts can be seen working without a tracker in a lorry.

    TRACCAR_FORWARD_KEY=... python -m app.tracker_simulator --imei 356938035643809 --scenario trip --url http://localhost:8010

Speeds in Traccar are in knots; these helpers take km/h and convert."""

import argparse
import asyncio
import os
from datetime import UTC, datetime, timedelta

import httpx

KMH_TO_KNOTS = 1 / 1.852
METRES_PER_DEGREE = 111_195


def stamp(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000+00:00")


def device(imei: str, status: str = "online") -> dict:
    return {"id": 1, "uniqueId": imei, "name": "Simulated tracker", "status": status}


def position(imei: str, at: datetime, lat: float, lng: float, *, speed_kmh: float = 0, course: float = 0, ignition: bool | None = True, alarm: str | None = None, power: float | None = 12.6, battery: float | None = None, valid: bool = True, fuel: float | None = None) -> dict:  # fmt: skip
    attributes: dict = {}
    if ignition is not None:
        attributes["ignition"] = ignition
    if alarm:
        attributes["alarm"] = alarm
    if power is not None:
        attributes["power"] = power
    if battery is not None:
        attributes["batteryLevel"] = battery
    if fuel is not None:
        attributes["fuel"] = fuel
    pos = {"id": 1, "deviceId": 1, "protocol": "simulated", "serverTime": stamp(at), "deviceTime": stamp(at), "fixTime": stamp(at), "valid": valid, "latitude": lat, "longitude": lng, "speed": round(speed_kmh * KMH_TO_KNOTS, 3), "course": course, "accuracy": 5.0, "attributes": attributes}  # fmt: skip
    return {"position": pos, "device": device(imei)}


def event(imei: str, type_: str, at: datetime, *, alarm: str | None = None, result: str | None = None) -> dict:
    attrs = {k: v for k, v in (("alarm", alarm), ("result", result)) if v}
    return {"event": {"id": 1, "type": type_, "eventTime": stamp(at), "deviceId": 1, "attributes": attrs}, "device": device(imei, "offline" if type_ == "deviceOffline" else "online")}


def trip(imei: str, start: datetime, lat: float = -4.0435, lng: float = 39.6682) -> list[dict]:
    """A drive north from Mombasa: sets off, cruises, speeds for a minute, brakes hard, idles twelve minutes with the engine on, then
    carries on. About twenty minutes of fixes."""
    out: list[dict] = []
    t, la = start, lat
    plan = [("sets off", 45, 60, 8), ("cruising", 62, 120, 5), ("speeding", 96, 60, 5), ("slowing", 60, 30, 5), ("hard stop", 20, 2, 1), ("stopped, engine on", 0, 720, 60), ("on again", 55, 120, 5)]
    for _name, speed, seconds, every in plan:
        for _ in range(max(1, seconds // every)):
            t += timedelta(seconds=every)
            la += (speed / 3.6) * every / METRES_PER_DEGREE
            out.append(position(imei, t, la, lng, speed_kmh=speed, course=0, ignition=True))
    return out


def power_cut(imei: str, at: datetime, lat: float = -1.2921, lng: float = 36.8219) -> list[dict]:
    """The tracker's supply is cut: it reports the alarm (on its backup battery) and the loss of power."""
    return [position(imei, at, lat, lng, speed_kmh=0, alarm="powerCut", power=0.0, battery=80, ignition=False)]


def jamming(imei: str, at: datetime, lat: float = -1.2921, lng: float = 36.8219) -> list[dict]:
    return [position(imei, at, lat, lng, speed_kmh=0, alarm="jamming")]


def offline(imei: str, at: datetime) -> list[dict]:
    return [event(imei, "deviceOffline", at)]


def siphon(imei: str, start: datetime, lat: float = -1.2921, lng: float = 36.8219, level: float = 280, taken: float = 50) -> list[dict]:
    """A lorry parked overnight with a fuel sensor: the level is steady for an hour, then falls by `taken` litres in about eight minutes."""
    out = [position(imei, start + timedelta(minutes=m), lat, lng, speed_kmh=0, ignition=False, fuel=level) for m in range(0, 61, 10)]
    steps = 5
    for i in range(1, steps + 1):
        out.append(position(imei, start + timedelta(minutes=60 + i), lat, lng, speed_kmh=0, ignition=False, fuel=level - taken * i / steps))
    out += [position(imei, start + timedelta(minutes=m), lat, lng, speed_kmh=0, ignition=False, fuel=level - taken) for m in range(75, 121, 15)]
    return out


def refuel(imei: str, start: datetime, lat: float = -1.2921, lng: float = 36.8219, level: float = 100, added: float = 100) -> list[dict]:
    """A lorry filling up at a pump: a steady low level, then `added` litres in about five minutes."""
    out = [position(imei, start + timedelta(minutes=m), lat, lng, speed_kmh=0, ignition=False, fuel=level) for m in range(0, 11, 5)]
    out += [position(imei, start + timedelta(minutes=10 + i), lat, lng, speed_kmh=0, ignition=False, fuel=level + added * i / 5) for i in range(1, 6)]
    out += [position(imei, start + timedelta(minutes=m), lat, lng, speed_kmh=0, ignition=False, fuel=level + added) for m in range(20, 41, 10)]
    return out


SCENARIOS = {"trip": lambda imei, now: trip(imei, now - timedelta(minutes=20)), "powercut": lambda imei, now: power_cut(imei, now), "jamming": lambda imei, now: jamming(imei, now), "offline": lambda imei, now: offline(imei, now), "siphon": lambda imei, now: siphon(imei, now - timedelta(minutes=125)), "refuel": lambda imei, now: refuel(imei, now - timedelta(minutes=45))}


async def post_all(url: str, key: str, payloads: list[dict], delay: float = 0.0) -> int:
    sent = 0
    async with httpx.AsyncClient(timeout=20) as http:
        for body in payloads:
            res = await http.post(f"{url.rstrip('/')}/hooks/traccar/{key}", json=body)
            res.raise_for_status()
            sent += 1
            if delay:
                await asyncio.sleep(delay)
    return sent


def main() -> None:
    parser = argparse.ArgumentParser(description="Send simulated tracker data to the API, as Traccar would.")
    parser.add_argument("--imei", required=True)
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="trip")
    parser.add_argument("--url", default="http://localhost:8010")
    parser.add_argument("--delay", type=float, default=0.0, help="seconds between posts, to watch it arrive")
    args = parser.parse_args()
    key = os.getenv("TRACCAR_FORWARD_KEY", "")
    if not key:
        raise SystemExit("Set TRACCAR_FORWARD_KEY in .env (the same value the API uses).")
    payloads = SCENARIOS[args.scenario](args.imei, datetime.now(UTC))
    print(f"Sent {asyncio.run(post_all(args.url, key, payloads, args.delay))} messages for scenario '{args.scenario}'.")


if __name__ == "__main__":
    main()
