"""Vehicle trust level (masterplan 5.3): how far the data from a vehicle can be believed.

It starts from how the vehicle is tracked and drops when phones used on it have been flagged for a mock-location
app, root access or a changed clock in the last 30 days. Flags lower the level; they never block anyone.
"""

import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DeviceCheck, TrackingTier, Vehicle

WINDOW = timedelta(days=30)
BASE = {TrackingTier.BASIC: 1, TrackingTier.STANDARD: 2, TrackingTier.PREMIUM: 3}


def level_for(tier: TrackingTier, flag_kinds: int) -> tuple[str, int]:
    score = max(0, BASE[tier] - min(flag_kinds, 2))
    return ("high" if score >= 3 else "medium" if score == 2 else "low"), score


async def flag_summary(db: AsyncSession, vehicle_ids: list[uuid.UUID] | None = None) -> dict[uuid.UUID, dict[str, dict]]:
    """Per vehicle, each flag seen in the last 30 days with how often and when last."""
    query = select(DeviceCheck).where(DeviceCheck.reported_at >= datetime.now(UTC) - WINDOW, DeviceCheck.vehicle_id.is_not(None))
    if vehicle_ids is not None:
        query = query.where(DeviceCheck.vehicle_id.in_(vehicle_ids))
    out: dict[uuid.UUID, dict[str, dict]] = defaultdict(dict)
    for check in (await db.execute(query)).scalars():
        for flag in check.flags:
            seen = out[check.vehicle_id].setdefault(flag, {"flag": flag, "count": 0, "last_at": check.reported_at})
            seen["count"] += 1
            seen["last_at"] = max(seen["last_at"], check.reported_at)
    return out


def trust_out(vehicle: Vehicle, flags: dict[str, dict]) -> dict:
    level, score = level_for(vehicle.tracking_tier, len(flags))
    return {"level": level, "score": score, "tier": vehicle.tracking_tier.value, "flags": sorted(flags.values(), key=lambda f: f["flag"])}
