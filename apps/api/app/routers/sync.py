"""Offline sync (masterplan Sections 4 and 13).

A phone that had no signal queues what the driver did, each action with an id the phone chose and the time the
driver did it. When the connection returns, the phone sends the queue here. Actions are applied in order, each on
its own; one that cannot be applied is rejected with a reason and the rest carry on. Sending the same batch twice
changes nothing: an action whose id has already been applied is answered with the original result.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import Principal, require_any
from app.models import SyncReceipt
from app.routers.devices import DeviceIn, record_device
from app.routers.fuel import FuelIn, do_add_fuel
from app.routers.inspections import InspectionIn, do_submit_inspection
from app.routers.trips import (
    ActionIn,
    LoadingIn,
    ReadingIn,
    do_end_trip,
    do_mark_delivered,
    do_record_loading,
    do_start_trip,
)

router = APIRouter(tags=["sync"])
log = logging.getLogger(__name__)
MAX_ACTIONS = 50
# A rejection that may clear up once the missing piece (usually a photo) has been uploaded.
RETRYABLE = {"photo_invalid", "photo_required"}


class SyncAction(BaseModel):
    client_id: uuid.UUID
    type: str = Field(max_length=40)
    payload: dict[str, Any] = {}


class SyncIn(BaseModel):
    actions: list[SyncAction] = Field(default_factory=list, max_length=MAX_ACTIONS)
    device: DeviceIn | None = None


async def _inspection(db: AsyncSession, who: Principal, p: dict) -> dict:
    vehicle_id = uuid.UUID(str(p.pop("vehicle_id")))
    done = await do_submit_inspection(db, who, vehicle_id, InspectionIn.model_validate(p))
    return {"id": str(done.id), "status": done.status.value}


async def _trip(handler, model, db: AsyncSession, who: Principal, p: dict) -> dict:
    trip_id = uuid.UUID(str(p.pop("trip_id")))
    trip = await handler(db, who, trip_id, model.model_validate(p))
    return {"id": str(trip.id), "status": trip.status.value}


async def _fuel(db: AsyncSession, who: Principal, p: dict) -> dict:
    entry, created = await do_add_fuel(db, who, FuelIn.model_validate(p))
    return {"id": str(entry.id), "created": created}


HANDLERS = {
    "inspection.submit": _inspection,
    "trip.start": lambda db, who, p: _trip(do_start_trip, ReadingIn, db, who, p),
    "trip.loading": lambda db, who, p: _trip(do_record_loading, LoadingIn, db, who, p),
    "trip.deliver": lambda db, who, p: _trip(do_mark_delivered, ActionIn, db, who, p),
    "trip.end": lambda db, who, p: _trip(do_end_trip, ReadingIn, db, who, p),
    "fuel.add": _fuel,
}


async def _apply(db: AsyncSession, who: Principal, action: SyncAction) -> dict:
    receipt = (await db.execute(select(SyncReceipt).where(SyncReceipt.client_id == action.client_id))).scalar_one_or_none()
    if receipt is not None:
        if receipt.user_id != who.user.id:  # never hand one person another person's result
            return {"client_id": action.client_id, "status": "rejected", "code": "client_id_in_use", "message": "That id belongs to someone else.", "retryable": False}
        return {"client_id": action.client_id, "status": "duplicate", "result": receipt.result}
    handler = HANDLERS.get(action.type)
    if handler is None:
        return {"client_id": action.client_id, "status": "rejected", "code": "unknown_action", "message": "This app version sent something the server does not know.", "retryable": False}
    try:
        async with db.begin_nested():  # a failed action undoes only itself
            result = await handler(db, who, dict(action.payload))
            db.add(SyncReceipt(client_id=action.client_id, action_type=action.type, result=result, user_id=who.user.id))
            await db.flush()
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        code = detail.get("code", "rejected")
        return {"client_id": action.client_id, "status": "rejected", "code": code, "message": detail.get("message", "Rejected."), "retryable": code in RETRYABLE}
    except (ValidationError, ValueError, KeyError):
        return {"client_id": action.client_id, "status": "rejected", "code": "invalid_action", "message": "That record is not valid.", "retryable": False}
    except IntegrityError:
        # Another request applied the same action a moment ago.
        return {"client_id": action.client_id, "status": "duplicate", "result": {}}
    except Exception:
        log.exception("Sync action %s failed", action.type)
        return {"client_id": action.client_id, "status": "rejected", "code": "server_error", "message": "The server could not apply this. It will be retried.", "retryable": True}
    return {"client_id": action.client_id, "status": "ok", "result": result}


@router.post("/sync")
async def sync(
    body: SyncIn,
    principal: Principal = Depends(require_any("trips.own", "trips.manage")),
    db: AsyncSession = Depends(get_db),
):
    flags: list[str] = []
    if body.device is not None:
        flags = await record_device(db, principal, body.device)
    results = [await _apply(db, principal, a) for a in body.actions]
    await db.commit()
    return {"server_time": datetime.now(UTC), "device_flags": flags, "results": results}
