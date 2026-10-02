from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import Principal, require
from app.models import AuditLog

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("")
async def list_audit(
    action: str | None = None,
    entity_type: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: Principal = Depends(require("audit.view")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    return [
        {
            "id": a.id,
            "actor_user_id": a.actor_user_id,
            "action": a.action,
            "entity_type": a.entity_type,
            "entity_id": a.entity_id,
            "before": a.before,
            "after": a.after,
            "note": a.note,
            "created_at": a.created_at,
        }
        for a in (await db.execute(stmt)).scalars()
    ]
