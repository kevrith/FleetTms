"""The remote engine immobiliser (masterplan 5.28, Section 10). Owner only. Two steps: a request, which is checked for safety and
written down, and a confirmation, which needs the registration typed and the owner's password and checks safety again with the
latest data before anything is sent. Every step is audit-logged, refusals included."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, immobiliser_rules
from app.models import ImmobiliserCommand, LocationPoint, TrackerDevice, Vehicle
from app.traccar import TraccarError, get_traccar

CONFIRM_WINDOW = timedelta(minutes=2)
COMMANDS = {"immobilise": "engineStop", "release": "engineResume"}


class ImmobiliserError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


async def active_device(db: AsyncSession, vehicle_id: uuid.UUID) -> TrackerDevice | None:
    return (await db.execute(select(TrackerDevice).where(TrackerDevice.vehicle_id == vehicle_id, TrackerDevice.is_active.is_(True)).order_by(TrackerDevice.supports_immobiliser.desc(), TrackerDevice.created_at))).scalars().first()


async def context(db: AsyncSession, device: TrackerDevice, now: datetime | None = None) -> dict:
    """What the safety rules look at, from the freshest position the vehicle has reported."""
    now = now or datetime.now(UTC)
    last = (await db.execute(select(LocationPoint).where(LocationPoint.vehicle_id == device.vehicle_id).order_by(LocationPoint.recorded_at.desc()).limit(1))).scalar_one_or_none()
    online = device.online_state != "offline" and device.last_seen_at is not None and now - device.last_seen_at <= timedelta(minutes=10)
    return {"speed_kmh": last.speed_kmh if last else None, "position_age_s": int((now - last.recorded_at).total_seconds()) if last else None, "online": online, "supported": device.supports_immobiliser}


def verdict(action: str, ctx: dict) -> tuple[bool, str | None]:
    return immobiliser_rules.check(action=action, speed_kmh=ctx["speed_kmh"], position_age_s=ctx["position_age_s"], online=ctx["online"], supported=ctx["supported"])


def message_for(code: str | None) -> str | None:
    return immobiliser_rules.REASONS.get(code or "")


async def send(db: AsyncSession, cmd: ImmobiliserCommand, device: TrackerDevice, actor_id: uuid.UUID, vehicle: Vehicle) -> None:
    """Hands the command to Traccar. A refusal from Traccar is recorded and shown, not hidden."""
    now = datetime.now(UTC)
    try:
        await get_traccar().send_command(device.imei, COMMANDS[cmd.action])
    except TraccarError as e:
        cmd.status, cmd.result_at, cmd.result_note = "failed", now, str(e)[:255]
        audit.record(db, actor_user_id=actor_id, action="immobiliser.failed", entity_type="vehicle", entity_id=vehicle.id, after={"command_id": str(cmd.id), "action": cmd.action}, note=str(e))
        raise ImmobiliserError("traccar_failed", str(e)) from None
    cmd.status, cmd.sent_at = "sent", now
    audit.record(db, actor_user_id=actor_id, action=f"immobiliser.{cmd.action}_sent", entity_type="vehicle", entity_id=vehicle.id, after={"command_id": str(cmd.id), "speed_kmh": cmd.speed_kmh, "position_age_s": cmd.position_age_s}, note=cmd.reason)
