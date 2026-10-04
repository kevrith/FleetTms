"""Recurring work: a schedule puts each coming day's job (or contract trip) in the diary ahead of time, once, and tells the managers when it
could not give it a lorry. Run every morning by the worker, or on request from the schedule's screen."""

import logging
import uuid
from datetime import date, timedelta
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, recurrence_rules
from app.db import get_sessionmaker
from app.models import (
    BillingMethod,
    Business,
    Client,
    Job,
    JobSchedule,
    JobScheduleRun,
    JobStatus,
    Membership,
    MembershipStatus,
    Role,
    SavedRoute,
    Trip,
    TripStatus,
)
from app.numbering import create_numbered
from app.reminders import nairobi_today
from app.sms import get_sms_sender
from app.tenancy import current_business_id

log = logging.getLogger(__name__)


def _detail(e: HTTPException) -> str:
    d = e.detail
    return (d.get("message") if isinstance(d, dict) else str(d))[:255]


async def has_active_schedule(db: AsyncSession, job_id: uuid.UUID) -> bool:
    return (await db.execute(select(JobSchedule.id).where(JobSchedule.template_job_id == job_id, JobSchedule.is_active.is_(True)).limit(1))).first() is not None


def upcoming(schedule: JobSchedule, *, today: date | None = None, days: int = 60, limit: int = 8) -> list[date]:
    today = today or nairobi_today()
    return recurrence_rules.due_dates(
        schedule.cadence, weekdays=schedule.weekdays or [], day_of_month=schedule.day_of_month, starts_on=schedule.starts_on, ends_on=schedule.ends_on,
        first=today, last=today + timedelta(days=days),
    )[:limit]  # fmt: skip


async def _tell_managers(db: AsyncSession, text: str) -> None:
    for m in (await db.execute(select(Membership).where(Membership.status == MembershipStatus.ACTIVE))).scalars():
        if {r.role for r in m.roles} & {Role.OWNER, Role.MANAGER} and m.user.phone:
            try:
                await get_sms_sender().send(m.user.phone, f"FleetTms: {text}")
            except Exception:  # noqa: BLE001 - a text that fails must not undo the diary entry
                log.warning("A recurring-work notice could not be sent")


async def _dispatch(db: AsyncSession, schedule: JobSchedule, job: Job, when) -> tuple[Trip | None, str | None]:
    """Sends the schedule's lorry out on `job` at `when`. Returns the trip, or why it could not be done."""
    from app.routers.trips import TripIn, do_create_trip

    route = (await db.execute(select(SavedRoute).where(SavedRoute.id == job.route_id))).scalar_one_or_none() if job.route_id else None
    acting = SimpleNamespace(user=SimpleNamespace(id=schedule.created_by_user_id), vehicle_scope=None, business_id=current_business_id.get())
    try:
        async with db.begin_nested():
            trip = await do_create_trip(
                db, acting, TripIn(vehicle_id=schedule.vehicle_id, cargo_description=job.cargo_description, origin=route.pickup if route else None, destination=route.dropoff if route else None, scheduled_for=when),
                job_id=job.id, hours=route.expected_hours if route else None,
            )  # fmt: skip
        return trip, None
    except HTTPException as e:
        return None, _detail(e)


async def materialise(db: AsyncSession, schedule: JobSchedule, today: date | None = None) -> list[JobScheduleRun]:
    """Puts every day that has come into the lead window and is not in the diary yet in the diary. Safe to repeat."""
    today = today or nairobi_today()
    template = (await db.execute(select(Job).where(Job.id == schedule.template_job_id))).scalar_one_or_none()
    if not schedule.is_active or template is None or template.status == JobStatus.CANCELLED:
        return []
    days = recurrence_rules.due_dates(
        schedule.cadence, weekdays=schedule.weekdays or [], day_of_month=schedule.day_of_month, starts_on=schedule.starts_on, ends_on=schedule.ends_on,
        first=today, last=today + timedelta(days=schedule.lead_days),
    )  # fmt: skip
    done = {r for r in (await db.execute(select(JobScheduleRun.occurrence_on).where(JobScheduleRun.schedule_id == schedule.id))).scalars()}
    client = (await db.execute(select(Client).where(Client.id == template.client_id))).scalar_one()
    made: list[JobScheduleRun] = []
    for day in days:
        if day in done:
            continue
        when = recurrence_rules.pickup_at(day, schedule.pickup_time)
        deliver_by = when + timedelta(hours=schedule.deliver_within_hours)
        note = None
        trip = None
        if template.billing_method == BillingMethod.MONTHLY_CONTRACT:
            job = template  # the contract bills itself every month; each day's work is a trip under it
            live = (await db.execute(select(Trip.id).where(Trip.job_id == job.id, Trip.status != TripStatus.CANCELLED))).all()
            job.trips_planned = max(job.trips_planned, len(live) + 1)
            if job.status == JobStatus.COMPLETED:
                job.status, job.completed_at = JobStatus.DISPATCHED, None
        else:
            job = await create_numbered(
                db, Job, "J", client_id=template.client_id, route_id=template.route_id, repeat_of_id=template.id, cargo_description=template.cargo_description,
                weight_tonnes=template.weight_tonnes, trips_planned=template.trips_planned, billing_method=template.billing_method, rate_cents=template.rate_cents,
                price_cents=template.price_cents, expected_profit_cents=template.expected_profit_cents, pickup_at=when, deliver_by=deliver_by,
                instructions=template.instructions, created_by_user_id=schedule.created_by_user_id,
            )  # fmt: skip
            audit.record(db, actor_user_id=None, action="job.scheduled", entity_type="job", entity_id=job.id, after={"number": job.number, "for": day.isoformat()}, note=f"Made by the recurring schedule of {template.number}")
        if schedule.vehicle_id is not None:
            trip, note = await _dispatch(db, schedule, job, when)
        elif template.billing_method == BillingMethod.MONTHLY_CONTRACT:
            note = "No lorry is set on this schedule."
        run = JobScheduleRun(schedule_id=schedule.id, occurrence_on=day, job_id=job.id, trip_id=trip.id if trip else None, note=note)
        db.add(run)
        await db.flush()
        made.append(run)
        if note:
            await _tell_managers(db, f"{client.name}, {job.number}, for {day.strftime('%a %d %b')} is in the diary but has no lorry: {note}")
    return made


async def run_all(today: date | None = None) -> int:
    """Every business's active schedules (the worker's job, early each morning). Returns how many days were put in the diary."""
    async with get_sessionmaker()() as db:
        ids = (await db.execute(select(Business.id))).scalars().all()
    total = 0
    for business_id in ids:
        async with get_sessionmaker()() as db:
            current_business_id.set(business_id)
            try:
                for schedule in (await db.execute(select(JobSchedule).where(JobSchedule.is_active.is_(True)))).scalars().all():
                    try:
                        total += len(await materialise(db, schedule, today))
                        await db.commit()
                    except Exception:
                        await db.rollback()
                        log.exception("A recurring schedule could not be run")
            finally:
                current_business_id.set(None)
    log.info("Recurring work: %s days put in the diary", total)
    return total


async def recurring_jobs_job(ctx: dict) -> int:
    return await run_all()
