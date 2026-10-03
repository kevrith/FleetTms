"""Mapped areas (masterplan 5.12): depots, client sites, fuel stations and places lorries must not go, with entry and exit events."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.db import get_db
from app.deps import Principal, error, require
from app.models import Geofence, GeofenceEvent, Vehicle
from app.vehicle_scope import scope_vehicles

router = APIRouter(tags=["geofences"])


class CircleIn(BaseModel):
    type: Literal["circle"]
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    radius_m: float = Field(ge=20, le=100_000)


class PolygonIn(BaseModel):
    type: Literal["polygon"]
    points: list[tuple[float, float]] = Field(min_length=3, max_length=200)

    @model_validator(mode="after")
    def _on_the_globe(self):
        if any(not (-90 <= la <= 90 and -180 <= ln <= 180) for la, ln in self.points):
            raise ValueError("A corner of the area is off the map.")
        return self


class GeofenceIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    kind: Literal["depot", "client_site", "fuel_station", "restricted"] = "client_site"
    shape: CircleIn | PolygonIn = Field(discriminator="type")
    alert_on: list[Literal["enter", "exit"]] = Field(default_factory=list)
    vehicle_ids: list[uuid.UUID] | None = None  # only these vehicles; leave out for every vehicle
    is_active: bool = True


def geofence_out(g: Geofence) -> dict:
    return {"id": g.id, "name": g.name, "kind": g.kind, "shape": g.shape, "alert_on": g.alert_on, "vehicle_ids": g.vehicle_ids, "is_active": g.is_active}


async def _values(db: AsyncSession, body: GeofenceIn) -> dict:
    ids = [str(v) for v in body.vehicle_ids] if body.vehicle_ids is not None else None
    if ids:
        have = {str(v) for v in (await db.execute(select(Vehicle.id).where(Vehicle.id.in_(body.vehicle_ids)))).scalars()}
        if set(ids) - have:
            raise error(422, "unknown_vehicle", "One of those vehicles was not found.")
    shape = body.shape.model_dump()
    if shape["type"] == "polygon":
        shape["points"] = [list(p) for p in shape["points"]]
    return {"name": body.name.strip(), "kind": body.kind, "shape": shape, "alert_on": sorted(set(body.alert_on)), "vehicle_ids": ids, "is_active": body.is_active}


@router.get("/geofences")
async def list_geofences(principal: Principal = Depends(require("livemap.view")), db: AsyncSession = Depends(get_db)):
    return [geofence_out(g) for g in (await db.execute(select(Geofence).order_by(Geofence.name))).scalars()]


@router.post("/geofences", status_code=status.HTTP_201_CREATED)
async def add_geofence(body: GeofenceIn, principal: Principal = Depends(require("geofences.manage")), db: AsyncSession = Depends(get_db)):
    g = Geofence(**await _values(db, body))
    db.add(g)
    try:
        await db.flush()
    except IntegrityError:
        raise error(status.HTTP_409_CONFLICT, "duplicate_geofence", "An area with that name already exists.") from None
    audit.record(db, actor_user_id=principal.user.id, action="geofence.added", entity_type="geofence", entity_id=g.id, after={"name": g.name, "kind": g.kind, "alert_on": g.alert_on})
    await db.commit()
    return geofence_out(g)


@router.put("/geofences/{geofence_id}")
async def update_geofence(geofence_id: uuid.UUID, body: GeofenceIn, principal: Principal = Depends(require("geofences.manage")), db: AsyncSession = Depends(get_db)):
    g = (await db.execute(select(Geofence).where(Geofence.id == geofence_id))).scalar_one_or_none()
    if g is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That area was not found.")
    before = {"name": g.name, "kind": g.kind, "alert_on": g.alert_on, "is_active": g.is_active}
    for k, v in (await _values(db, body)).items():
        setattr(g, k, v)
    try:
        await db.flush()
    except IntegrityError:
        raise error(status.HTTP_409_CONFLICT, "duplicate_geofence", "An area with that name already exists.") from None
    audit.record(db, actor_user_id=principal.user.id, action="geofence.updated", entity_type="geofence", entity_id=g.id, before=before, after={"name": g.name, "kind": g.kind, "alert_on": g.alert_on, "is_active": g.is_active})
    await db.commit()
    return geofence_out(g)


@router.delete("/geofences/{geofence_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_geofence(geofence_id: uuid.UUID, principal: Principal = Depends(require("geofences.manage")), db: AsyncSession = Depends(get_db)):
    g = (await db.execute(select(Geofence).where(Geofence.id == geofence_id))).scalar_one_or_none()
    if g is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That area was not found.")
    audit.record(db, actor_user_id=principal.user.id, action="geofence.deleted", entity_type="geofence", entity_id=g.id, before={"name": g.name})
    await db.delete(g)
    await db.commit()


@router.get("/geofences/events")
async def geofence_events(vehicle_id: uuid.UUID | None = None, geofence_id: uuid.UUID | None = None, limit: int = 100, principal: Principal = Depends(require("livemap.view")), db: AsyncSession = Depends(get_db)):
    """Entries and exits, newest first, for the vehicles the caller may see."""
    names = {v.id: v.registration for v in (await db.execute(scope_vehicles(select(Vehicle), principal))).scalars()}
    fences = {g.id: g.name for g in (await db.execute(select(Geofence))).scalars()}
    query = select(GeofenceEvent).order_by(GeofenceEvent.at.desc()).limit(min(max(limit, 1), 500))
    if vehicle_id:
        query = query.where(GeofenceEvent.vehicle_id == vehicle_id)
    if geofence_id:
        query = query.where(GeofenceEvent.geofence_id == geofence_id)
    return [
        {"id": e.id, "geofence": fences.get(e.geofence_id), "geofence_id": e.geofence_id, "vehicle_id": e.vehicle_id, "registration": names[e.vehicle_id], "trip_id": e.trip_id, "kind": e.kind, "at": e.at, "lat": e.lat, "lng": e.lng}
        for e in (await db.execute(query)).scalars() if e.vehicle_id in names
    ]  # fmt: skip
