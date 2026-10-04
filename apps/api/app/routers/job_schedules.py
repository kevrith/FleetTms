"""Recurring work (masterplan 5.x, jobs: "a recurring contract job"): set a job up once, and each coming day's work is put in the diary by itself.

A per-trip, per-tonne or per-kilometre job is repeated as a new job each time. A monthly contract already bills itself every month, so its
schedule sends a trip of the contract out each time instead (it needs a lorry). Managers are told by text when a day could not be given a lorry."""

import uuid
from datetime import date, time
from typing import Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, recurrence
from app.db import get_db
from app.deps import Principal, error, require
from app.models import BillingMethod, Client, Job, JobSchedule, JobScheduleRun, JobStatus, Vehicle
from app.reminders import nairobi_today

router = APIRouter(tags=["jobs"])


class ScheduleIn(BaseModel):
    template_job_id: uuid.UUID
    cadence: Literal["daily", "weekly", "monthly"]
    weekdays: list[int] = []
    day_of_month: int | None = Field(default=None, ge=1, le=28)
    pickup_time: time
    deliver_within_hours: int = Field(default=24, ge=1, le=240)
    lead_days: int = Field(default=2, ge=0, le=14)
    starts_on: date | None = None
    ends_on: date | None = None
    vehicle_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def coherent(self):
        if self.cadence == "weekly" and (not self.weekdays or any(d < 0 or d > 6 for d in self.weekdays)):
            raise ValueError("Choose the weekdays (0 is Monday, 6 is Sunday).")
        if self.cadence == "monthly" and self.day_of_month is None:
            raise ValueError("Choose the day of the month (1 to 28).")
        if self.ends_on and self.starts_on and self.ends_on < self.starts_on:
            raise ValueError("The end date is before the start date.")
        return self


class ScheduleUpdate(BaseModel):
    weekdays: list[int] | None = None
    day_of_month: int | None = Field(default=None, ge=1, le=28)
    pickup_time: time | None = None
    deliver_within_hours: int | None = Field(default=None, ge=1, le=240)
    lead_days: int | None = Field(default=None, ge=0, le=14)
    ends_on: date | None = None
    vehicle_id: uuid.UUID | None = None
    is_active: bool | None = None


async def _get(db: AsyncSession, schedule_id: uuid.UUID) -> JobSchedule:
    row = (await db.execute(select(JobSchedule).where(JobSchedule.id == schedule_id))).scalar_one_or_none()
    if row is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That schedule was not found.")
    return row


async def out(db: AsyncSession, s: JobSchedule, *, runs: bool = False) -> dict:
    template = (await db.execute(select(Job).where(Job.id == s.template_job_id))).scalar_one_or_none()
    client = (await db.execute(select(Client).where(Client.id == template.client_id))).scalar_one_or_none() if template else None
    vehicle = (await db.execute(select(Vehicle).where(Vehicle.id == s.vehicle_id))).scalar_one_or_none() if s.vehicle_id else None
    body = {
        "id": s.id, "template_job_id": s.template_job_id, "template": template.number if template else None, "client": client.name if client else None,
        "contract": bool(template and template.billing_method == BillingMethod.MONTHLY_CONTRACT), "cadence": s.cadence, "weekdays": s.weekdays, "day_of_month": s.day_of_month,
        "pickup_time": s.pickup_time.strftime("%H:%M"), "deliver_within_hours": s.deliver_within_hours, "lead_days": s.lead_days, "starts_on": s.starts_on, "ends_on": s.ends_on,
        "vehicle_id": s.vehicle_id, "registration": vehicle.registration if vehicle else None, "is_active": s.is_active, "next": recurrence.upcoming(s),
    }  # fmt: skip
    if runs:
        rows = (await db.execute(select(JobScheduleRun).where(JobScheduleRun.schedule_id == s.id).order_by(JobScheduleRun.occurrence_on.desc()).limit(60))).scalars().all()
        body["runs"] = [{"day": r.occurrence_on, "job_id": r.job_id, "trip_id": r.trip_id, "note": r.note} for r in rows]
    return body


