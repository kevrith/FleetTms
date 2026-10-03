"""Predictions and learned models (masterplan 5.14), each with its working shown."""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import fraud, learned, predictions
from app.db import get_db
from app.deps import Principal, error, require
from app.models import Vehicle
from app.reminders import NAIROBI
from app.vehicle_scope import scope_vehicles

router = APIRouter(tags=["predictions"])


async def _vehicle(db: AsyncSession, principal: Principal, vehicle_id: uuid.UUID) -> Vehicle:
    v = (await db.execute(scope_vehicles(select(Vehicle), principal).where(Vehicle.id == vehicle_id))).scalar_one_or_none()
    if v is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That vehicle was not found.")
    return v


@router.get("/predictions/fuel")
async def expected_fuel(
    vehicle_id: uuid.UUID, distance_km: float, weight_tonnes: float = 0, origin: str | None = None, destination: str | None = None, return_empty: bool = True,
    principal: Principal = Depends(require("vehicles.view")), db: AsyncSession = Depends(get_db),
):  # fmt: skip
    """Fuel a planned trip should take, and how that was worked out."""
    if not 0 < distance_km <= 20_000 or not 0 <= weight_tonnes <= 1000:
        raise error(422, "bad_trip", "Give a distance up to 20,000 km and a weight up to 1,000 tonnes.")
    vehicle = await _vehicle(db, principal, vehicle_id)
    t, _ = await fraud.load_settings(db)
    known = await predictions.consumption(db, vehicle, distance_km=distance_km, weight_kg=weight_tonnes * 1000, origin=origin, destination=destination, t=t)
    if known is None:
        kmpl_loaded, kmpl_empty = vehicle.expected_kmpl_loaded, vehicle.expected_kmpl_empty
        if not kmpl_loaded and not kmpl_empty:
            return {"vehicle_id": vehicle.id, "registration": vehicle.registration, "source": None, "litres": None, "steps": ["Nothing is known about this vehicle's fuel use yet: enter its consumption or record fuel on a few trips."]}
        kmpl_loaded, kmpl_empty = float(kmpl_loaded or kmpl_empty), float(kmpl_empty or kmpl_loaded)
        known = {"kmpl_loaded": kmpl_loaded, "kmpl_empty": kmpl_empty, "source": "declared", "steps": [f"The consumption entered for the vehicle: {kmpl_loaded:g} km a litre loaded and {kmpl_empty:g} empty. Its own trip history is not enough to use yet."]}
    loaded = distance_km / (known["kmpl_loaded"] or known["kmpl_empty"])
    back = distance_km / (known["kmpl_empty"] or known["kmpl_loaded"]) if return_empty else 0
    steps = [*known["steps"], f"Fuel for the trip: {loaded:.0f} litres out{f' and {back:.0f} back, {loaded + back:.0f} in all' if return_empty else ''}."]
    return {"vehicle_id": vehicle.id, "registration": vehicle.registration, "source": known["source"], "litres_loaded": round(loaded), "litres_return": round(back), "litres": round(loaded + back), "steps": steps}


@router.get("/predictions/forecast")
async def month_forecast(principal: Principal = Depends(require("finance.view")), db: AsyncSession = Depends(get_db)):
    """How this month is likely to end, for the business and each vehicle, with the working."""
    from datetime import datetime

    today: date = datetime.now(NAIROBI).date()
    return await predictions.forecast(db, today)


@router.get("/vehicles/{vehicle_id}/model")
async def vehicle_model(vehicle_id: uuid.UUID, principal: Principal = Depends(require("vehicles.view")), db: AsyncSession = Depends(get_db)):
    """What has been learned about this vehicle's fuel use from its own trips, and whether it is reliable enough to be used."""
    vehicle = await _vehicle(db, principal, vehicle_id)
    t, _ = await fraud.load_settings(db)
    model = await learned.train(db, vehicle, t)
    await db.commit()
    if model is None:
        return {"vehicle_id": vehicle.id, "registration": vehicle.registration, "trained": False, "needed_trips": 6, "message": "Fewer than 6 finished trips with fuel recorded: nothing can be learned yet."}
    c = model["coefs"]
    return {
        "vehicle_id": vehicle.id, "registration": vehicle.registration, "trained": True, "trips": model["n"], "r2": model["r2"], "sigma_litres": model["sigma"], "reliable": model["reliable"], "needed_trips": t.model_min_trips,
        "litres_per_km": c["km"], "litres_per_tonne_km": c["tonne_km"], "litres_per_idle_hour": c["idle_hours"], "usual_idle_hours": model["mean_idle_hours"],
        "message": ("Used alongside the rules: a trip well above what it expects raises an alert." if model["reliable"]
                    else f"Not used yet: it needs at least {t.model_min_trips} trips and has to explain at least 60% of how fuel varies (it explains {round(model['r2'] * 100)}%)."),
    }  # fmt: skip
