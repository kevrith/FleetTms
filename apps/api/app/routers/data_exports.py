"""Full data export for owners: ask for a copy, see when it is ready, download it."""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, data_export, storage
from app.db import get_db
from app.deps import Principal, error, require
from app.models import DataExport

router = APIRouter(tags=["exports"])
PER_DAY = 5


class ExportIn(BaseModel):
    include_photos: bool = False


def out(e: DataExport) -> dict:
    return {"id": e.id, "status": e.status, "include_photos": e.include_photos, "size_bytes": e.size_bytes, "tables": e.tables, "error": e.error, "created_at": e.created_at, "ready_at": e.ready_at, "expires_at": e.expires_at}


@router.post("/data-exports", status_code=status.HTTP_202_ACCEPTED)
async def request_export(body: ExportIn, tasks: BackgroundTasks, principal: Principal = Depends(require("business.manage")), db: AsyncSession = Depends(get_db)):
    """Starts making a copy of everything the business has. It takes a minute or more; ask again for its state. Works when the account is read-only."""
    running = (await db.execute(select(DataExport.id).where(DataExport.status.in_(("queued", "running"))))).first()
    if running is not None:
        raise error(status.HTTP_409_CONFLICT, "export_running", "A copy is already being made. Wait for it to finish.")
    today = (await db.execute(select(func.count()).select_from(DataExport).where(DataExport.created_at >= datetime.now(UTC) - timedelta(days=1)))).scalar_one()
    if today >= PER_DAY:
        raise error(status.HTTP_429_TOO_MANY_REQUESTS, "too_many_exports", "That is enough copies for one day. Download one you already have, or ask again tomorrow.")
    export = DataExport(requested_by_user_id=principal.user.id, include_photos=body.include_photos)
    db.add(export)
    await db.flush()
    audit.record(db, actor_user_id=principal.user.id, action="export.requested", entity_type="data_export", entity_id=export.id, after={"include_photos": body.include_photos})
    await db.commit()
    tasks.add_task(data_export.run, principal.business_id, export.id)
    return out(export)


@router.get("/data-exports")
async def list_exports(principal: Principal = Depends(require("business.manage")), db: AsyncSession = Depends(get_db)):
    return [out(e) for e in (await db.execute(select(DataExport).order_by(DataExport.created_at.desc()).limit(20))).scalars()]


@router.get("/data-exports/{export_id}")
async def export_status(export_id: uuid.UUID, principal: Principal = Depends(require("business.manage")), db: AsyncSession = Depends(get_db)):
    e = (await db.execute(select(DataExport).where(DataExport.id == export_id))).scalar_one_or_none()
    if e is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That copy was not found.")
    return out(e)


@router.get("/data-exports/{export_id}/download")
async def download(export_id: uuid.UUID, principal: Principal = Depends(require("business.manage")), db: AsyncSession = Depends(get_db)):
    e = (await db.execute(select(DataExport).where(DataExport.id == export_id))).scalar_one_or_none()
    if e is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That copy was not found.")
    if e.status != "ready" or not e.storage_key:
        raise error(status.HTTP_409_CONFLICT, "not_ready", "That copy is not ready, or has expired. Ask for a new one.")
    path = storage.read_path(e.storage_key)
    if path is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That copy is no longer stored. Ask for a new one.")
    audit.record(db, actor_user_id=principal.user.id, action="export.downloaded", entity_type="data_export", entity_id=e.id)
    await db.commit()
    return FileResponse(path, media_type="application/zip", filename=f"fleettms-data-{e.created_at.date().isoformat()}.zip")
