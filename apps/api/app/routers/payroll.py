"""Payroll (masterplan 5.11): salary advances, monthly runs with advances and fines taken off, and each salary spread over
the vehicles the person crewed so true cost per lorry includes the crew."""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, mpesa, payroll_service
from app.db import get_db
from app.deps import Principal, error, require_any
from app.lease_rules import month_bounds
from app.models import Membership, PayrollLine, PayrollRun, SalaryAdvance, StaffProfile, Vehicle
from app.reminders import nairobi_today

router = APIRouter(tags=["payroll"])
VIEW = ("payroll.view",)
MANAGE = ("payroll.manage",)


class AdvanceIn(BaseModel):
    membership_id: uuid.UUID
    amount_cents: int = Field(gt=0, le=10_000_000_000)
    given_on: date | None = None
    mpesa_code: str | None = None
    note: str | None = Field(default=None, max_length=255)


class RunIn(BaseModel):
    month: date


class PaidIn(BaseModel):
    paid_on: date | None = None


async def _names(db: AsyncSession) -> dict[uuid.UUID, str]:
    return {m.id: m.user.name for m in (await db.execute(select(Membership))).scalars()}


def advance_out(a: SalaryAdvance, names: dict) -> dict:
    return {"id": a.id, "membership_id": a.membership_id, "name": names.get(a.membership_id), "amount_cents": a.amount_cents, "remaining_cents": a.remaining_cents, "given_on": a.given_on, "mpesa_code": a.mpesa_code, "note": a.note}


async def run_out(db: AsyncSession, run: PayrollRun, *, detail: bool = False) -> dict:
    names = await _names(db)
    out = {
        "id": run.id, "month": run.month, "status": run.status, "approved_at": run.approved_at, "paid_on": run.paid_on, "people": len(run.lines),
        "gross_cents": sum(ln.gross_cents for ln in run.lines), "deductions_cents": sum(ln.advances_cents + ln.fines_cents for ln in run.lines), "net_cents": sum(ln.net_cents for ln in run.lines),
    }  # fmt: skip
    if detail:
        regs = {str(v.id): v.registration for v in (await db.execute(select(Vehicle))).scalars()}
        out["lines"] = [
            {**payroll_service.line_row(ln), "name": names.get(ln.membership_id), "allocation": [{"registration": regs.get(a["vehicle_id"]) if a["vehicle_id"] else None, "cents": a["cents"]} for a in ln.allocation]}
            for ln in sorted(run.lines, key=lambda ln: names.get(ln.membership_id, ""))
        ]  # fmt: skip
    return out


async def _run(db: AsyncSession, run_id: uuid.UUID) -> PayrollRun:
    run = (await db.execute(select(PayrollRun).where(PayrollRun.id == run_id).with_for_update())).scalar_one_or_none()
    if run is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That payroll run was not found.")
    return run


@router.get("/payroll/advances")
async def list_advances(owing_only: bool = False, principal: Principal = Depends(require_any(*VIEW)), db: AsyncSession = Depends(get_db)):
    names = await _names(db)
    query = select(SalaryAdvance).order_by(SalaryAdvance.given_on.desc())
    if owing_only:
        query = query.where(SalaryAdvance.remaining_cents > 0)
    return [advance_out(a, names) for a in (await db.execute(query)).scalars()]


