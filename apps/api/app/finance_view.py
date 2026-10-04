"""Money numbers for the dashboard (masterplan 5.15): what you billed, what you were paid, and what is still owed.

This is a first look at profit against cash. Costs here are the expenses and fuel recorded; salaries, lease payments and
overheads join in the true-cost engine (Sprint 10)."""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.floatcalc import day_bounds
from app.lease_rules import add_months
from app.models import (
    COUNTED,
    Expense,
    FinanceAgreement,
    FuelEntry,
    Invoice,
    InvoicePayment,
    LeaseAgreement,
    Vehicle,
)


async def owed_cents(db: AsyncSession) -> int:
    rows = (await db.execute(select(Invoice).where(Invoice.status.in_(("issued", "partially_paid"))))).scalars().all()
    return sum(max(0, i.total_cents - sum(p.amount_cents for p in i.payments)) for i in rows)


async def billed_cents(db: AsyncSession, start: date, end: date) -> int:
    """What was invoiced between two dates (inclusive), before VAT: VAT is the taxman's money, not income. Balances brought forward from the old system were invoiced there, so they are not income here."""
    return int((await db.execute(select(func.coalesce(func.sum(Invoice.subtotal_cents), 0)).where(Invoice.issue_date >= start, Invoice.issue_date <= end, Invoice.status != "void", Invoice.kind != "opening"))).scalar_one())


async def profit_vs_cash(db: AsyncSession, today: date) -> dict:
    """This month so far."""
    first = today.replace(day=1)
    start, _ = day_bounds(first)
    _, end = day_bounds(today)
    billed = await billed_cents(db, first, today)
    received = int(
        (
            await db.execute(
                select(func.coalesce(func.sum(InvoicePayment.amount_cents), 0)).join(Invoice, Invoice.id == InvoicePayment.invoice_id)
                .where(InvoicePayment.received_on >= first, InvoicePayment.received_on <= today, Invoice.status != "void")
            )
        ).scalar_one()
    )  # fmt: skip
    fuel = int((await db.execute(select(func.coalesce(func.sum(FuelEntry.amount_cents), 0)).where(FuelEntry.captured_at >= start, FuelEntry.captured_at < end))).scalar_one())
    spent = int((await db.execute(select(func.coalesce(func.sum(Expense.amount_cents), 0)).where(Expense.status.in_(COUNTED), Expense.spent_at >= start, Expense.spent_at < end))).scalar_one())
    costs = fuel + spent
    return {
        "month_start": first, "billed_cents": billed, "costs_cents": costs, "profit_cents": billed - costs,
        "received_cents": received, "cash_cents": received - costs, "owed_cents": await owed_cents(db),
    }  # fmt: skip


async def last_month_profit(db: AsyncSession, today: date) -> dict:
    """How each lorry (and the business) did last month after every deduction, including what was paid to a lorry's owner."""
    from app.profit import build

    month = add_months(today.replace(day=1), -1)
    data = await build(db, month, month)
    return {
        "month": month, "business": data["business"],
        "vehicles": [
            {"vehicle_id": v["vehicle_id"], "registration": v["registration"], "ownership_type": v["ownership_type"], "revenue_cents": v["revenue"], "gross_profit_cents": v["gross"], "lease_payable_cents": v["lease_payable"], "net_profit_cents": v["net"], "lease_not_paying": v["lease_not_paying"]}
            for v in data["vehicles"] if v["revenue"] or v["operating"] or v["lease_charges"] or v["finance"] or v["ownership"]
        ],
    }  # fmt: skip


async def lease_alerts(db: AsyncSession, today: date, not_paying: list[str]) -> list[dict]:
    """Lease and loan payments that are overdue or due within three days, and leases that are not paying off."""
    from datetime import timedelta

    from app.leases import entries_of, standing_of

    out: list[dict] = []
    names = {v.id: v.registration for v in (await db.execute(select(Vehicle))).scalars()}
    for a in (await db.execute(select(LeaseAgreement).where(LeaseAgreement.status == "active"))).scalars():
        s = standing_of(await entries_of(db, a.id), today)
        reg = names.get(a.vehicle_id, "A vehicle")
        who = "the lessor" if a.direction == "in" else "the lessee"
        if s["overdue_cents"] > 0:
            title = f"{reg}: lease payment of KES {s['overdue_cents'] / 100:,.2f} to {who} is overdue" if a.direction == "in" else f"{reg}: the lessee owes KES {s['overdue_cents'] / 100:,.2f} and is late"
            out.append({"kind": "lease_overdue", "severity": "red", "title": title, "detail": "", "link": "/leases"})
        elif s["next_due_date"] is not None and s["next_due_date"] <= today + timedelta(days=3):
            out.append({"kind": "lease_due", "severity": "amber", "title": f"{reg}: lease payment of KES {s['balance_cents'] / 100:,.2f} falls due {s['next_due_date']:%d %b}", "detail": "", "link": "/leases"})
    for f in (await db.execute(select(FinanceAgreement).where(FinanceAgreement.status == "active"))).scalars():
        owing = [i for i in f.instalments if i.paid_cents < i.amount_cents]
        late = sum(i.amount_cents - i.paid_cents for i in owing if i.due_date < today)
        reg = names.get(f.vehicle_id, "A vehicle")
        if late:
            out.append({"kind": "loan_overdue", "severity": "red", "title": f"{reg}: loan repayment of KES {late / 100:,.2f} is overdue", "detail": "", "link": "/leases/finance"})
        elif owing and min(i.due_date for i in owing) <= today + timedelta(days=3):
            nxt = min(owing, key=lambda i: i.due_date)
            out.append({"kind": "loan_due", "severity": "amber", "title": f"{reg}: loan repayment of KES {(nxt.amount_cents - nxt.paid_cents) / 100:,.2f} falls due {nxt.due_date:%d %b}", "detail": "", "link": "/leases/finance"})
    for reg in not_paying:
        out.append({"kind": "lease_not_paying", "severity": "amber", "title": f"{reg}: the lorry's owner has earned more than you for three months running", "detail": "Look at whether this lease is worth keeping.", "link": "/leases/profit"})
    return out
