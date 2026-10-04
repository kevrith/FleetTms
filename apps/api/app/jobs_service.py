"""Keeps a job's status in step with its trips."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Job, JobStatus, Trip, TripStatus
from app.models import utcnow as now


async def sync_job(db: AsyncSession, job_id: uuid.UUID | None) -> None:
    """planned (nothing dispatched) -> dispatched -> in progress (a trip has started) -> completed (every planned trip done)."""
    if job_id is None:
        return
    job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none()
    if job is None or job.status == JobStatus.CANCELLED:
        return
    await db.flush()
    trips = (await db.execute(select(Trip).where(Trip.job_id == job.id, Trip.status != TripStatus.CANCELLED))).scalars().all()
    done = sum(1 for t in trips if t.status == TripStatus.COMPLETED)
    started = any(t.status in (TripStatus.IN_PROGRESS, TripStatus.DELIVERED, TripStatus.COMPLETED) for t in trips)
    from app.recurrence import has_active_schedule

    if done >= job.trips_planned and not await has_active_schedule(db, job.id):  # work that comes round again is not finished
        job.status = JobStatus.COMPLETED
        job.completed_at = job.completed_at or now()
    elif started:
        job.status, job.completed_at = JobStatus.IN_PROGRESS, None
    elif trips:
        job.status, job.completed_at = JobStatus.DISPATCHED, None
    else:
        job.status, job.completed_at = JobStatus.PLANNED, None
