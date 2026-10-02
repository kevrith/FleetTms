"""Debtors (masterplan 5.10): who owes what, how late it is, and what has been paid."""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.debtor_rules import BUCKETS, ageing_bucket, days_late
from app.deps import Principal, error, require_any
from app.models import Client, Invoice, PaymentReminder
from app.payment_reminders import balance_of
from app.reminders import nairobi_today

router = APIRouter(tags=["debtors"])
MANAGE = ("invoices.manage",)


def _empty() -> dict:
    return {b: 0 for b in BUCKETS}


def _open(invoices: list[Invoice]) -> list[Invoice]:
    return [i for i in invoices if i.status in ("issued", "partially_paid") and balance_of(i) > 0]


def invoice_row(i: Invoice, today: date) -> dict:
    return {
        "id": i.id, "number": i.number, "issue_date": i.issue_date, "due_date": i.due_date, "total_cents": i.total_cents, "balance_cents": balance_of(i),
        "days_late": max(0, days_late(i.due_date, today)), "bucket": ageing_bucket(i.due_date, today),
    }  # fmt: skip


@router.get("/debtors")
async def debtors(principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    """Balance per client with ageing: not yet due, then 1-30, 31-60, 61-90 and over 90 days late."""
    today = nairobi_today()
    clients = {c.id: c for c in (await db.execute(select(Client))).scalars()}
    invoices = _open((await db.execute(select(Invoice))).scalars().all())
    last_paid: dict[uuid.UUID, date] = {}
    for i in (await db.execute(select(Invoice))).scalars():
        for p in i.payments:
            if p.received_on > last_paid.get(i.client_id, date.min):
                last_paid[i.client_id] = p.received_on
    rows: dict[uuid.UUID, dict] = {}
    for i in invoices:
        c = clients[i.client_id]
        row = rows.setdefault(
            c.id, {"client_id": c.id, "name": c.name, "phone": c.phone, "email": c.email, "reminders_enabled": c.reminders_enabled, "balance_cents": 0, "overdue_cents": 0, "buckets": _empty(), "invoices": 0, "oldest_due": None, "last_payment_on": last_paid.get(c.id)},
        )  # fmt: skip
        bal = balance_of(i)
        bucket = ageing_bucket(i.due_date, today)
        row["balance_cents"] += bal
        row["buckets"][bucket] += bal
        row["overdue_cents"] += bal if bucket != "current" else 0
        row["invoices"] += 1
        row["oldest_due"] = min(row["oldest_due"] or i.due_date, i.due_date)
    for row in rows.values():
        row["oldest_days_late"] = max(0, days_late(row["oldest_due"], today))
    ordered = sorted(rows.values(), key=lambda r: (-r["overdue_cents"], -r["balance_cents"]))
    totals = _empty()
    for r in ordered:
        for b in BUCKETS:
            totals[b] += r["buckets"][b]
    return {"as_of": today, "balance_cents": sum(totals.values()), "overdue_cents": sum(v for b, v in totals.items() if b != "current"), "buckets": totals, "clients": ordered}


@router.get("/debtors/{client_id}")
async def debtor(client_id: uuid.UUID, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    """One client: open invoices with their age, every payment received, and the reminders sent."""
    client = (await db.execute(select(Client).where(Client.id == client_id))).scalar_one_or_none()
    if client is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That client was not found.")
    today = nairobi_today()
    every = (await db.execute(select(Invoice).where(Invoice.client_id == client_id).order_by(Invoice.due_date))).scalars().all()
    open_rows = [invoice_row(i, today) for i in _open(list(every))]
    buckets = _empty()
    for r in open_rows:
        buckets[r["bucket"]] += r["balance_cents"]
    payments = sorted(
        ({"invoice_id": i.id, "invoice_number": i.number, "received_on": p.received_on, "amount_cents": p.amount_cents, "method": p.method, "reference": p.reference} for i in every for p in i.payments),
        key=lambda p: p["received_on"], reverse=True,
    )  # fmt: skip
    ids = [i.id for i in every]
    reminders = (await db.execute(select(PaymentReminder).where(PaymentReminder.invoice_id.in_(ids)).order_by(PaymentReminder.sent_at.desc()).limit(30))).scalars().all() if ids else []
    numbers = {i.id: i.number for i in every}
    return {
        "client": {"id": client.id, "name": client.name, "phone": client.phone, "email": client.email, "payment_terms_days": client.payment_terms_days, "reminders_enabled": client.reminders_enabled},
        "as_of": today, "balance_cents": sum(buckets.values()), "buckets": buckets, "invoices": open_rows, "payments": payments,
        "reminders": [{"invoice_number": numbers[r.invoice_id], "channel": r.channel, "status": r.status, "sent_at": r.sent_at, "automatic": r.offset_days is not None} for r in reminders],
    }  # fmt: skip
