"""The remote engine immobiliser (masterplan 5.28, Section 10): owner only, a stopped vehicle only, two steps, everything audit-logged."""

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, immobiliser
from app.db import get_db
from app.deps import Principal, error, require
from app.models import ImmobiliserCommand, Vehicle
from app.security import verify_password

router = APIRouter(tags=["immobiliser"])
USE = "immobiliser.use"


class RequestIn(BaseModel):
    action: Literal["immobilise", "release"]
    reason: str = Field(min_length=3, max_length=255)  # why: recorded with the command


class ConfirmIn(BaseModel):
    registration: str = Field(min_length=3, max_length=20)  # the vehicle's number plate, typed, so the right lorry is certain
    password: str = Field(min_length=1, max_length=200)


def command_out(c: ImmobiliserCommand, registration: str | None = None) -> dict:
    return {
        "id": c.id, "vehicle_id": c.vehicle_id, "registration": registration, "action": c.action, "status": c.status, "reason": c.reason, "speed_kmh": c.speed_kmh, "position_age_s": c.position_age_s,
        "requested_at": c.requested_at, "expires_at": c.expires_at, "confirmed_at": c.confirmed_at, "sent_at": c.sent_at, "result_at": c.result_at, "result_note": c.result_note,
    }  # fmt: skip


async def _vehicle(db: AsyncSession, vehicle_id: uuid.UUID) -> Vehicle:
    v = (await db.execute(select(Vehicle).where(Vehicle.id == vehicle_id))).scalar_one_or_none()
    if v is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That vehicle was not found.")
    return v


async def _command(db: AsyncSession, command_id: uuid.UUID) -> ImmobiliserCommand:
    c = (await db.execute(select(ImmobiliserCommand).where(ImmobiliserCommand.id == command_id).with_for_update())).scalar_one_or_none()
    if c is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That request was not found.")
    return c


@router.get("/vehicles/{vehicle_id}/immobiliser")
async def immobiliser_state(vehicle_id: uuid.UUID, principal: Principal = Depends(require(USE)), db: AsyncSession = Depends(get_db)):
    """Whether the engine can be stopped right now (and why not), whether it is stopped, and what has been asked of it."""
    vehicle = await _vehicle(db, vehicle_id)
    device = await immobiliser.active_device(db, vehicle.id)
    history = (await db.execute(select(ImmobiliserCommand).where(ImmobiliserCommand.vehicle_id == vehicle.id).order_by(ImmobiliserCommand.requested_at.desc()).limit(20))).scalars().all()
    out: dict = {"vehicle_id": vehicle.id, "registration": vehicle.registration, "has_tracker": device is not None, "history": [command_out(c, vehicle.registration) for c in history]}
    if device is None:
        return {**out, "supported": False, "immobilised": False, "can_immobilise": False, "reason": "no_tracker", "message": "This vehicle has no tracker."}
    ctx = await immobiliser.context(db, device)
    allowed, reason = immobiliser.verdict("immobilise", ctx)
    return {**out, "supported": device.supports_immobiliser, "immobilised": device.immobilised, "can_immobilise": allowed, "reason": reason, "message": immobiliser.message_for(reason), "speed_kmh": ctx["speed_kmh"], "position_age_s": ctx["position_age_s"], "online": ctx["online"]}


@router.post("/vehicles/{vehicle_id}/immobiliser", status_code=status.HTTP_201_CREATED)
async def request_command(vehicle_id: uuid.UUID, body: RequestIn, principal: Principal = Depends(require(USE)), db: AsyncSession = Depends(get_db)):
    """Step one. The safety rules are checked now and the request is written down either way. A refusal says why and sends nothing."""
    vehicle = await _vehicle(db, vehicle_id)
    device = await immobiliser.active_device(db, vehicle.id)
    if device is None:
        raise error(422, "no_tracker", "This vehicle has no tracker.")
    ctx = await immobiliser.context(db, device)
    allowed, reason = immobiliser.verdict(body.action, ctx)
    cmd = ImmobiliserCommand(
        vehicle_id=vehicle.id, device_id=device.id, action=body.action, reason=body.reason, speed_kmh=ctx["speed_kmh"], position_age_s=ctx["position_age_s"], requested_by_user_id=principal.user.id,
        expires_at=datetime.now(UTC) + immobiliser.CONFIRM_WINDOW, status="awaiting_confirmation" if allowed else "refused", result_note=None if allowed else immobiliser.message_for(reason),
    )  # fmt: skip
    db.add(cmd)
    await db.flush()
    audit.record(
        db, actor_user_id=principal.user.id, action=f"immobiliser.{body.action}_requested" if allowed else "immobiliser.refused", entity_type="vehicle", entity_id=vehicle.id,
        after={"command_id": str(cmd.id), "speed_kmh": ctx["speed_kmh"], "position_age_s": ctx["position_age_s"], "refused_because": reason}, note=body.reason,
    )  # fmt: skip
    await db.commit()
    if not allowed:
        raise error(status.HTTP_409_CONFLICT, reason or "refused", immobiliser.message_for(reason) or "That is not allowed right now.")
    return command_out(cmd, vehicle.registration)


