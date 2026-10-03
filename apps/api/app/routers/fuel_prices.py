"""Pump prices and route suggestions for quotes (masterplan 5.12, 5.28)."""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, fuel_prices, routing
from app.db import get_db
from app.deps import Principal, error, require, require_any
from app.models import Business, FuelPrice, FuelType
from app.tenancy import current_business_id

router = APIRouter(tags=["planning"])


class PriceIn(BaseModel):
    month: date
    region: str
    diesel_cents: int = Field(gt=0, le=100_000)  # per litre
    petrol_cents: int = Field(gt=0, le=100_000)


class RegionIn(BaseModel):
    region: str


class SuggestIn(BaseModel):
    origin: str = Field(min_length=2, max_length=160)
    destination: str = Field(min_length=2, max_length=160)


def price_out(p: FuelPrice) -> dict:
    return {"id": p.id, "month": p.month, "region": p.region, "diesel_cents": p.diesel_cents, "petrol_cents": p.petrol_cents, "source": p.source}


@router.get("/fuel-prices")
async def list_prices(principal: Principal = Depends(require_any("clients.manage", "finance.view", "vehicles.view")), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(FuelPrice).order_by(FuelPrice.month.desc(), FuelPrice.region).limit(120))).scalars().all()
    region = await fuel_prices.region_of(db)
    return {"region": region, "regions": fuel_prices.REGIONS, "current": await fuel_prices.current(db, FuelType.DIESEL), "current_petrol": await fuel_prices.current(db, FuelType.PETROL), "prices": [price_out(p) for p in rows]}


@router.put("/fuel-prices")
async def save_price(body: PriceIn, principal: Principal = Depends(require("clients.manage")), db: AsyncSession = Depends(get_db)):
    """Types in one month's price for one town. A month already there is replaced."""
    if body.region not in fuel_prices.REGIONS:
        raise error(422, "unknown_region", f"Choose one of: {', '.join(fuel_prices.REGIONS)}.")
    await fuel_prices.save_prices(db, body.month, [body.model_dump(include={"region", "diesel_cents", "petrol_cents"})], "manual")
    audit.record(db, actor_user_id=principal.user.id, action="fuel_price.saved", entity_type="fuel_price", entity_id=uuid.uuid4(), after=body.model_dump(mode="json"))
    await db.commit()
    return {"current": await fuel_prices.current(db, FuelType.DIESEL)}


@router.put("/fuel-prices/region")
async def set_region(body: RegionIn, principal: Principal = Depends(require("clients.manage")), db: AsyncSession = Depends(get_db)):
    """Which town's price quotes start from."""
    if body.region not in fuel_prices.REGIONS:
        raise error(422, "unknown_region", f"Choose one of: {', '.join(fuel_prices.REGIONS)}.")
    business = (await db.execute(select(Business).where(Business.id == current_business_id.get()))).scalar_one()
    business.fuel_region = body.region
    audit.record(db, actor_user_id=principal.user.id, action="fuel_region.changed", entity_type="business", entity_id=business.id, after={"region": body.region})
    await db.commit()
    return {"region": body.region, "current": await fuel_prices.current(db, FuelType.DIESEL)}


@router.post("/fuel-prices/fetch")
async def fetch(principal: Principal = Depends(require("clients.manage")), db: AsyncSession = Depends(get_db)):
    """Reads this month's prices from the feed set in EPRA_PRICES_URL."""
    try:
        saved = await fuel_prices.fetch_prices(db)
    except fuel_prices.FeedError as e:
        raise error(status.HTTP_502_BAD_GATEWAY, "feed_failed", str(e)) from None
    await db.commit()
    return {"saved": saved, "current": await fuel_prices.current(db, FuelType.DIESEL)}


@router.post("/routes/suggest")
async def suggest_route(body: SuggestIn, principal: Principal = Depends(require("clients.manage"))):
    """How far and how long between two places, to fill in a saved route."""
    try:
        return await routing.get_routes().suggest(body.origin, body.destination)
    except routing.RouteError as e:
        raise error(422, "no_route", str(e)) from None
