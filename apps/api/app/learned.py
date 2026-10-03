"""Learned fuel models (masterplan 5.13): training one for a vehicle from its finished trips, and keeping what was learned so the owner
can see it. The maths is in app/learned_rules.py."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import fraud, learned_rules
from app.fraud_rules import Thresholds
from app.models import Trip, TripStatus, Vehicle, VehicleModel

WINDOW = 120  # the most recent trips a model is trained on


def sample_of(trip: Trip, litres: float, idle_hours: float) -> dict | None:
    km = fraud.best_km(trip)
    if not km or km <= 0 or litres <= 0:
        return None
    tonnes = (trip.loaded_weight_kg or 0) / 1000
    return {"km": km, "tonne_km": tonnes * km, "idle_hours": idle_hours, "litres": litres}


async def train(db: AsyncSession, vehicle: Vehicle, t: Thresholds, *, exclude_trip: uuid.UUID | None = None, save: bool = True) -> dict | None:
    """Learns from the vehicle's finished trips that have fuel recorded (leaving one trip out when it is the one being judged).
    Returns the model, or None when there are too few trips. The result is kept for the owner to look at."""
    trips = (await db.execute(select(Trip).where(Trip.vehicle_id == vehicle.id, Trip.status.in_((TripStatus.DELIVERED, TripStatus.COMPLETED)), Trip.distance_km.is_not(None)).order_by(Trip.ended_at.desc()).limit(WINDOW))).scalars().all()
    trips = [x for x in trips if x.id != exclude_trip]
    fuel, idle = await fraud._fuel_by_trip(db, trips), await fraud._idle_hours(db, [x.id for x in trips])
    samples = [s for x in trips if fuel.get(x.id) and (s := sample_of(x, fuel[x.id], idle[x.id]))]
    model = learned_rules.fit(samples, t.model_min_trips)
    if model is not None and save:
        row = (await db.execute(select(VehicleModel).where(VehicleModel.vehicle_id == vehicle.id, VehicleModel.kind == "fuel"))).scalars().first()
        if row is None:
            row = VehicleModel(vehicle_id=vehicle.id, kind="fuel", trips=0, r2=0, sigma_litres=0)
            db.add(row)
        row.trips, row.r2, row.sigma_litres, row.reliable = model["n"], model["r2"], model["sigma"], model["reliable"]
        row.params, row.trained_at = {"coefs": model["coefs"], "mean_idle_hours": model["mean_idle_hours"]}, datetime.now(UTC)
    return model
