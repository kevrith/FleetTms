"""Payment reminders (masterplan 5.10): unpaid invoices are chased by SMS and email on a schedule the owner sets (by default
3 days before the due date, then 1, 7, 14 and 30 days after). Each reminder is recorded, so none repeats; if several are
behind only the latest is sent. Off until the owner turns it on, and off per client with `reminders_enabled`."""

import logging
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.db import get_sessionmaker
from app.debtor_rules import days_late, reminder_offset_due
from app.invoicing import pay_instructions, render_invoice_pdf
from app.models import Business, Client, Invoice, PaymentReminder, PaymentSettings
from app.payment_config import get_settings
from app.reminders import nairobi_today
from app.report_delivery import DeliveryError, get_report_sender
from app.sms import get_sms_sender
from app.tenancy import current_business_id

log = logging.getLogger(__name__)
MAX_TRIES = 3


def kes(cents: int) -> str:
    return f"KES {cents / 100:,.2f}"


def balance_of(invoice: Invoice) -> int:
    return invoice.total_cents - sum(p.amount_cents for p in invoice.payments)


def reminder_text(*, business: str, invoice: Invoice, balance_cents: int, today: date, pay: str | None) -> tuple[str, str]:
    """(short text for SMS, longer text for an email body)."""
    late = days_late(invoice.due_date, today)
    if late <= 0:
        when = f"is due on {invoice.due_date.strftime('%d %b %Y')}" if late < 0 else "is due today"
        tone = "A friendly reminder:"
    else:
        when = f"was due on {invoice.due_date.strftime('%d %b %Y')} and is {late} day{'s' if late != 1 else ''} overdue"
        tone = "Payment reminder:"
    how = f" {pay}" if pay else ""
    sms = f"{business}: {tone} invoice {invoice.number} for {kes(balance_cents)} {when}.{how} Please ignore this if you have already paid."
    email = f"Hello,\n\n{tone} invoice {invoice.number} from {business} for {kes(balance_cents)} {when}. The invoice is attached.\n\n{pay or ''}\n\nPlease ignore this message if you have already paid. Thank you.\n\n{business}"
    return sms, email


async def _send_one(db: AsyncSession, invoice: Invoice, client: Client, business: Business, cfg: PaymentSettings, channel: str, today: date) -> tuple[str, str | None]:
    """Sends one reminder on one channel. Returns (recipient, error text or None)."""
    recipient = (client.phone if channel == "sms" else client.email) or ""
    pay = pay_instructions(cfg, invoice)
    sms, email = reminder_text(business=business.name, invoice=invoice, balance_cents=balance_of(invoice), today=today, pay=pay)
    try:
        if channel == "sms":
            await get_sms_sender().send(recipient, sms)
        else:
            subject = f"Payment reminder: invoice {invoice.number} from {business.name}"
            await get_report_sender("email").send(recipient, subject, f"{invoice.number}.pdf", await render_invoice_pdf(db, invoice), email)
    except DeliveryError as e:
        return recipient, str(e)
    except Exception:
        log.exception("Reminder for %s on %s failed", invoice.number, channel)
        return recipient, "The message could not be sent."
    return recipient, None


async def remind(
    db: AsyncSession, invoice: Invoice, client: Client, business: Business, cfg: PaymentSettings, *, channels: list[str], offset: int | None,
    user_id: uuid.UUID | None, today: date,
) -> list[PaymentReminder]:  # fmt: skip
    """Sends the reminder on each channel the client can be reached on. An automatic one (`offset` set) is never sent twice on
    a channel and is given up on after three failures; a manual one (offset None) always goes."""
    results: list[PaymentReminder] = []
    for channel in channels:
        if not (client.phone if channel == "sms" else client.email):
            continue
        row = None
        if offset is not None:
            row = (await db.execute(select(PaymentReminder).where(PaymentReminder.invoice_id == invoice.id, PaymentReminder.offset_days == offset, PaymentReminder.channel == channel))).scalar_one_or_none()
            if row is not None and (row.status == "sent" or row.attempts >= MAX_TRIES):
                continue
        recipient, problem = await _send_one(db, invoice, client, business, cfg, channel, today)
        if row is None:
            row = PaymentReminder(invoice_id=invoice.id, offset_days=offset, channel=channel, recipient=recipient, attempts=1, sent_by_user_id=user_id)
            db.add(row)
        else:
            row.attempts += 1
        row.status, row.error = ("failed", problem) if problem else ("sent", None)
        results.append(row)
        audit.record(
            db, actor_user_id=user_id, action="invoice.reminder", entity_type="invoice", entity_id=invoice.id,
            after={"channel": channel, "status": row.status, "offset_days": offset, "automatic": user_id is None},
        )  # fmt: skip
    await db.flush()
    return results


async def remind_business(db: AsyncSession, today: date | None = None) -> int:
    """The daily pass for the current business. Returns how many reminders went out."""
    today = today or nairobi_today()
    cfg = await get_settings(db)
    if not cfg.reminders_enabled or not cfg.reminder_channels:
        return 0
    business = (await db.execute(select(Business).where(Business.id == current_business_id.get()))).scalar_one()
    clients = {c.id: c for c in (await db.execute(select(Client).where(Client.reminders_enabled.is_(True)))).scalars()}
    sent = 0
    invoices = (await db.execute(select(Invoice).where(Invoice.status.in_(("issued", "partially_paid"))).order_by(Invoice.due_date))).scalars().all()
    for invoice in invoices:
        client = clients.get(invoice.client_id)
        if client is None or balance_of(invoice) <= 0:
            continue
        reachable = [ch for ch in cfg.reminder_channels if (client.phone if ch == "sms" else client.email)]
        if not reachable:
            continue
        closed: dict[int, set[str]] = {}  # per step: the channels that are finished (sent, or given up on)
        for r in (await db.execute(select(PaymentReminder).where(PaymentReminder.invoice_id == invoice.id, PaymentReminder.offset_days.is_not(None)))).scalars():
            if r.status == "sent" or r.attempts >= MAX_TRIES:
                closed.setdefault(r.offset_days, set()).add(r.channel)
        done = {step for step, channels in closed.items() if set(reachable) <= channels}
        offset = reminder_offset_due(due=invoice.due_date, today=today, offsets=cfg.reminder_offsets, sent=done)
        if offset is None:
            continue
        rows = await remind(db, invoice, client, business, cfg, channels=cfg.reminder_channels, offset=offset, user_id=None, today=today)
        sent += sum(r.status == "sent" for r in rows)
        await db.commit()  # after each invoice, so a crash never makes a client get the same reminder again
    return sent


async def run_reminders() -> int:
    """Runs across every business (daily, in the morning)."""
    total = 0
    async with get_sessionmaker()() as db:
        business_ids = (await db.execute(select(Business.id))).scalars().all()
    for business_id in business_ids:
        async with get_sessionmaker()() as db:
            current_business_id.set(business_id)
            try:
                total += await remind_business(db)
            finally:
                current_business_id.set(None)
    log.info("Sent %s payment reminders", total)
    return total


async def payment_reminders_job(ctx: dict) -> int:
    return await run_reminders()
