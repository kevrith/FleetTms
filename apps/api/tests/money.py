"""Helpers for Sprint 9 tests: invoices made directly (so a test about money does not need a whole delivery), the Safaricom
callback, and payment settings."""

import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from app import daraja
from app.db import get_sessionmaker
from app.etims_service import queue_sale
from app.models import Business, Invoice, InvoiceLine
from app.numbering import create_numbered
from app.reminders import nairobi_today
from app.tenancy import current_business_id
from tests.helpers import bearer
from tests.test_clients import add_client

SHORTCODE = "174379"


async def business_id(name: str = "Kamau Haulage") -> uuid.UUID:
    async with get_sessionmaker()() as db:
        return (await db.execute(select(Business.id).where(Business.name == name))).scalar_one()


async def seed_invoice(client_id, *, total_cents=1_000_000, due_in=30, vat_pct=0, business="Kamau Haulage", queue=True, void=False, lines=None) -> dict:
    """An issued invoice for a client, due `due_in` days from today (negative: already late)."""
    today = nairobi_today()
    async with get_sessionmaker()() as db:
        current_business_id.set(await business_id(business))
        try:
            subtotal = round(total_cents / (1 + vat_pct / 100)) if vat_pct else total_cents
            vat = total_cents - subtotal
            items = lines or [("Transport Mombasa to Nairobi", subtotal)]
            invoice = await create_numbered(
                db, Invoice, "INV", client_id=uuid.UUID(str(client_id)), kind="trip", issue_date=today, due_date=today + timedelta(days=due_in),
                status="void" if void else "issued", subtotal_cents=subtotal, vat_pct=Decimal(vat_pct), vat_cents=vat, total_cents=total_cents, payments=[],
                lines=[InvoiceLine(description=d, quantity=Decimal(1), unit_cents=a, amount_cents=a, sort_order=n) for n, (d, a) in enumerate(items)],
            )  # fmt: skip
            if queue and not void:
                await queue_sale(db, invoice)
            await db.commit()
            return {"id": str(invoice.id), "number": invoice.number}
        finally:
            current_business_id.set(None)


async def owner_with_client(client, **client_extra):
    from tests.helpers import owner_session

    owner, _ = await owner_session(client)
    c = await add_client(client, owner, billing_method="per_trip", rate_cents=1_000_000, **client_extra)
    return owner, c


async def configure(client, owner, **settings):
    body = {"shortcode": SHORTCODE, **settings}
    res = await client.put("/payments/settings", headers=bearer(owner), json=body)
    assert res.status_code == 200, res.text
    return res.json()


def c2b(trans_id="QGH7XYZ123", amount="10000.00", bill_ref="INV-0001", **extra) -> dict:
    return {
        "TransactionType": "Pay Bill", "TransID": trans_id, "TransTime": "20261002101500", "TransAmount": amount, "BusinessShortCode": SHORTCODE,
        "BillRefNumber": bill_ref, "InvoiceNumber": "", "OrgAccountBalance": "0.00", "ThirdPartyTransID": "", "MSISDN": "fe3b1c0aaf", "FirstName": "John", "MiddleName": "", "LastName": "Kamau", **extra,
    }  # fmt: skip


async def pay_in(client, business: uuid.UUID, body: dict, *, key: str | None = None, kind: str = "confirmation"):
    """What Safaricom does: post the payment notice to the business's secret address."""
    return await client.post(f"/hooks/c2b/{business}/{key or daraja.callback_key(business)}/{kind}", json=body)


async def invoice(client, owner, invoice_id) -> dict:
    res = await client.get(f"/invoices/{invoice_id}", headers=bearer(owner))
    assert res.status_code == 200, res.text
    return res.json()