@router.post("/payroll/advances", status_code=status.HTTP_201_CREATED)
async def give_advance(body: AdvanceIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    """Money given to a staff member before payday. It is taken back from their next salary."""
    m = (await db.execute(select(Membership).where(Membership.id == body.membership_id))).scalar_one_or_none()
    if m is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That staff member was not found.")
    try:
        code = mpesa.tidy(body.mpesa_code)
    except ValueError as e:
        raise error(422, "invalid_mpesa_code", str(e)) from None
    if code and await mpesa.taken(db, code):
        raise error(status.HTTP_409_CONFLICT, "duplicate_mpesa_code", "That M-Pesa code was already recorded.")
    a = SalaryAdvance(membership_id=m.id, amount_cents=body.amount_cents, remaining_cents=body.amount_cents, given_on=body.given_on or nairobi_today(), mpesa_code=code, note=body.note, created_by_user_id=principal.user.id)
    db.add(a)
    await db.flush()
    audit.record(db, actor_user_id=principal.user.id, action="payroll.advance_given", entity_type="salary_advance", entity_id=a.id, after={"membership_id": str(m.id), "amount_cents": a.amount_cents})
    await db.commit()
    return advance_out(a, {m.id: m.user.name})


@router.get("/payroll/runs")
async def list_runs(principal: Principal = Depends(require_any(*VIEW)), db: AsyncSession = Depends(get_db)):
    return [await run_out(db, r) for r in (await db.execute(select(PayrollRun).order_by(PayrollRun.month.desc()))).scalars()]


async def _fill(db: AsyncSession, run: PayrollRun) -> None:
    run.lines.clear()
    await db.flush()
    for ln in await payroll_service.draft_lines(db, run.month):
        run.lines.append(PayrollLine(**ln))


@router.post("/payroll/runs", status_code=status.HTTP_201_CREATED)
async def create_run(body: RunIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    first, _ = month_bounds(body.month)
    if first > nairobi_today():
        raise error(422, "future_month", "That month has not started yet.")
    if (await db.execute(select(PayrollRun.id).where(PayrollRun.month == first))).first() is not None:
        raise error(status.HTTP_409_CONFLICT, "run_exists", "There is already a payroll run for that month.")
    run = PayrollRun(month=first, lines=[])
    db.add(run)
    await db.flush()
    await _fill(db, run)
    if not run.lines:
        raise error(422, "no_salaries", "Nobody has a monthly salary set. Add salaries on the staff page first.")
    audit.record(db, actor_user_id=principal.user.id, action="payroll.run_created", entity_type="payroll_run", entity_id=run.id, after={"month": first.isoformat(), "people": len(run.lines)})
    await db.commit()
    return await run_out(db, run, detail=True)


@router.get("/payroll/runs/{run_id}")
async def read_run(run_id: uuid.UUID, principal: Principal = Depends(require_any(*VIEW)), db: AsyncSession = Depends(get_db)):
    return await run_out(db, await _run(db, run_id), detail=True)


@router.post("/payroll/runs/{run_id}/recalculate")
async def recalculate(run_id: uuid.UUID, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    """Works the draft out again (a new advance, a new fine, a changed salary). Only a draft can change."""
    run = await _run(db, run_id)
    if run.status != "draft":
        raise error(status.HTTP_409_CONFLICT, "locked", "Only a draft payroll run can be recalculated.")
    before = _totals(run)
    await _fill(db, run)
    audit.record(db, actor_user_id=principal.user.id, action="payroll.run_recalculated", entity_type="payroll_run", entity_id=run.id, before=before, after=_totals(run))
    await db.commit()
    return await run_out(db, run, detail=True)


def _totals(run) -> dict:
    """What a draft run adds up to, for the audit trail: how many people and the money going out."""
    return {"people": len(run.lines), "gross_cents": sum(x.gross_cents for x in run.lines), "advances_cents": sum(x.advances_cents for x in run.lines), "fines_cents": sum(x.fines_cents for x in run.lines)}


@router.post("/payroll/runs/{run_id}/approve")
async def approve(run_id: uuid.UUID, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    """Locks the run: advances and fines are really taken off what people owe, and the salary cost counts towards each lorry."""
    run = await _run(db, run_id)
    if run.status != "draft":
        raise error(status.HTTP_409_CONFLICT, "locked", "That payroll run is already approved.")
    await payroll_service.apply_deductions(db, run)
    from datetime import UTC, datetime

    run.status, run.approved_by_user_id, run.approved_at = "approved", principal.user.id, datetime.now(UTC)
    audit.record(db, actor_user_id=principal.user.id, action="payroll.run_approved", entity_type="payroll_run", entity_id=run.id, after={"month": run.month.isoformat(), "net_cents": sum(ln.net_cents for ln in run.lines)})
    await db.commit()
    return await run_out(db, run, detail=True)


@router.post("/payroll/runs/{run_id}/paid")
async def mark_paid(run_id: uuid.UUID, body: PaidIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    run = await _run(db, run_id)
    if run.status != "approved":
        raise error(status.HTTP_409_CONFLICT, "not_approved", "Approve the run before marking it paid.")
    run.status, run.paid_on = "paid", body.paid_on or nairobi_today()
    audit.record(db, actor_user_id=principal.user.id, action="payroll.run_paid", entity_type="payroll_run", entity_id=run.id, after={"paid_on": run.paid_on.isoformat()})
    await db.commit()
    return await run_out(db, run, detail=True)


@router.get("/payroll/people")
async def people_with_salary(principal: Principal = Depends(require_any(*VIEW)), db: AsyncSession = Depends(get_db)):
    """Who has a salary on file (for choosing who gets an advance)."""
    names = await _names(db)
    rows = (await db.execute(select(StaffProfile.membership_id, StaffProfile.monthly_salary_cents).where(StaffProfile.monthly_salary_cents.is_not(None)))).all()
    return [{"membership_id": m, "name": names.get(m), "monthly_salary_cents": s} for m, s in rows]
