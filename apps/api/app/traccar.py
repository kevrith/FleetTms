"""Traccar (masterplan Section 7): the open-source server that speaks to hundreds of tracker brands. It forwards each position and
event as JSON to our webhook, and takes commands (the immobiliser) over its REST API. Everything Traccar-shaped stays in this file.

Traccar names a device by its unique id, which for most trackers is the IMEI; speeds arrive in knots."""

import logging
from datetime import UTC, datetime
from typing import Protocol

import httpx

from app.config import settings

log = logging.getLogger(__name__)
KNOTS_TO_KMH = 1.852

# Traccar alarm names and what we do with them. Tamper alarms raise an alert at once; driving alarms become behaviour events.
TAMPER_ALARMS = {
    "powerCut": "power_cut", "powerOff": "power_cut", "removing": "power_cut", "gpsAntennaCut": "power_cut",
    "lowBattery": "low_battery", "lowPower": "low_battery", "jamming": "gps_jamming", "tampering": "tamper",
    "bonnet": "tamper", "sos": "sos", "tow": "tamper",
}  # fmt: skip
RESTORED_ALARMS = {"powerRestored": "power_cut", "powerOn": "power_cut"}  # also closes an open power_cut alert
DRIVING_ALARMS = {"hardAcceleration": "harsh_acceleration", "hardBraking": "harsh_braking", "hardCornering": "harsh_cornering", "overspeed": "speeding", "fatigueDriving": "long_driving", "idle": "idling"}  # fmt: skip
EVENT_TYPES = {"deviceOffline": "offline", "deviceOnline": "online", "deviceUnknown": "online", "commandResult": "command_result"}


class TraccarError(Exception):
    """Traccar did not take the command. The text is safe to show to the owner."""


def parse_time(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        t = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def parse_position(pos: dict) -> dict | None:
    """A Traccar position as the fields we use, or None if it has no time or place."""
    at = parse_time(pos.get("fixTime") or pos.get("deviceTime") or pos.get("serverTime"))
    lat, lng = pos.get("latitude"), pos.get("longitude")
    if at is None or lat is None or lng is None:
        return None
    attrs = pos.get("attributes") or {}
    knots = pos.get("speed")
    power = attrs.get("power")
    return {
        "at": at, "lat": float(lat), "lng": float(lng), "valid": bool(pos.get("valid", True)), "speed_kmh": round(float(knots) * KNOTS_TO_KMH, 1) if knots is not None else None,
        "heading": float(pos["course"]) if pos.get("course") is not None else None, "accuracy_m": float(pos["accuracy"]) if pos.get("accuracy") else None,
        "ignition": attrs.get("ignition"), "alarm": attrs.get("alarm"), "battery_pct": attrs.get("batteryLevel"), "power_v": float(power) if power is not None else None,
        "gsm": attrs.get("rssi"), "satellites": attrs.get("sat"),
    }  # fmt: skip


def parse_forward(body: dict) -> dict:
    """What Traccar's forwarder posts, as {imei, position?, event?}. A position post is {position, device}; an event post
    is {event, position?, device}."""
    device = body.get("device") or {}
    imei = str(device.get("uniqueId") or "").strip()
    position = parse_position(body["position"]) if body.get("position") else None
    event = None
    if body.get("event"):
        ev = body["event"]
        attrs = ev.get("attributes") or {}
        event = {"type": ev.get("type"), "at": parse_time(ev.get("eventTime")), "alarm": attrs.get("alarm"), "result": attrs.get("result")}
    return {"imei": imei, "position": position, "event": event}


class TraccarClient(Protocol):
    async def send_command(self, imei: str, command: str) -> None: ...


class FakeTraccar:
    """Keeps the commands that would have been sent, so tests and development can see them."""

    def __init__(self) -> None:
        self.commands: list[tuple[str, str]] = []
        self.fail_with: str | None = None

    async def send_command(self, imei: str, command: str) -> None:
        if self.fail_with:
            raise TraccarError(self.fail_with)
        self.commands.append((imei, command))
        log.info("Fake Traccar command %s for a device", command)


class RestTraccar:
    async def send_command(self, imei: str, command: str) -> None:
        base, headers = settings.traccar_url.rstrip("/"), {"Authorization": f"Bearer {settings.traccar_token}"}
        try:
            async with httpx.AsyncClient(timeout=20) as http:
                found = await http.get(f"{base}/api/devices", params={"uniqueId": imei}, headers=headers)
                found.raise_for_status()
                devices = found.json()
                if not devices:  # Traccar's uniqueId lookup only sees devices linked to the token's user; an admin can list them all
                    everything = await http.get(f"{base}/api/devices", params={"all": "true"}, headers=headers)
                    everything.raise_for_status()
                    devices = [d for d in everything.json() if str(d.get("uniqueId")) == imei]
                if not devices:
                    raise TraccarError("Traccar does not know that device.")
                sent = await http.post(f"{base}/api/commands/send", headers=headers, json={"deviceId": devices[0]["id"], "type": command, "attributes": {}})
                sent.raise_for_status()
        except httpx.HTTPError as e:
            raise TraccarError(f"Traccar did not accept the command: {type(e).__name__}") from e


_fake = FakeTraccar()


def get_traccar() -> TraccarClient:
    return RestTraccar() if settings.traccar_url and settings.traccar_token else _fake


def fake_traccar() -> FakeTraccar:
    return _fake


def is_live() -> bool:
    return bool(settings.traccar_url and settings.traccar_token)
