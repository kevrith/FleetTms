"""Owner dashboard v1 and basic reports (masterplan 5.15 and Section 6)."""

import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import Principal, error, require, require_any
from app.floatcalc import day_bounds
from app.models import (
    COUNTED,
    ComplianceDocument,
    Defect,
    Expense,
    ExpenseStatus,
    FloatTransfer,
    FuelEntry,
    Inspection,
    InspectionStatus,
    Priority,
    Reconciliation,
    ReconciliationStatus,
    Role,
    ServiceSchedule,
    Trip,
    TripStatus,
    Vehicle,
    WorkOrder,
)
from app.reminders import NAIROBI, nairobi_today
from app.routers.workshop import OPEN, schedule_out
from app.trust import flag_summary
from app.vehicle_scope import scope_vehicles

router = APIRouter(tags=["dashboard"])
MAX_REPORT_DAYS = 366


def alert(kind: str, severity: str, title: str, detail: str, link: str) -> dict:
    return {"kind": kind, "severity": severity, "title": title, "detail": detail, "link": link}


@router.get("/dashboard")
async def dashboard(
    principal: Principal = Depends(require_any("finance.view", "vehicles.view", "expenses.view", "reconciliations.approve")),
    db: AsyncSession = Depends(get_db),
):
    """How is my business doing right now: today's numbers and what needs attention, limited to what the caller may see."""
    perms, today = principal.permissions, nairobi_today()
    start, end = day_bounds(today)
    vehicles = {v.id: v for v in (await db.execute(scope_vehicles(select(Vehicle), principal))).scalars()}
    vids = list(vehicles)
    owner_driver = {Role.OWNER, Role.DRIVER} <= principal.roles
    mine = principal.membership_id if owner_driver else None  # an owner who also drives is not nagged about their own entries

    numbers: dict = {"mode": "owner_driver" if owner_driver else "standard", "day": today}
    if "trips.view" in perms or "vehicles.view" in perms:
        trips = select(Trip).where(Trip.vehicle_id.in_(vids))
        numbers["trips_active"] = len((await db.execute(trips.where(Trip.status.in_((TripStatus.IN_PROGRESS, TripStatus.DELIVERED))))).scalars().all())
        done = (await db.execute(trips.where(Trip.ended_at >= start, Trip.ended_at < end))).scalars().all()
        numbers["trips_completed_today"] = len(done)
        numbers["distance_today_km"] = sum(t.distance_km or 0 for t in done)
    if "vehicles.view" in perms:
        fuel = (await db.execute(select(FuelEntry).where(FuelEntry.vehicle_id.in_(vids), FuelEntry.captured_at >= start, FuelEntry.captured_at < end))).scalars().all()
        numbers["fuel_today"] = {"litres": float(sum(f.litres for f in fuel)), "amount_cents": sum(f.amount_cents for f in fuel)}
    if "expenses.view" in perms:
        spent = (
            await db.execute(
                select(func.coalesce(func.sum(Expense.amount_cents), 0)).where(
                    Expense.status.in_(COUNTED), Expense.spent_at >= start, Expense.spent_at < end,
                    (Expense.vehicle_id.in_(vids)) if principal.vehicle_scope is not None else True,
                )
            )
        ).scalar_one()
        numbers["expenses_today_cents"] = int(spent)
    if "floats.manage" in perms or "finance.view" in perms:
        sent = (await db.execute(select(func.coalesce(func.sum(FloatTransfer.amount_cents), 0)).where(FloatTransfer.sent_at >= start, FloatTransfer.sent_at < end, FloatTransfer.amount_cents > 0))).scalar_one()
        numbers["floats_sent_today_cents"] = int(sent)
    # Income, profit and money owed arrive with quotes, jobs and billing.
    numbers["income_today_cents"] = None
    numbers["money_owed_cents"] = None

    alerts: list[dict] = []
    if "vehicles.view" in perms:
        for s in (await db.execute(select(ServiceSchedule).where(ServiceSchedule.is_active.is_(True), ServiceSchedule.vehicle_id.in_(vids)))).scalars():
            row = schedule_out(s, vehicles[s.vehicle_id], today)
            if row["due_status"] == "overdue":
                alerts.append(alert("service_overdue", "red", f"{row['registration']}: {s.name} is overdue", "Book the service now.", f"/vehicles/{s.vehicle_id}"))
            elif row["due_status"] == "due_soon":
                left = f"{row['km_left']:,} km left" if row["km_left"] is not None and (row["days_left"] is None or row["km_left"] / 1000 < max(row["days_left"], 1)) else f"{row['days_left']} days left"
                alerts.append(alert("service_due", "amber", f"{row['registration']}: {s.name} is due soon", left, f"/vehicles/{s.vehicle_id}"))
        for wo in (await db.execute(select(WorkOrder).where(WorkOrder.status.in_(OPEN), WorkOrder.priority == Priority.URGENT, WorkOrder.vehicle_id.in_(vids)))).scalars():
            alerts.append(alert("work_order_urgent", "red", f"Urgent work order: {wo.title}", vehicles[wo.vehicle_id].registration, "/workshop"))
        blocked = (await db.execute(select(Inspection).where(Inspection.local_date == today, Inspection.status == InspectionStatus.BLOCKED, Inspection.vehicle_id.in_(vids)))).scalars()
        for i in blocked:
            alerts.append(alert("inspection_blocked", "red", f"{vehicles[i.vehicle_id].registration}: critical fault found today", "The vehicle cannot start a trip until a manager clears it.", f"/vehicles/{i.vehicle_id}"))
        for d in (await db.execute(select(ComplianceDocument).where(ComplianceDocument.vehicle_id.in_(vids), ComplianceDocument.expires_on <= today + timedelta(days=30)).order_by(ComplianceDocument.expires_on))).scalars():
            gone = d.expires_on < today
            alerts.append(alert("document_expired" if gone else "document_expiring", "red" if gone else "amber", f"{vehicles[d.vehicle_id].registration}: {d.doc_type.value.replace('_', ' ')} {'expired' if gone else 'expires'} {d.expires_on.isoformat()}", "", f"/vehicles/{d.vehicle_id}"))
        for vid, flags in (await flag_summary(db, vids)).items():
            alerts.append(alert("low_trust", "amber", f"{vehicles[vid].registration}: phone check failed", ", ".join(sorted(flags)).replace("_", " "), f"/vehicles/{vid}"))
        week = start - timedelta(days=6)
        for f in (await db.execute(select(FuelEntry).where(FuelEntry.vehicle_id.in_(vids), FuelEntry.captured_at >= week))).scalars():
            if "amount_mismatch" in f.flags:
                alerts.append(alert("fuel_flagged", "amber", f"{vehicles[f.vehicle_id].registration}: fuel total does not match litres times price", "", "/expenses/fuel"))
    if "expenses.approve_limit" in perms:
        waiting = (await db.execute(select(Expense).where(Expense.status == ExpenseStatus.AWAITING_APPROVAL, Expense.driver_membership_id != mine if mine else True))).scalars().all()
        if waiting:
            alerts.append(alert("expense_waiting", "amber", f"{len(waiting)} expense{'s' if len(waiting) != 1 else ''} waiting for your approval", "Over the spend limit.", "/expenses/expenses"))
    if "expenses.view" in perms:
        for e in (await db.execute(select(Expense).where(Expense.spent_at >= start - timedelta(days=6)))).scalars():
            if "unusual_for_route" in e.flags and e.status in COUNTED and (principal.vehicle_scope is None or e.vehicle_id in vids):
                alerts.append(alert("expense_unusual", "amber", f"Unusual {e.category.value.replace('_', ' ')} claim", f"KES {e.amount_cents / 100:,.2f} is well above the usual for this route.", "/expenses/expenses"))
    if "reconciliations.approve" in perms:
        query = select(Reconciliation).where(Reconciliation.status == ReconciliationStatus.SUBMITTED)
        if mine:
            query = query.where(Reconciliation.driver_membership_id != mine)
        waiting_rec = (await db.execute(query)).scalars().all()
        if waiting_rec:
            alerts.append(alert("reconciliation_waiting", "amber", f"{len(waiting_rec)} daily reconciliation{'s' if len(waiting_rec) != 1 else ''} waiting for approval", "", "/expenses/reconciliation"))
    order = {"red": 0, "amber": 1}
    alerts.sort(key=lambda a: order[a["severity"]])
    open_defects = int((await db.execute(select(func.count()).select_from(Defect).where(Defect.status != "fixed", Defect.vehicle_id.in_(vids)))).scalar_one()) if "vehicles.view" in perms else None
    return {"numbers": numbers, "alerts": alerts, "open_defects": open_defects}


