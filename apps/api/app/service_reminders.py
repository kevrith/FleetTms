"""Service reminders (masterplan 5.8): "Service due in 500 km", sent once per due service, with a work order raised."""

import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_sessionmaker
from app.models import (
    Business,
    Membership,
    MembershipStatus,
    Priority,
    Role,
    ServiceReminder,
    ServiceSchedule,
    Vehicle,
    WorkOrder,
    WorkOrderSource,
    WorkOrderStatus,
)
from app.reminders import NAIROBI, nairobi_today
from app.service_rules import service_due
from app.sms import get_sms_sender
from app.tenancy import current_business_id

log = logging.getLogger(__name__)
OPEN = (WorkOrderStatus.OPEN, WorkOrderStatus.IN_PROGRESS, WorkOrderStatus.WAITING_PARTS)


def describe(name: str, registration: str, km_left: int | None, days_left: int | None, status: str) -> str:
    if status == "overdue":
        what = "is overdue"
    elif km_left is not None and km_left <= 0 or km_left is not None and (days_left is None or km_left / 1000 < max(days_left, 1)):
        what = f"is due in {km_left:,} km"
    else:
        what = f"is due in {days_left} day{'s' if days_left != 1 else ''}"
    return f"FleetTms: {name} for {registration} {what}."


async def _for_business(db: AsyncSession, today: date) -> int:
    managers = [
        m for m in (await db.execute(select(Membership))).scalars()
        if m.status == MembershipStatus.ACTIVE and m.user.phone and {r.role for r in m.roles} & {Role.OWNER, Role.MANAGER}
    ]  # fmt: skip
    vehicles = {v.id: v for v in (await db.execute(select(Vehicle))).scalars()}
    sent = {(r.schedule_id, r.due_key) for r in (await db.execute(select(ServiceReminder))).scalars()}
    sms, count = get_sms_sender(), 0
    for schedule in (await db.execute(select(ServiceSchedule).where(ServiceSchedule.is_active.is_(True)))).scalars().all():
        vehicle = vehicles.get(schedule.vehicle_id)
        if vehicle is None:
            continue
        due = service_due(
            every_km=schedule.every_km, every_months=schedule.every_months, last_done_km=schedule.last_done_km,
            last_done_on=schedule.last_done_on, advance_km=schedule.advance_km, advance_days=schedule.advance_days,
            odometer_km=vehicle.odometer_km, today=today, started_on=schedule.created_at.astimezone(NAIROBI).date(),
        )  # fmt: skip
        if due.status == "ok" or (schedule.id, due.key) in sent:
            continue
        open_wo = (
            await db.execute(
                select(WorkOrder.id).where(WorkOrder.schedule_id == schedule.id, WorkOrder.status.in_(OPEN)).limit(1)
            )
        ).first()
        if open_wo is None:
            db.add(
                WorkOrder(
                    vehicle_id=vehicle.id, source=WorkOrderSource.SERVICE, schedule_id=schedule.id,
                    title=f"{schedule.name}: service due for {vehicle.registration}",
                    priority=Priority.URGENT if due.status == "overdue" else Priority.HIGH,
                )
            )  # fmt: skip
        message = describe(schedule.name, vehicle.registration, due.km_left, due.days_left, due.status)
        for phone in sorted({m.user.phone for m in managers}):
            await sms.send(phone, message)
            count += 1
        db.add(ServiceReminder(schedule_id=schedule.id, due_key=due.key))
    await db.commit()
    return count


async def send_service_reminders(today: date | None = None) -> int:
    """Runs across every business. `today` is injectable so tests can use fake dates."""
    today = today or nairobi_today()
    total = 0
    async with get_sessionmaker()() as db:
        business_ids = (await db.execute(select(Business.id))).scalars().all()
    for business_id in business_ids:
        async with get_sessionmaker()() as db:
            current_business_id.set(business_id)
            try:
                total += await _for_business(db, today)
            finally:
                current_business_id.set(None)
    log.info("Sent %s service reminder messages", total)
    return total


async def service_reminders_job(ctx: dict) -> int:
    return await send_service_reminders()
