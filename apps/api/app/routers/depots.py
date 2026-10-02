import uuid

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.db import get_db
from app.deps import Principal, error, require
from app.models import Depot

router = APIRouter(prefix="/depots", tags=["depots"])
FIELDS = ["name", "location"]


class DepotIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    location: str | None = Field(default=None, max_length=255)


def _out(d: Depot) -> dict:
    return {"id": d.id, "name": d.name, "location": d.location}


async def _get(db: AsyncSession, depot_id: uuid.UUID) -> Depot:
    d = (await db.execute(select(Depot).where(Depot.id == depot_id))).scalar_one_or_none()
    if d is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That depot was not found.")
    return d


@router.get("")
async def list_depots(_: Principal = Depends(require("depots.view")), db: AsyncSession = Depends(get_db)):
    return [_out(d) for d in (await db.execute(select(Depot).order_by(Depot.name))).scalars()]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_depot(
    body: DepotIn, principal: Principal = Depends(require("depots.manage")), db: AsyncSession = Depends(get_db)
):
    depot = Depot(name=body.name.strip(), location=body.location)
    db.add(depot)
    await db.flush()
    audit.record(
        db, actor_user_id=principal.user.id, action="depot.created", entity_type="depot",
        entity_id=depot.id, after=audit.snapshot(depot, FIELDS),
    )
    await db.commit()
    return _out(depot)


@router.put("/{depot_id}")
async def update_depot(
    depot_id: uuid.UUID,
    body: DepotIn,
    principal: Principal = Depends(require("depots.manage")),
    db: AsyncSession = Depends(get_db),
):
    depot = await _get(db, depot_id)
    before = audit.snapshot(depot, FIELDS)
    depot.name, depot.location = body.name.strip(), body.location
    audit.record(
        db, actor_user_id=principal.user.id, action="depot.updated", entity_type="depot",
        entity_id=depot.id, before=before, after=audit.snapshot(depot, FIELDS),
    )
    await db.commit()
    return _out(depot)


@router.delete("/{depot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_depot(
    depot_id: uuid.UUID, principal: Principal = Depends(require("depots.manage")), db: AsyncSession = Depends(get_db)
):
    depot = await _get(db, depot_id)
    audit.record(
        db, actor_user_id=principal.user.id, action="depot.deleted", entity_type="depot",
        entity_id=depot.id, before=audit.snapshot(depot, FIELDS),
    )
    await db.delete(depot)
    await db.commit()
