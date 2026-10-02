"""Document numbers per business: Q-0001, J-0001. Two requests at once can pick the same number; the unique constraint
catches that and the loser tries the next one."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


async def create_numbered(db: AsyncSession, model: Any, prefix: str, **fields: Any) -> Any:
    for _ in range(5):
        highest = 0
        for number in (await db.execute(select(model.number))).scalars():
            head, _, tail = number.partition("-")
            if head == prefix and tail.isdigit():
                highest = max(highest, int(tail))
        row = model(number=f"{prefix}-{highest + 1:04d}", **fields)
        try:
            async with db.begin_nested():
                db.add(row)
                await db.flush()
        except IntegrityError:
            continue
        return row
    raise RuntimeError("Could not allocate a document number")