@router.post("/immobiliser/{command_id}/confirm")
async def confirm_command(command_id: uuid.UUID, body: ConfirmIn, principal: Principal = Depends(require(USE)), db: AsyncSession = Depends(get_db)):
    """Step two. The registration is typed, the owner's password given, the safety rules checked again with the newest position, and
    only then is the command sent to the tracker."""
    cmd = await _command(db, command_id)
    vehicle = await _vehicle(db, cmd.vehicle_id)
    if cmd.status != "awaiting_confirmation":
        raise error(status.HTTP_409_CONFLICT, "not_waiting", "That request is not waiting for confirmation.")
    if cmd.expires_at <= datetime.now(UTC):
        cmd.status = "expired"
        await db.commit()
        raise error(status.HTTP_410_GONE, "expired", "That request has expired. Start again.")
    if "".join(body.registration.upper().split()) != "".join(vehicle.registration.upper().split()):
        raise error(422, "wrong_registration", "That is not this vehicle's registration. Type it exactly to be sure it is the right lorry.")
    if not verify_password(body.password, principal.user.password_hash):
        audit.record(db, actor_user_id=principal.user.id, action="immobiliser.wrong_password", entity_type="vehicle", entity_id=vehicle.id, after={"command_id": str(cmd.id)})
        await db.commit()
        raise error(status.HTTP_403_FORBIDDEN, "wrong_password", "That password is not right.")
    device = await immobiliser.active_device(db, vehicle.id)
    if device is None or device.id != cmd.device_id:
        raise error(409, "no_tracker", "The tracker has changed. Start again.")
    ctx = await immobiliser.context(db, device)
    allowed, reason = immobiliser.verdict(cmd.action, ctx)  # the vehicle may have started moving since the request
    cmd.confirmed_at = datetime.now(UTC)
    if not allowed:
        cmd.status, cmd.result_note, cmd.result_at = "refused", immobiliser.message_for(reason), datetime.now(UTC)
        audit.record(db, actor_user_id=principal.user.id, action="immobiliser.refused", entity_type="vehicle", entity_id=vehicle.id, after={"command_id": str(cmd.id), "refused_because": reason, "at": "confirmation"}, note=cmd.reason)
        await db.commit()
        raise error(status.HTTP_409_CONFLICT, reason or "refused", immobiliser.message_for(reason) or "That is not allowed right now.")
    cmd.speed_kmh, cmd.position_age_s = ctx["speed_kmh"], ctx["position_age_s"]
    try:
        await immobiliser.send(db, cmd, device, principal.user.id, vehicle)
    except immobiliser.ImmobiliserError as e:
        await db.commit()
        raise error(502, e.code, e.message) from None
    await db.commit()
    return command_out(cmd, vehicle.registration)


@router.post("/immobiliser/{command_id}/cancel")
async def cancel_command(command_id: uuid.UUID, principal: Principal = Depends(require(USE)), db: AsyncSession = Depends(get_db)):
    cmd = await _command(db, command_id)
    if cmd.status != "awaiting_confirmation":
        raise error(status.HTTP_409_CONFLICT, "not_waiting", "That request is not waiting for confirmation.")
    cmd.status, cmd.result_at = "cancelled", datetime.now(UTC)
    audit.record(db, actor_user_id=principal.user.id, action="immobiliser.cancelled", entity_type="vehicle", entity_id=cmd.vehicle_id, after={"command_id": str(cmd.id)})
    await db.commit()
    return command_out(cmd)
