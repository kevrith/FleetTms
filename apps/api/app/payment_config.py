"""The business's payment settings row (made on first use)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PaymentSettings


async def get_settings(db: AsyncSession) -> PaymentSettings:
    row = (await db.execute(select(PaymentSettings))).scalar_one_or_none()
    if row is None:
        row = PaymentSettings()
        db.add(row)
        await db.flush()
    return row