@router.post("/job-schedules", status_code=status.HTTP_201_CREATED)
async def create_schedule(body: ScheduleIn, principal: Principal = Depends(require("jobs.manage")), db: AsyncSession = Depends(get_db)):
    template = (await db.execute(select(Job).where(Job.id == body.template_job_id))).scalar_one_or_none()
    if template is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That job was not found.")
    if template.status == JobStatus.CANCELLED:
        raise error(status.HTTP_409_CONFLICT, "cancelled", "A cancelled job cannot be repeated.")
    contract = template.billing_method == BillingMethod.MONTHLY_CONTRACT
    if contract and body.vehicle_id is None:
        raise error(422, "lorry_needed", "A monthly contract already bills itself each month, so its schedule sends a lorry out each time. Choose the lorry.")
    if body.vehicle_id is not None and (await db.execute(select(Vehicle.id).where(Vehicle.id == body.vehicle_id, Vehicle.is_active.is_(True)))).first() is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That vehicle was not found.")
    row = JobSchedule(
        template_job_id=template.id, vehicle_id=body.vehicle_id, cadence=body.cadence, weekdays=sorted(set(body.weekdays)), day_of_month=body.day_of_month,
        pickup_time=body.pickup_time, deliver_within_hours=body.deliver_within_hours, lead_days=body.lead_days, starts_on=body.starts_on or nairobi_today(),
        ends_on=body.ends_on, created_by_user_id=principal.user.id,
    )  # fmt: skip
    db.add(row)
    await db.flush()
    audit.record(db, actor_user_id=principal.user.id, action="job_schedule.created", entity_type="job_schedule", entity_id=row.id, after={"template": template.number, "cadence": row.cadence})
    await db.commit()
    return await out(db, row)


@router.get("/job-schedules")
async def list_schedules(principal: Principal = Depends(require("jobs.manage")), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(JobSchedule).order_by(JobSchedule.created_at.desc()))).scalars().all()
    return [await out(db, s) for s in rows]


@router.get("/job-schedules/{schedule_id}")
async def read_schedule(schedule_id: uuid.UUID, principal: Principal = Depends(require("jobs.manage")), db: AsyncSession = Depends(get_db)):
    return await out(db, await _get(db, schedule_id), runs=True)


@router.put("/job-schedules/{schedule_id}")
async def update_schedule(schedule_id: uuid.UUID, body: ScheduleUpdate, principal: Principal = Depends(require("jobs.manage")), db: AsyncSession = Depends(get_db)):
    s = await _get(db, schedule_id)
    changes = body.model_dump(exclude_unset=True)
    if "weekdays" in changes:
        if s.cadence != "weekly" or not changes["weekdays"] or any(d < 0 or d > 6 for d in changes["weekdays"]):
            raise error(422, "bad_weekdays", "Weekdays apply to a weekly schedule, and must be 0 (Monday) to 6 (Sunday).")
        changes["weekdays"] = sorted(set(changes["weekdays"]))
    if "day_of_month" in changes and s.cadence != "monthly":
        raise error(422, "bad_day", "A day of the month applies to a monthly schedule.")
    for field, value in changes.items():
        setattr(s, field, value)
    audit.record(db, actor_user_id=principal.user.id, action="job_schedule.updated", entity_type="job_schedule", entity_id=s.id, after={k: str(v) for k, v in changes.items()})
    await db.commit()
    return await out(db, s)


@router.post("/job-schedules/{schedule_id}/run")
async def run_now(schedule_id: uuid.UUID, principal: Principal = Depends(require("jobs.manage")), db: AsyncSession = Depends(get_db)):
    """Puts the coming days in the diary now, instead of waiting for the early-morning run. Days already in the diary are left alone."""
    s = await _get(db, schedule_id)
    made = await recurrence.materialise(db, s)
    await db.commit()
    return {"made": [{"day": r.occurrence_on, "job_id": r.job_id, "trip_id": r.trip_id, "note": r.note} for r in made]}
