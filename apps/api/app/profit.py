"""The profit engine (masterplan 5.15 and 5.23): what each trip, vehicle, client, driver, depot and the whole business really
made, after every deduction. Works in whole calendar months because leases, loans, ownership costs and salaries are monthly.

Gross profit is revenue less the cost of running (fuel, expenses, crew pay). What a lorry's owner is paid (the lease charges less
the costs the operator paid on the owner's behalf) comes off next, then loan repayments and ownership costs, which gives the net.
A cost the lease makes the owner's responsibility is left out of the operator's costs and shown as paid on the owner's behalf; it
comes back to the operator as an offset against the lease charge.

Client and driver rows are the trip's own contribution (revenue less the fuel and expenses booked to the trip); fixed and shared
costs belong to vehicles, depots and the business."""

import uuid
from collections import defaultdict
from datetime import date, datetime
from itertools import pairwise

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.floatcalc import day_bounds
from app.lease_config import (
    CATEGORY_OWNERSHIP_KIND,
    has_variable_terms,
    item_for_category,
    matrix_of,
    terms_of,
)
from app.lease_rules import (
    Usage,
    add_months,
    lease_not_paying,
    month_bounds,
    month_charge,
    net_profit,
    ownership_monthly,
)
from app.models import (
    COUNTED,
    Client,
    Depot,
    Expense,
    FinanceAgreement,
    FinanceInstalment,
    FuelEntry,
    Invoice,
    Job,
    LeaseAgreement,
    LeaseEntry,
    Membership,
    OdometerReading,
    OwnershipCost,
    Trip,
    TripStatus,
    Vehicle,
)
from app.payroll_service import salary_cost
from app.reminders import NAIROBI


def month_of(moment: datetime) -> date:
    return moment.astimezone(NAIROBI).date().replace(day=1)


def months_between(first: date, last: date) -> list[date]:
    out, cursor = [], first.replace(day=1)
    while cursor <= last.replace(day=1):
        out.append(cursor)
        cursor = add_months(cursor, 1)
    return out


async def trip_revenue(db: AsyncSession, trips: list[Trip]) -> tuple[dict[uuid.UUID, int], set[uuid.UUID], set[uuid.UUID]]:
    """What each delivered trip earned (before VAT): its invoice, or its share of the month's contract fee. Returns
    (revenue, trips whose revenue is an estimate, trips with no revenue yet)."""
    if not trips:
        return {}, set(), set()
    ids = [t.id for t in trips]
    invoices = (await db.execute(select(Invoice).where(Invoice.status != "void"))).scalars().all()
    by_trip = {i.trip_id: i for i in invoices if i.trip_id in ids}
    jobs = {j.id: j for j in (await db.execute(select(Job).where(Job.id.in_({t.job_id for t in trips if t.job_id})))).scalars()}
    revenue: dict[uuid.UUID, int] = {}
    estimated: set[uuid.UUID] = set()
    contract: dict[tuple[uuid.UUID, date], list[Trip]] = defaultdict(list)
    for t in trips:
        job = jobs.get(t.job_id) if t.job_id else None
        if job is not None and job.billing_method.value == "monthly_contract":
            contract[(job.id, month_of(t.delivered_at or t.ended_at))].append(t)
        elif t.id in by_trip:
            revenue[t.id] = by_trip[t.id].subtotal_cents
    for (job_id, month), group in contract.items():
        invoice = next((i for i in invoices if i.job_id == job_id and i.kind == "contract" and i.period_start == month), None)
        fee = invoice.subtotal_cents if invoice is not None else jobs[job_id].rate_cents
        group.sort(key=lambda t: (t.delivered_at or t.ended_at, str(t.id)))
        share, rest = divmod(fee, len(group))
        for n, t in enumerate(group):
            revenue[t.id] = share + (rest if n == len(group) - 1 else 0)
            if invoice is None:
                estimated.add(t.id)
    return revenue, estimated, {t.id for t in trips if t.id not in revenue}


def _new() -> dict:
    return {"revenue": 0, "fuel": 0, "expenses": 0, "crew": 0, "lessor_paid": 0, "trips": 0, "km": 0, "loaded_km": 0, "empty_km": 0, "unbilled": 0, "estimated": 0}


