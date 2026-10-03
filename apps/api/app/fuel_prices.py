"""EPRA's monthly pump prices (masterplan 5.28). Typed in by the business (the dependable way: EPRA publishes a PDF, not an API) or
fetched from a JSON feed set in EPRA_PRICES_URL. Quotes start from the newest price for the business's town."""

import logging
from datetime import date, datetime
from typing import Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Business, FuelPrice, FuelType
from app.reminders import NAIROBI
from app.tenancy import current_business_id

log = logging.getLogger(__name__)
REGIONS = ["Nairobi", "Mombasa", "Kisumu", "Nakuru", "Eldoret"]


class FeedError(Exception):
    """The price feed could not be read. The text is safe to show."""


class PriceFeed(Protocol):
    async def fetch(self) -> tuple[date, list[dict]]: ...


class FakeFeed:
    """What tests and development use when no feed is set: the prices it is given."""

    def __init__(self) -> None:
        self.result: tuple[date, list[dict]] | None = None
        self.fail_with: str | None = None

    async def fetch(self) -> tuple[date, list[dict]]:
        if self.fail_with:
            raise FeedError(self.fail_with)
        if self.result is None:
            raise FeedError("No price feed is set up.")
        return self.result


class HttpFeed:
    async def fetch(self) -> tuple[date, list[dict]]:
        try:
            async with httpx.AsyncClient(timeout=20) as http:
                res = await http.get(settings.epra_prices_url)
                res.raise_for_status()
                data = res.json()
            month = date.fromisoformat(data["month"]).replace(day=1)
            rows = [{"region": p["region"], "diesel_cents": round(float(p["diesel"]) * 100), "petrol_cents": round(float(p["petrol"]) * 100)} for p in data["prices"]]
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
            raise FeedError(f"The price feed could not be read: {type(e).__name__}") from e
        return month, rows


_fake = FakeFeed()


def get_feed() -> PriceFeed:
    return HttpFeed() if settings.epra_prices_url else _fake


def fake_feed() -> FakeFeed:
    return _fake


def this_month() -> date:
    return datetime.now(NAIROBI).date().replace(day=1)


async def region_of(db: AsyncSession) -> str:
    return (await db.execute(select(Business.fuel_region).where(Business.id == current_business_id.get()))).scalar_one_or_none() or "Nairobi"


async def current(db: AsyncSession, fuel: FuelType = FuelType.DIESEL, region: str | None = None) -> dict | None:
    """The newest price (not for a month still to come) for a town and a fuel: {cents, month, region, source} or None."""
    region = region or await region_of(db)
    row = (await db.execute(select(FuelPrice).where(FuelPrice.region == region, FuelPrice.month <= this_month()).order_by(FuelPrice.month.desc()).limit(1))).scalars().first()
    if row is None:
        return None
    return {"cents": row.diesel_cents if fuel == FuelType.DIESEL else row.petrol_cents, "month": row.month, "region": row.region, "source": row.source}


async def save_prices(db: AsyncSession, month: date, rows: list[dict], source: str) -> int:
    """Stores a month's prices, replacing what was there for the same town and month. Returns how many towns were saved."""
    month = month.replace(day=1)
    saved = 0
    for r in rows:
        if r["region"] not in REGIONS:
            continue
        existing = (await db.execute(select(FuelPrice).where(FuelPrice.month == month, FuelPrice.region == r["region"]))).scalars().first()
        if existing is None:
            db.add(FuelPrice(month=month, region=r["region"], diesel_cents=r["diesel_cents"], petrol_cents=r["petrol_cents"], source=source))
        else:
            existing.diesel_cents, existing.petrol_cents, existing.source = r["diesel_cents"], r["petrol_cents"], source
        saved += 1
    return saved


async def fetch_prices(db: AsyncSession, *, only_if_missing: bool = False) -> int:
    """Reads the feed and stores it. With only_if_missing (the daily job) nothing is fetched when this month already has prices."""
    month = this_month()
    if only_if_missing and (await db.execute(select(FuelPrice.id).where(FuelPrice.month == month).limit(1))).first() is not None:
        return 0
    got_month, rows = await get_feed().fetch()
    return await save_prices(db, got_month, rows, "epra")
