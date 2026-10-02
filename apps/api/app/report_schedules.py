"""Scheduled reports (masterplan 5.15): the finished period is sent as a PDF, once, by email or WhatsApp."""

import logging
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_sessionmaker
from app.models import Business, ReportFrequency, ReportSchedule
from app.reminders import nairobi_today
from app.report_delivery import DeliveryError, get_report_sender
from app.report_files import report_pdf
from app.routers.dashboard import build_summary
from app.tenancy import current_business_id

log = logging.getLogger(__name__)


def last_finished_period(frequency: ReportFrequency, today: date) -> tuple[date, date]:
    """Yesterday; last week Monday to Sunday; or last calendar month."""
    if frequency == ReportFrequency.DAILY:
        day = today - timedelta(days=1)
        return day, day
    if frequency == ReportFrequency.WEEKLY:
        monday = today - timedelta(days=today.weekday())
        return monday - timedelta(days=7), monday - timedelta(days=1)
    end = today.replace(day=1) - timedelta(days=1)
    return end.replace(day=1), end


async def send_schedule(db: AsyncSession, schedule: ReportSchedule, period: tuple[date, date]) -> None:
    """Builds and sends one report. Raises DeliveryError; the caller records the outcome."""
    start, end = period
    pdf = report_pdf(await build_summary(db, start, end))
    name = f"fleettms-report-{start.isoformat()}-to-{end.isoformat()}.pdf"
    await get_report_sender(schedule.channel.value).send(schedule.recipient, f"FleetTms report {start.isoformat()} to {end.isoformat()}", name, pdf)


async def _for_business(db: AsyncSession, today: date) -> int:
    sent = 0
    for schedule in (await db.execute(select(ReportSchedule).where(ReportSchedule.is_active.is_(True)))).scalars().all():
        period = last_finished_period(schedule.frequency, today)
        if schedule.last_period_end is not None and schedule.last_period_end >= period[1]:
            continue  # this period was already sent
        try:
            await send_schedule(db, schedule, period)
        except DeliveryError as e:
            schedule.last_error = str(e)[:255]  # tried again at the next run
        else:
            schedule.last_period_end, schedule.last_error = period[1], None
            sent += 1
    await db.commit()
    return sent


async def send_scheduled_reports(today: date | None = None) -> int:
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
    log.info("Sent %s scheduled reports", total)
    return total


async def scheduled_reports_job(ctx: dict) -> int:
    return await send_scheduled_reports()
