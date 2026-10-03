"""The report catalogue (masterplan 5.15): every report builds the same shape (a title, then sections that are tables), so any of them can
be looked at on screen, exported as PDF or Excel, and scheduled by email or WhatsApp. Money in the tables is in KES, as a reader wants it."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import fraud, report_files
from app.floatcalc import day_bounds
from app.models import BehaviourEvent, FraudAlert, FuelEntry, Membership, Trip, TripStatus, Vehicle
from app.reminders import NAIROBI, nairobi_today

MAX_DAYS = 366


def kes(cents: int | None) -> float | None:
    return None if cents is None else cents / 100


@dataclass(frozen=True)
class Report:
    key: str
    title: str
    description: str
    permissions: tuple[str, ...]  # any one of these lets a person run it
    feature: str | None  # the plan feature it needs; None means every plan has it
    period: bool = True  # False for a report that is a picture of now (debtors)


def _data(key: str, title: str, start: date, end: date, sections: list, notes: list[str] | None = None) -> dict:
    return {"key": key, "title": title, "from": start, "to": end, "notes": notes or [], "sections": [{"title": t, "columns": c, "rows": r} for t, c, r in sections]}


def system_principal(business_id) -> SimpleNamespace:
    """For a scheduled report, which nobody is signed in to read: the whole business, as the owner who scheduled it would see it."""
    return SimpleNamespace(vehicle_scope=None, business_id=business_id, permissions={"finance.view", "reports.view", "alerts.view", "invoices.manage", "clients.manage"}, user=None, roles=set(), membership_id=None)


async def summary(db: AsyncSession, start: date, end: date, principal) -> dict:
    from app.routers.dashboard import build_summary

    data = await build_summary(db, start, end)
    return _data("summary", "Summary", start, end, report_files._tables(data))


async def profit(db: AsyncSession, start: date, end: date, principal) -> dict:
    from app import profit as profit_engine

    first, last = start.replace(day=1), end.replace(day=1)
    d = await profit_engine.build(db, first, last)
    b = d["business"]
    business = [
        ["Revenue", kes(b["revenue"])], ["Running costs (fuel, expenses, crew)", kes(b["operating"])], ["Gross profit", kes(b["gross"])], ["Lease payable to lessors", kes(b["lease_payable"])],
        ["Finance repayments", kes(b["finance"])], ["Ownership costs (depreciation and the like)", kes(b["ownership"])], ["Net profit across vehicles", kes(b["net"])],
        ["Overheads (office, payroll)", kes(b["overheads"])], ["Net profit after overheads", kes(b["net_after_overheads"])],
    ]  # fmt: skip
    vehicles = [
        [v["registration"], v["trips"], v["km"], kes(v["revenue"]), kes(v["operating"]), kes(v["gross"]), kes(v["lease_payable"]), kes(v["finance"]), kes(v["ownership"]), kes(v["net"]), kes(v["cost_per_km"]), kes(v["revenue_per_km"])]
        for v in d["vehicles"]
    ]  # fmt: skip
    clients = [[c["name"], c["trips"], kes(c["revenue_cents"]), kes(c["direct_cost_cents"]), kes(c["contribution_cents"])] for c in d["clients"]]
    drivers = [[x["name"], x["trips"], x["distance_km"], kes(x["revenue_cents"]), kes(x["direct_cost_cents"]), kes(x["contribution_cents"])] for x in d["drivers"]]
    notes = [f"Profit is worked out in whole months: {first.strftime('%B %Y')} to {last.strftime('%B %Y')}."]
    if b["not_on_a_trip"]:
        notes.append(f"{kes(b['not_on_a_trip'])} of fuel and expenses is not on any trip: it is in the business and vehicle figures, but in no client or driver row.")
    return _data("profit", "Profit and loss", start, end, [
        ("The business", ["Measure", "KES"], business),
        ("By vehicle", ["Vehicle", "Trips", "Km", "Revenue", "Running costs", "Gross profit", "Lease payable", "Finance", "Ownership", "Net profit", "Cost per km", "Revenue per km"], vehicles),
        ("By client (before overheads)", ["Client", "Trips", "Revenue", "Direct costs", "Contribution"], clients),
        ("By driver (before overheads)", ["Driver", "Trips", "Km", "Revenue", "Direct costs", "Contribution"], drivers),
    ], notes)  # fmt: skip


async def fuel_efficiency(db: AsyncSession, start: date, end: date, principal) -> dict:
    begin, _ = day_bounds(start)
    _, finish = day_bounds(end)
    vehicles = {v.id: v for v in (await db.execute(select(Vehicle))).scalars()}
    trips = list((await db.execute(select(Trip).where(Trip.ended_at >= begin, Trip.ended_at < finish, Trip.status.in_((TripStatus.DELIVERED, TripStatus.COMPLETED))))).scalars())
    entries = list((await db.execute(select(FuelEntry).where(FuelEntry.captured_at >= begin, FuelEntry.captured_at < finish))).scalars())
    idle: dict = defaultdict(float)
    for e in (await db.execute(select(BehaviourEvent).where(BehaviourEvent.kind == "idling", BehaviourEvent.at >= begin, BehaviourEvent.at < finish))).scalars():
        idle[e.vehicle_id] += (e.value or 0) / 60
    per: dict = {}
    for t in trips:
        row = per.setdefault(t.vehicle_id, {"trips": 0, "km": 0.0, "litres": 0.0, "cents": 0})
        row["trips"] += 1
        row["km"] += fraud.best_km(t) or 0
    for e in entries:
        row = per.setdefault(e.vehicle_id, {"trips": 0, "km": 0.0, "litres": 0.0, "cents": 0})
        row["litres"] += float(e.litres)
        row["cents"] += e.amount_cents
    rows = []
    for vid, r in per.items():
        if vid in vehicles:
            kpl = round(r["km"] / r["litres"], 2) if r["litres"] and r["km"] else None
            rows.append([vehicles[vid].registration, r["trips"], round(r["km"]), round(r["litres"], 1), kpl, kes(r["cents"]), round(r["cents"] / 100 / r["km"], 2) if r["km"] else None, round(idle[vid], 1)])
    rows.sort(key=lambda r: (r[4] is None, -(r[4] or 0)))  # most efficient first
    fuel = await fraud._fuel_by_trip(db, trips)
    people = {m.id: m.user.name for m in (await db.execute(select(Membership))).scalars()}
    by_driver: dict = {}
    for t in trips:
        if t.driver_membership_id:
            r = by_driver.setdefault(t.driver_membership_id, {"trips": 0, "km": 0.0, "litres": 0.0})
            r["trips"] += 1
            r["km"] += fraud.best_km(t) or 0
            r["litres"] += fuel.get(t.id, 0.0)
    drivers = [[people.get(d, "Unknown"), r["trips"], round(r["km"]), round(r["litres"], 1), round(r["km"] / r["litres"], 2) if r["litres"] and r["km"] else None] for d, r in by_driver.items()]
    drivers.sort(key=lambda r: (r[4] is None, -(r[4] or 0)))
    return _data("fuel_efficiency", "Fuel efficiency and cost per kilometre", start, end, [
        ("By vehicle, most efficient first", ["Vehicle", "Trips", "Km", "Fuel (litres)", "Km per litre", "Fuel (KES)", "Fuel cost per km (KES)", "Idling (hours)"], rows),
        ("By driver, most efficient first", ["Driver", "Trips", "Km", "Fuel on their trips (litres)", "Km per litre"], drivers),
    ], ["Km are the distances of trips that ended in the period; litres are the fuel recorded in it, so a fill-up made for the next trip shows against this period."])  # fmt: skip


async def debtors(db: AsyncSession, start: date, end: date, principal) -> dict:
    from app.routers import debtors as debtors_router

    d = await debtors_router.debtors(principal, db)
    b = ["current", "1_30", "31_60", "61_90", "over_90"]
    rows = [[c["name"], kes(c["balance_cents"]), *[kes(c["buckets"][k]) for k in b], c["invoices"], c["oldest_days_late"]] for c in d["clients"]]
    rows.append(["Everyone", kes(d["balance_cents"]), *[kes(d["buckets"][k]) for k in b], None, None])
    today = nairobi_today()
    return _data("debtors", "Who owes us", today, today, [("Clients, most overdue first", ["Client", "Owes (KES)", "Not yet due", "1-30 days late", "31-60", "61-90", "Over 90", "Open invoices", "Oldest, days late"], rows)], [f"As at {d['as_of'].isoformat()}. This report is a picture of now, not of a period."])


async def alerts(db: AsyncSession, start: date, end: date, principal) -> dict:
    begin, _ = day_bounds(start)
    _, finish = day_bounds(end)
    query = select(FraudAlert).where(FraudAlert.occurred_at >= begin, FraudAlert.occurred_at < finish).order_by(FraudAlert.occurred_at.desc())
    scope = getattr(principal, "vehicle_scope", None)
    rows = [a for a in (await db.execute(query)).scalars() if scope is None or (a.vehicle_id is not None and str(a.vehicle_id) in scope)]
    regs = {v.id: v.registration for v in (await db.execute(select(Vehicle))).scalars()}
    people = {m.id: m.user.name for m in (await db.execute(select(Membership))).scalars()}
    kinds: dict = defaultdict(lambda: defaultdict(int))
    for a in rows:
        kinds[a.kind][a.status] += 1
    from app.routers.fraud import LABELS

    by_kind = [[LABELS.get(k, k), sum(c.values()), c["open"], c["explained"], c["confirmed"]] for k, c in sorted(kinds.items(), key=lambda kv: -sum(kv[1].values()))]
    listing = [[a.occurred_at.astimezone(NAIROBI).strftime("%Y-%m-%d %H:%M"), regs.get(a.vehicle_id, ""), people.get(a.driver_membership_id, ""), a.severity, a.title, a.status, a.note or ""] for a in rows]
    return _data("alerts", "Alert history", start, end, [("By kind", ["Check", "Raised", "Waiting", "Explained", "Confirmed"], by_kind), ("Every alert", ["When", "Vehicle", "Driver", "Severity", "What", "Answer", "Note"], listing)])


async def scorecards(db: AsyncSession, start: date, end: date, principal) -> dict:
    from app.routers import scorecards as scorecards_router

    d = await scorecards_router.scorecards(start, end, principal, db)
    rows = [[c["name"], c["trips"], c["km"], c["safety"], c["fuel"], c["punctuality"], c["inspections"], c["alerts"], c["overall"]] for c in d["drivers"]]
    return _data("scorecards", "Driver scorecards", start, end, [("Drivers, best first", ["Driver", "Trips", "Km", "Safety", "Fuel", "On time", "Inspections", "Alerts", "Overall"], rows)], ["Each part is out of 100. The overall score weighs safety 30, fuel 25, and the other three 15 each, leaving out any part with no data."])


CATALOG: dict[str, tuple[Report, object]] = {
    "summary": (Report("summary", "Summary", "Trips, distance, fuel and expenses by type, vehicle and day.", ("reports.view",), None), summary),
    "profit": (Report("profit", "Profit and loss", "Revenue, running costs, lease, finance and ownership: profit by vehicle, client and driver.", ("finance.view",), "custom_reports"), profit),
    "fuel_efficiency": (Report("fuel_efficiency", "Fuel efficiency and cost per km", "Kilometres a litre and fuel cost per kilometre, with idling, for each vehicle and driver.", ("reports.view",), "custom_reports"), fuel_efficiency),
    "debtors": (Report("debtors", "Who owes us", "Balances by client with ageing: not yet due, then 1-30, 31-60, 61-90 and over 90 days late.", ("finance.view", "invoices.manage"), "custom_reports", False), debtors),
    "alerts": (Report("alerts", "Alert history", "Every fraud and tamper alert in the period, with how it was answered.", ("alerts.view",), "custom_reports"), alerts),
    "scorecards": (Report("scorecards", "Driver scorecards", "Safety, fuel, punctuality, inspections and alerts for each driver.", ("reports.view",), "scorecards"), scorecards),
}  # fmt: skip


def check_range(start: date | None, end: date | None) -> tuple[date, date]:
    end = end or nairobi_today()
    start = start or end - timedelta(days=29)
    return start, end


def render(data: dict, file_format: str) -> tuple[bytes, str, str]:
    """(file bytes, file name, mime type) for a report as pdf or xlsx."""
    sections = [(s["title"], s["columns"], s["rows"]) for s in data["sections"]]
    stem = f"fleettms-{data['key']}-{data['from'].isoformat()}-to-{data['to'].isoformat()}".replace("_", "-")
    if file_format == "xlsx":
        return report_files.sections_xlsx(sections), f"{stem}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    title = f"FleetTms: {data['title']}, {data['from'].isoformat()} to {data['to'].isoformat()}"
    return report_files.sections_pdf(title, sections, data["notes"]), f"{stem}.pdf", "application/pdf"
