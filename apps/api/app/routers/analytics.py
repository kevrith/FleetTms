"""Product analytics for the platform admin: which parts of the product are used, and where new businesses get stuck (see analytics.py)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app import analytics
from app.db import get_db
from app.deps import Principal, platform_admin

router = APIRouter(tags=["platform"])


@router.get("/platform/analytics/usage")
async def usage(days: int = Query(30, ge=1, le=365), principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    return await analytics.usage(db, days)


@router.get("/platform/analytics/funnel")
async def funnel(weeks: int = Query(12, ge=1, le=52), principal: Principal = Depends(platform_admin), db: AsyncSession = Depends(get_db)):
    return await analytics.funnel(db, weeks)