@router.get("/reports/summary")
async def summary(
    date_from: date = Query(alias="from"),
    date_to: date = Query(alias="to"),
    principal: Principal = Depends(require("reports.view")),
    db: AsyncSession = Depends(get_db),
):
    """Totals for a date range (a day, a week, a month, or any range), by category, vehicle and day."""
    if date_to < date_from:
        raise error(422, "bad_range", "The end date is before the start date.")
    if (date_to - date_from).days >= MAX_REPORT_DAYS:
        raise error(422, "range_too_long", "Choose a range of a year or less.")
    start, _ = day_bounds(date_from)
    _, end = day_bounds(date_to)

    vehicles = {v.id: v for v in (await db.execute(select(Vehicle))).scalars()}
    per_vehicle: dict[uuid.UUID, dict] = {
        vid: {"vehicle_id": vid, "registration": v.registration, "trips": 0, "distance_km": 0, "fuel_litres": 0.0, "fuel_cents": 0, "expenses_cents": 0}
        for vid, v in vehicles.items()
    }  # fmt: skip
    per_day: dict[date, dict] = {}
    cursor = date_from
    while cursor <= date_to:
        per_day[cursor] = {"day": cursor, "trips": 0, "distance_km": 0, "fuel_cents": 0, "expenses_cents": 0}
        cursor += timedelta(days=1)

    for t in (await db.execute(select(Trip).where(Trip.status == TripStatus.COMPLETED, Trip.ended_at >= start, Trip.ended_at < end))).scalars():
        day = t.ended_at.astimezone(NAIROBI).date()
        per_day[day]["trips"] += 1
        per_day[day]["distance_km"] += t.distance_km or 0
        per_vehicle[t.vehicle_id]["trips"] += 1
        per_vehicle[t.vehicle_id]["distance_km"] += t.distance_km or 0
    fuel_litres = fuel_cents = 0
    for f in (await db.execute(select(FuelEntry).where(FuelEntry.captured_at >= start, FuelEntry.captured_at < end))).scalars():
        per_day[f.captured_at.astimezone(NAIROBI).date()]["fuel_cents"] += f.amount_cents
        per_vehicle[f.vehicle_id]["fuel_litres"] += float(f.litres)
        per_vehicle[f.vehicle_id]["fuel_cents"] += f.amount_cents
        fuel_litres, fuel_cents = fuel_litres + float(f.litres), fuel_cents + f.amount_cents
    by_category: dict[str, int] = {}
    expenses_cents = 0
    for e in (await db.execute(select(Expense).where(Expense.status.in_(COUNTED), Expense.spent_at >= start, Expense.spent_at < end))).scalars():
        per_day[e.spent_at.astimezone(NAIROBI).date()]["expenses_cents"] += e.amount_cents
        if e.vehicle_id in per_vehicle:
            per_vehicle[e.vehicle_id]["expenses_cents"] += e.amount_cents
        by_category[e.category.value] = by_category.get(e.category.value, 0) + e.amount_cents
        expenses_cents += e.amount_cents
    floats_cents = int((await db.execute(select(func.coalesce(func.sum(FloatTransfer.amount_cents), 0)).where(FloatTransfer.sent_at >= start, FloatTransfer.sent_at < end, FloatTransfer.amount_cents > 0))).scalar_one())

    rows = []
    for row in per_vehicle.values():
        if row["trips"] or row["fuel_cents"] or row["expenses_cents"]:
            row["km_per_litre"] = round(row["distance_km"] / row["fuel_litres"], 2) if row["fuel_litres"] else None
            rows.append(row)
    days = list(per_day.values())
    return {
        "from": date_from, "to": date_to,
        "totals": {
            "trips_completed": sum(d["trips"] for d in days), "distance_km": sum(d["distance_km"] for d in days),
            "fuel_litres": round(fuel_litres, 2), "fuel_cents": fuel_cents, "expenses_cents": expenses_cents,
            "floats_sent_cents": floats_cents,
        },
        "expenses_by_category": sorted(({"category": c, "cents": v} for c, v in by_category.items()), key=lambda x: -x["cents"]),
        "by_vehicle": sorted(rows, key=lambda r: r["registration"]),
        "by_day": days,
    }