async def build(db: AsyncSession, first_month: date, last_month: date) -> dict:
    first_month, last_month = first_month.replace(day=1), last_month.replace(day=1)
    shown = months_between(first_month, last_month)
    window = months_between(add_months(first_month, -2), last_month)  # two earlier months, for "is this lease paying off"
    start, _ = day_bounds(window[0])
    _, end = day_bounds(month_bounds(last_month)[1])
    vehicles = {v.id: v for v in (await db.execute(select(Vehicle))).scalars()}
    depots = {d.id: d.name for d in (await db.execute(select(Depot))).scalars()}

    agreements: dict[uuid.UUID, list[LeaseAgreement]] = defaultdict(list)
    for a in (await db.execute(select(LeaseAgreement))).scalars():
        agreements[a.vehicle_id].append(a)
    ledger: dict[tuple[uuid.UUID, date, str], int] = defaultdict(int)  # (agreement, month, kind) -> cents
    for e in (await db.execute(select(LeaseEntry).where(LeaseEntry.kind.in_(("charge", "offset"))))).scalars():
        if e.period_start is not None:
            ledger[(e.agreement_id, e.period_start, e.kind)] += e.amount_cents
    ledger_has = {(a, m) for (a, m, k) in ledger if k == "charge"}
    ownership: dict[uuid.UUID, list[OwnershipCost]] = defaultdict(list)
    for o in (await db.execute(select(OwnershipCost))).scalars():
        ownership[o.vehicle_id].append(o)
    finance: dict[tuple[uuid.UUID, date], int] = defaultdict(int)
    loans = {f.id: f for f in (await db.execute(select(FinanceAgreement))).scalars()}
    for i in (await db.execute(select(FinanceInstalment))).scalars():
        finance[(loans[i.agreement_id].vehicle_id, i.due_date.replace(day=1))] += i.amount_cents

    def agreement_in(vehicle_id: uuid.UUID, month: date, direction: str | None = None) -> list[LeaseAgreement]:
        first, last = month_bounds(month)
        return [a for a in agreements.get(vehicle_id, []) if a.start_date <= last and (a.end_date is None or a.end_date >= first) and (direction is None or a.direction == direction)]

    def ownership_kinds(vehicle_id: uuid.UUID, month: date) -> set[str]:
        first, last = month_bounds(month)
        return {o.kind for o in ownership.get(vehicle_id, []) if o.start_date <= last and (o.end_date is None or o.end_date >= first)}

    # ---- trips and their revenue ----
    trips = [
        t for t in (await db.execute(select(Trip).where(Trip.status.in_((TripStatus.DELIVERED, TripStatus.COMPLETED))))).scalars()
        if (t.delivered_at or t.ended_at) and start <= (t.delivered_at or t.ended_at) < end
    ]  # fmt: skip
    revenue, estimated, unbilled = await trip_revenue(db, trips)
    jobs = {j.id: j for j in (await db.execute(select(Job))).scalars()}
    readings: dict[uuid.UUID, dict[str, int]] = defaultdict(dict)
    for r in (await db.execute(select(OdometerReading))).scalars():
        readings[r.trip_id][r.phase.value] = r.confirmed_value

    fig: dict[tuple[uuid.UUID, date], dict] = defaultdict(_new)
    trip_cost: dict[uuid.UUID, int] = defaultdict(int)
    by_vehicle_trips: dict[uuid.UUID, list[Trip]] = defaultdict(list)
    for t in trips:
        by_vehicle_trips[t.vehicle_id].append(t)
        f = fig[(t.vehicle_id, month_of(t.delivered_at or t.ended_at))]
        f["trips"] += 1
        f["revenue"] += revenue.get(t.id, 0)
        f["km"] += t.distance_km or 0
        f["loaded_km" if (t.job_id or t.loaded_at) else "empty_km"] += t.distance_km or 0
        f["unbilled"] += t.id in unbilled
        f["estimated"] += t.id in estimated
    for vid, group in by_vehicle_trips.items():  # kilometres driven between trips: empty running nobody recorded as a trip
        group.sort(key=lambda t: t.started_at or t.created_at)
        for prev, nxt in pairwise(group):
            end_km, start_km = readings.get(prev.id, {}).get("end"), readings.get(nxt.id, {}).get("start")
            if end_km is not None and start_km is not None and start_km > end_km:
                f = fig[(vid, month_of(nxt.started_at or nxt.created_at))]
                f["empty_km"] += start_km - end_km
                f["km"] += start_km - end_km

    # ---- costs ----
    overhead_expenses = 0
    for fu in (await db.execute(select(FuelEntry).where(FuelEntry.captured_at >= start, FuelEntry.captured_at < end))).scalars():
        m = month_of(fu.captured_at)
        lessor = any(matrix_of(a).get("fuel") == "lessor" for a in agreement_in(fu.vehicle_id, m, "in"))
        fig[(fu.vehicle_id, m)]["lessor_paid" if lessor else "fuel"] += fu.amount_cents
        if fu.trip_id and not lessor:
            trip_cost[fu.trip_id] += fu.amount_cents
    for ex in (await db.execute(select(Expense).where(Expense.status.in_(COUNTED), Expense.spent_at >= start, Expense.spent_at < end))).scalars():
        m = month_of(ex.spent_at)
        if ex.vehicle_id is None:
            if first_month <= m <= last_month:
                overhead_expenses += ex.amount_cents
            continue
        kind = CATEGORY_OWNERSHIP_KIND.get(ex.category)
        if kind and kind in ownership_kinds(ex.vehicle_id, m):
            continue  # the spread ownership cost already covers it
        item = item_for_category(ex.category)
        lessor = bool(item) and any(matrix_of(a).get(item) == "lessor" for a in agreement_in(ex.vehicle_id, m, "in"))
        fig[(ex.vehicle_id, m)]["lessor_paid" if lessor else "expenses"] += ex.amount_cents
        if ex.trip_id and not lessor:
            trip_cost[ex.trip_id] += ex.amount_cents

    overhead_payroll = 0
    for m in window:
        for allocation in (await salary_cost(db, m)).values():
            for part in allocation:
                if part["vehicle_id"] is None:
                    overhead_payroll += part["cents"] if m in shown else 0
                else:
                    vid = uuid.UUID(part["vehicle_id"])
                    lessor = any(matrix_of(a).get("driver_salary") == "lessor" for a in agreement_in(vid, m, "in"))
                    if not lessor:
                        fig[(vid, m)]["crew"] += part["cents"]

    # ---- per vehicle, per month ----
    rows: dict[uuid.UUID, dict] = {}
    history: dict[uuid.UUID, list[dict]] = defaultdict(list)
    for vid, v in vehicles.items():
        total = {k: 0 for k in ("revenue", "fuel", "expenses", "crew", "lessor_paid", "operating", "gross", "lease_charges", "lease_offsets", "lease_income", "finance", "ownership", "net", "trips", "km", "loaded_km", "empty_km", "unbilled", "estimated")}  # fmt: skip
        provisional = False
        for m in window:
            f = fig.get((vid, m)) or _new()
            operating = f["fuel"] + f["expenses"] + f["crew"]
            leases_in, leases_out = agreement_in(vid, m, "in"), agreement_in(vid, m, "out")
            charges = offsets = income = 0
            for a in leases_in + leases_out:
                if (a.id, m) in ledger_has:
                    c, o = ledger[(a.id, m, "charge")], -ledger[(a.id, m, "offset")]
                else:
                    c = month_charge(terms_of(a), m, Usage(trips=f["trips"], km=f["km"], revenue_cents=f["revenue"], profit_cents=f["revenue"] - operating))["charge_cents"]
                    o = f["lessor_paid"] if a.direction == "in" else 0
                    provisional = provisional or has_variable_terms(a) and a.direction == "out"
                if a.direction == "in":
                    charges, offsets = charges + c, offsets + o
                else:
                    income += c - o
            out_only = bool(leases_out) and not leases_in
            rev = income if out_only else f["revenue"] + income
            fin = finance.get((vid, m), 0)
            own = sum(ownership_monthly(kind=o.kind, amount_cents=o.amount_cents, period=o.period, salvage_cents=o.salvage_cents, life_months=o.life_months, start=o.start_date, end=o.end_date, month=m) for o in ownership.get(vid, []))  # fmt: skip
            result = net_profit(revenue_cents=rev, operating_cents=operating, lease_charges_cents=charges, offsets_cents=offsets, finance_cents=fin, ownership_cents=own)
            history[vid].append({"month": m, "lessor_cents": result["lease_payable_cents"], "operator_net_cents": result["net_profit_cents"], "has_lease": bool(leases_in)})
            if m not in shown:
                continue
            for k, val in (("revenue", rev), ("fuel", f["fuel"]), ("expenses", f["expenses"]), ("crew", f["crew"]), ("lessor_paid", f["lessor_paid"]), ("operating", operating), ("gross", result["gross_profit_cents"]), ("lease_charges", charges), ("lease_offsets", offsets), ("lease_income", income), ("finance", fin), ("ownership", own), ("net", result["net_profit_cents"]), ("trips", f["trips"]), ("km", f["km"]), ("loaded_km", f["loaded_km"]), ("empty_km", f["empty_km"]), ("unbilled", f["unbilled"]), ("estimated", f["estimated"])):  # fmt: skip
                total[k] += val
        recent = history[vid][-3:]
        total.update(
            registration=v.registration, ownership_type=v.ownership_type.value, vehicle_id=vid, depot_id=v.depot_id, lease_payable=total["lease_charges"] - total["lease_offsets"],
            cost_per_km=round(total["operating"] / total["km"]) if total["km"] else None, revenue_per_km=round(total["revenue"] / total["km"]) if total["km"] else None,
            lease_not_paying=all(m["has_lease"] for m in recent) and lease_not_paying(recent), provisional=provisional,
        )  # fmt: skip
        rows[vid] = total

    # ---- trips, clients, drivers ----
    people = {m.id: m.user.name for m in (await db.execute(select(Membership))).scalars()}
    clients = {c.id: c.name for c in (await db.execute(select(Client))).scalars()}
    shown_first, _ = day_bounds(first_month)
    trip_rows = []
    for t in trips:
        moment = t.delivered_at or t.ended_at
        if not (shown_first <= moment < end):
            continue
        job = jobs.get(t.job_id) if t.job_id else None
        rev, cost = revenue.get(t.id, 0), trip_cost.get(t.id, 0)
        trip_rows.append(
            {
                "trip_id": t.id, "vehicle_id": t.vehicle_id, "registration": vehicles[t.vehicle_id].registration, "route": f"{t.origin or ''} to {t.destination or ''}".strip(" to"),
                "delivered_at": moment, "client_id": job.client_id if job else None, "client_name": clients.get(job.client_id) if job else None,
                "driver_membership_id": t.driver_membership_id, "driver_name": people.get(t.driver_membership_id), "distance_km": t.distance_km or 0,
                "revenue_cents": rev, "direct_cost_cents": cost, "contribution_cents": rev - cost, "estimated": t.id in estimated, "unbilled": t.id in unbilled,
            }
        )

    def group(key: str, name: str) -> list[dict]:
        acc: dict = {}
        for r in trip_rows:
            k = r[key]
            g = acc.setdefault(k, {key: k, "name": r[name] or "No " + key.split("_")[0], "trips": 0, "revenue_cents": 0, "direct_cost_cents": 0, "contribution_cents": 0, "distance_km": 0})
            g["trips"] += 1
            for f in ("revenue_cents", "direct_cost_cents", "contribution_cents", "distance_km"):
                g[f] += r[f]
        return sorted(acc.values(), key=lambda g: -g["contribution_cents"])

    by_depot: dict = {}
    for r in rows.values():
        d = by_depot.setdefault(r["depot_id"], {"depot_id": r["depot_id"], "name": depots.get(r["depot_id"], "No depot"), "vehicles": 0, **{k: 0 for k in ("revenue", "operating", "gross", "lease_payable", "finance", "ownership", "net")}})
        d["vehicles"] += 1
        for k in ("revenue", "operating", "gross", "lease_payable", "finance", "ownership", "net"):
            d[k] += r[k]
    vehicle_rows = sorted(rows.values(), key=lambda r: r["registration"])
    sums = {k: sum(r[k] for r in vehicle_rows) for k in ("revenue", "operating", "gross", "lease_payable", "lease_income", "finance", "ownership", "net", "trips", "km", "loaded_km", "empty_km", "unbilled", "estimated", "lessor_paid")}  # fmt: skip
    overheads = overhead_expenses + overhead_payroll
    return {
        "from_month": first_month, "to_month": last_month, "months": shown,
        "vehicles": vehicle_rows, "depots": sorted(by_depot.values(), key=lambda d: d["name"]), "trips": sorted(trip_rows, key=lambda r: r["delivered_at"], reverse=True),
        "clients": group("client_id", "client_name"), "drivers": group("driver_membership_id", "driver_name"),
        "business": {**sums, "overheads": overheads, "overhead_expenses": overhead_expenses, "overhead_payroll": overhead_payroll, "net_after_overheads": sums["net"] - overheads},
    }  # fmt: skip
