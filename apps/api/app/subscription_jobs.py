"""Daily subscription reminders (masterplan Section 9), across every business."""

from sqlalchemy.ext.asyncio import AsyncSession

from app import subscriptions
from app.tracking_jobs import _each_business


async def run_notices() -> int:
    async def one(db: AsyncSession) -> int:
        sent = await subscriptions.send_notices(db)
        await db.commit()
        return sent

    return await _each_business(one)


async def subscription_notices_job(ctx: dict) -> int:
    return await run_notices()
