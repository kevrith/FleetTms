"""Payroll (masterplan 5.11): monthly salaries, advances taken back at month end, fines taken from the driver's pay, and each
salary's cost spread over the vehicles the person crewed, by days. Statutory deductions (PAYE, SHIF, NSSF, Housing Levy) and
payslips are a later phase."""

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.lease_rules import month_bounds
from app.models import (
    CrewAssignment,
    Incident,
    Membership,
    MembershipStatus,
    PayrollLine,
    PayrollRun,
    SalaryAdvance,
    StaffProfile,
)
from app.reminders import NAIROBI


def allocate_salary(salary_cents: int, days_by_vehicle: dict[uuid.UUID, int], days_in_month: int) -> list[dict]:
    """Spreads a salary over the vehicles crewed, in proportion to days; days with no vehicle are the business's own cost
    (vehicle_id None). The parts add up to the salary exactly (leftover cents go to the largest remainders)."""
    assigned = {v: min(d, days_in_month) for v, d in days_by_vehicle.items() if d > 0}
    free = max(0, days_in_month - sum(assigned.values()))
    weights: list[tuple[uuid.UUID | None, int]] = [*assigned.items()]
    if free or not weights:
        weights.append((None, free if weights else days_in_month))
    total = sum(w for _, w in weights) or 1
    floors = [(salary_cents * w) // total for _, w in weights]
    left = salary_cents - sum(floors)
    order = sorted(range(len(weights)), key=lambda i: (-((salary_cents * weights[i][1]) % total), i))
    for i in order[:left]:
        floors[i] += 1
    return [{"vehicle_id": str(v) if v else None, "cents": c} for (v, _), c in zip(weights, floors, strict=True) if c > 0]


async def crew_days(db: AsyncSession, month: date) -> dict[uuid.UUID, dict[uuid.UUID, int]]:
    """For each person, the days they crewed each vehicle in the month (Nairobi days, both ends counted)."""
    first, last = month_bounds(month)
    out: dict[uuid.UUID, dict[uuid.UUID, int]] = {}
    for a in (await db.execute(select(CrewAssignment))).scalars():
        start = a.started_at.astimezone(NAIROBI).date()
        end = a.ended_at.astimezone(NAIROBI).date() if a.ended_at else last
        lo, hi = max(first, start), min(last, end)
        if hi >= lo:
            per = out.setdefault(a.membership_id, {})
            per[a.vehicle_id] = per.get(a.vehicle_id, 0) + (hi - lo).days + 1
    return out


async def salary_cost(db: AsyncSession, month: date) -> dict[uuid.UUID, list[dict]]:
    """Each person's salary cost for the month, spread over vehicles. An approved payroll run is used where there is one;
    otherwise the salary on the person's profile is an estimate."""
    first, last = month_bounds(month)
    run = (await db.execute(select(PayrollRun).where(PayrollRun.month == first, PayrollRun.status.in_(("approved", "paid"))))).scalar_one_or_none()
    if run is not None:
        return {ln.membership_id: ln.allocation for ln in run.lines}
    days = await crew_days(db, month)
    people = (
        await db.execute(
            select(StaffProfile.membership_id, StaffProfile.monthly_salary_cents)
            .join(Membership, Membership.id == StaffProfile.membership_id)
            .where(StaffProfile.monthly_salary_cents.is_not(None), Membership.status == MembershipStatus.ACTIVE)
        )
    ).all()
    return {m: allocate_salary(salary, days.get(m, {}), last.day) for m, salary in people if salary}


async def draft_lines(db: AsyncSession, month: date) -> list[dict]:
    """What a payroll run for the month would pay each person: salary, less advances still owing, less fines the driver
    pays through payroll. Deductions never take more than the salary; what is left over waits for next month."""
    _, last = month_bounds(month)
    days = await crew_days(db, month)
    advances: dict[uuid.UUID, list[SalaryAdvance]] = {}
    for adv in (await db.execute(select(SalaryAdvance).where(SalaryAdvance.remaining_cents > 0).order_by(SalaryAdvance.given_on))).scalars():
        advances.setdefault(adv.membership_id, []).append(adv)
    fines: dict[uuid.UUID, list[Incident]] = {}
    for inc in (await db.execute(select(Incident).where(Incident.deduct_from_payroll.is_(True), Incident.driver_membership_id.is_not(None)).order_by(Incident.occurred_at))).scalars():
        if (inc.fine_amount_cents or 0) > inc.payroll_deducted_cents:
            fines.setdefault(inc.driver_membership_id, []).append(inc)
    people = (
        await db.execute(
            select(StaffProfile.membership_id, StaffProfile.monthly_salary_cents)
            .join(Membership, Membership.id == StaffProfile.membership_id)
            .where(StaffProfile.monthly_salary_cents.is_not(None), Membership.status == MembershipStatus.ACTIVE)
        )
    ).all()
    lines = []
    for membership_id, salary in people:
        if not salary:
            continue
        room, deductions = salary, []
        for adv in advances.get(membership_id, []):
            take = min(adv.remaining_cents, room)
            if take > 0:
                deductions.append({"kind": "advance", "id": str(adv.id), "cents": take, "note": adv.note})
                room -= take
        for inc in fines.get(membership_id, []):
            take = min((inc.fine_amount_cents or 0) - inc.payroll_deducted_cents, room)
            if take > 0:
                deductions.append({"kind": "fine", "id": str(inc.id), "cents": take, "note": inc.reference or inc.type.value.replace("_", " ")})
                room -= take
        adv_total = sum(d["cents"] for d in deductions if d["kind"] == "advance")
        fine_total = sum(d["cents"] for d in deductions if d["kind"] == "fine")
        lines.append(
            {
                "membership_id": membership_id, "gross_cents": salary, "advances_cents": adv_total, "fines_cents": fine_total, "net_cents": salary - adv_total - fine_total,
                "deductions": deductions, "allocation": allocate_salary(salary, days.get(membership_id, {}), last.day),
            }
        )
    return lines


async def apply_deductions(db: AsyncSession, run: PayrollRun) -> None:
    """When a run is approved, advances and fines are really taken: what they owe goes down."""
    for line in run.lines:
        for d in line.deductions:
            if d["kind"] == "advance":
                adv = (await db.execute(select(SalaryAdvance).where(SalaryAdvance.id == uuid.UUID(d["id"])))).scalar_one()
                adv.remaining_cents = max(0, adv.remaining_cents - d["cents"])
            else:
                inc = (await db.execute(select(Incident).where(Incident.id == uuid.UUID(d["id"])))).scalar_one()
                inc.payroll_deducted_cents += d["cents"]


def line_row(ln: PayrollLine) -> dict:
    return {
        "id": ln.id, "membership_id": ln.membership_id, "gross_cents": ln.gross_cents, "advances_cents": ln.advances_cents, "fines_cents": ln.fines_cents,
        "net_cents": ln.net_cents, "deductions": ln.deductions, "allocation": ln.allocation,
    }  # fmt: skip
