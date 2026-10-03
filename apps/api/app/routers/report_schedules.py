"""Scheduled report delivery: who gets the PDF, how often and by which channel (masterplan 5.15)."""

import uuid
from typing import Literal

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, report_catalog, subscriptions
from app.db import get_db
from app.deps import Principal, error, require
from app.models import ReportChannel, ReportFrequency, ReportSchedule
from app.phone import normalize_phone
from app.reminders import nairobi_today
from app.report_delivery import DeliveryError
from app.report_schedules import last_finished_period, send_schedule

router = APIRouter(tags=["reports"])
MAX_SCHEDULES = 20


class ScheduleIn(BaseModel):
    frequency: ReportFrequency
    channel: ReportChannel
    recipient: str
    report: str = "summary"  # which report from the catalogue
    file_format: Literal["pdf", "xlsx"] = "pdf"


class ScheduleActive(BaseModel):
    is_active: bool


def _out(s: ReportSchedule) -> dict:
    return {
        "id": s.id, "frequency": s.frequency, "channel": s.channel, "recipient": s.recipient, "report": s.report, "file_format": s.file_format, "is_active": s.is_active,
        "last_period_end": s.last_period_end, "last_error": s.last_error,
    }  # fmt: skip


def _recipient(channel: ReportChannel, raw: str) -> str:
    if channel == ReportChannel.EMAIL:
        try:
            return validate_email(raw.strip(), check_deliverability=False).normalized
        except EmailNotValidError:
            raise error(422, "invalid_recipient", "Enter a valid email address.") from None
    phone = normalize_phone(raw)
    if phone is None:
        raise error(422, "invalid_recipient", "Enter a valid phone number for WhatsApp.")
    return phone


async def _get(db: AsyncSession, schedule_id: uuid.UUID) -> ReportSchedule:
    schedule = (await db.execute(select(ReportSchedule).where(ReportSchedule.id == schedule_id))).scalar_one_or_none()
    if schedule is None:
        raise error(404, "not_found", "That scheduled report was not found.")
    return schedule


@router.get("/report-schedules")
async def list_schedules(principal: Principal = Depends(require("reports.schedule")), db: AsyncSession = Depends(get_db)):
    return [_out(s) for s in (await db.execute(select(ReportSchedule).order_by(ReportSchedule.created_at))).scalars()]


@router.post("/report-schedules", status_code=status.HTTP_201_CREATED)
async def create_schedule(body: ScheduleIn, principal: Principal = Depends(require("reports.schedule")), db: AsyncSession = Depends(get_db)):
    recipient = _recipient(body.channel, body.recipient)
    if body.report not in report_catalog.CATALOG:
        raise error(422, "unknown_report", f"Choose one of: {', '.join(report_catalog.CATALOG)}.")
    definition = report_catalog.CATALOG[body.report][0]
    if not any(p in principal.permissions for p in definition.permissions):
        raise error(403, "forbidden", "You do not have permission to schedule that report.")
    if definition.feature:
        await subscriptions.require_feature(db, principal.business_id, definition.feature)
    existing = (await db.execute(select(ReportSchedule))).scalars().all()
    if len(existing) >= MAX_SCHEDULES:
        raise error(422, "too_many", f"You can have up to {MAX_SCHEDULES} scheduled reports.")
    if any((s.frequency, s.channel, s.recipient, s.report, s.file_format) == (body.frequency, body.channel, recipient, body.report, body.file_format) for s in existing):
        raise error(409, "duplicate_schedule", "That report is already scheduled for this recipient.")
    schedule = ReportSchedule(frequency=body.frequency, channel=body.channel, recipient=recipient, report=body.report, file_format=body.file_format, created_by_user_id=principal.user.id)
    db.add(schedule)
    await db.flush()
    audit.record(db, actor_user_id=principal.user.id, action="report_schedule.created", entity_type="report_schedule", entity_id=schedule.id, after={"frequency": body.frequency.value, "channel": body.channel.value})
    await db.commit()
    return _out(schedule)


@router.patch("/report-schedules/{schedule_id}")
async def set_active(schedule_id: uuid.UUID, body: ScheduleActive, principal: Principal = Depends(require("reports.schedule")), db: AsyncSession = Depends(get_db)):
    schedule = await _get(db, schedule_id)
    schedule.is_active = body.is_active
    audit.record(db, actor_user_id=principal.user.id, action="report_schedule.paused" if not body.is_active else "report_schedule.resumed", entity_type="report_schedule", entity_id=schedule.id)
    await db.commit()
    return _out(schedule)


@router.delete("/report-schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(schedule_id: uuid.UUID, principal: Principal = Depends(require("reports.schedule")), db: AsyncSession = Depends(get_db)):
    schedule = await _get(db, schedule_id)
    audit.record(db, actor_user_id=principal.user.id, action="report_schedule.deleted", entity_type="report_schedule", entity_id=schedule.id)
    await db.delete(schedule)
    await db.commit()


@router.post("/report-schedules/{schedule_id}/send-now")
async def send_now(schedule_id: uuid.UUID, principal: Principal = Depends(require("reports.schedule")), db: AsyncSession = Depends(get_db)):
    """Sends the latest finished period straight away, as a test. It does not count as the scheduled send."""
    schedule = await _get(db, schedule_id)
    try:
        await send_schedule(db, schedule, last_finished_period(schedule.frequency, nairobi_today()))
    except DeliveryError as e:
        raise error(502, "delivery_failed", str(e)) from None
    return {"sent": True}
