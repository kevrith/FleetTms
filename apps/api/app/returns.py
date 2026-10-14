"""The lorry coming home after a delivery. The depot is a mapped area of kind depot (Settings, Mapped areas); a trip that has delivered
and then ends away from every depot is noted, and the driver may say why. Nothing here ever stops a trip from ending."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.geofence_rules import inside
from app.models import Geofence


async def depots_for(db: AsyncSession, vehicle_id: uuid.UUID) -> list[Geofence]:
    """The active depot areas that apply to this vehicle (an area with no vehicles listed applies to all)."""
    rows = (await db.execute(select(Geofence).where(Geofence.kind == "depot", Geofence.is_active.is_(True)))).scalars().all()
    return [g for g in rows if not g.vehicle_ids or str(vehicle_id) in g.vehicle_ids]


def at_a_depot(depots: list[Geofence], lat: float, lng: float) -> bool:
    return any(inside(g.shape, lat, lng) for g in depots)
