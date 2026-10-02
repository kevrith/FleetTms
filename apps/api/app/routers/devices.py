import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.db import get_db
from app.deps import Principal, require, require_any
from app.models import DeviceCheck
from app.routers.vehicles import get_vehicle
from app.trust import flag_summary, trust_out

router = APIRouter(tags=["devices"])
CLOCK_TOLERANCE_S = 300  # a phone clock more than five minutes off is flagged


class DeviceIn(BaseModel):
    device_id: str = Field(min_length=3, max_length=80)
    mock_location: bool = False  # the phone says a mock-location app is supplying the position
    rooted: bool = False
    device_time: datetime | None = None  # the phone's own idea of "now"
    app_version: str | None = Field(default=None, max_length=40)
    vehicle_id: uuid.UUID | None = None


async def record_device(db: AsyncSession, principal: Principal, report: DeviceIn) -> list[str]:
    """Stores a report only when something is wrong, and returns the flags. Flags are recorded, never blocking."""
    flags: list[str] = []
    offset = None
    if report.device_time is not None:
        when = report.device_time if report.device_time.tzinfo else report.device_time.replace(tzinfo=UTC)
        offset = int((when - datetime.now(UTC)).total_seconds())
        if abs(offset) > CLOCK_TOLERANCE_S:
            flags.append("clock_changed")
    if report.mock_location:
        flags.append("mock_location")
    if report.rooted:
        flags.append("rooted")
    if not flags:
        return []
    vehicle_id = None
    if report.vehicle_id is not None:
        vehicle_id = (await get_vehicle(db, principal, report.vehicle_id)).id
    db.add(
        DeviceCheck(
            user_id=principal.user.id, vehicle_id=vehicle_id, device_id=report.device_id, flags=flags,
            clock_offset_s=offset, app_version=report.app_version,
        )
    )  # fmt: skip
    audit.record(
        db, actor_user_id=principal.user.id, action="device.flagged", entity_type="device", entity_id=report.device_id,
        after={"flags": flags, "vehicle_id": str(vehicle_id) if vehicle_id else None, "clock_offset_s": offset},
    )  # fmt: skip
    return flags


@router.post("/devices/integrity")
async def report_integrity(
    body: DeviceIn,
    principal: Principal = Depends(require_any("trips.own", "trips.manage")),
    db: AsyncSession = Depends(get_db),
):
    flags = await record_device(db, principal, body)
    await db.commit()
    return {"flags": flags, "server_time": datetime.now(UTC)}


@router.get("/vehicles/{vehicle_id}/trust")
async def vehicle_trust(
    vehicle_id: uuid.UUID, principal: Principal = Depends(require("vehicles.view")), db: AsyncSession = Depends(get_db)
):
    vehicle = await get_vehicle(db, principal, vehicle_id)
    return trust_out(vehicle, (await flag_summary(db, [vehicle.id])).get(vehicle.id, {}))
