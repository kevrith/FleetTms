"""Supervisors only see their assigned vehicles (masterplan Section 3). Everyone else sees all."""

import uuid

from fastapi import status
from sqlalchemy import Select

from app.deps import Principal, error
from app.models import Vehicle


def vehicle_in_scope(principal: Principal, vehicle_id: uuid.UUID) -> bool:
    return principal.vehicle_scope is None or str(vehicle_id) in principal.vehicle_scope


def scope_vehicles(query: Select, principal: Principal) -> Select:
    """Narrow a Vehicle query to what the principal may see."""
    if principal.vehicle_scope is None:
        return query
    ids = []
    for v in principal.vehicle_scope:
        try:
            ids.append(uuid.UUID(v))
        except ValueError:
            continue  # a malformed entry grants nothing
    return query.where(Vehicle.id.in_(ids))


def require_vehicle_in_scope(principal: Principal, vehicle_id: uuid.UUID) -> None:
    # 404 rather than 403, so a supervisor cannot probe for vehicles outside their scope.
    if not vehicle_in_scope(principal, vehicle_id):
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That vehicle was not found.")
