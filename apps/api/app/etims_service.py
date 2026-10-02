"""Sending invoices to KRA eTIMS (masterplan 5.10): every invoice is queued when it is issued, a worker sends it and
tries again with growing gaps when KRA cannot be reached, and anything KRA refuses (or that keeps failing) waits in a
review queue for a person. A voided invoice that KRA already has is cancelled with a credit note."""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.db import get_sessionmaker
from app.etims import Device, EtimsRejected, EtimsTransient, get_etims
from app.etims_rules import EtimsRuleError, build_sale, retry_delay_minutes
from app.models import Business, Client, EtimsSubmission, Invoice
from app.payment_config import get_settings
from app.tenancy import current_business_id

log = logging.getLogger(__name__)
WAITING = ("pending", "needs_review")


async def _next_invoice_no(db: AsyncSession) -> int:
    highest = max([0, *(await db.execute(select(EtimsSubmission.invoice_no))).scalars()])
    return highest + 1


async def _queue(db: AsyncSession, invoice: Invoice, kind: str) -> EtimsSubmission:
    existing = (await db.execute(select(EtimsSubmission).where(EtimsSubmission.invoice_id == invoice.id, EtimsSubmission.kind == kind))).scalar_one_or_none()
    if existing is not None:
        return existing
    for _ in range(5):
        row = EtimsSubmission(invoice_id=invoice.id, kind=kind, status="pending", invoice_no=await _next_invoice_no(db), next_attempt_at=datetime.now(UTC))
        try:
            async with db.begin_nested():
                db.add(row)
                await db.flush()
        except IntegrityError:  # another request took that number
            continue
        return row
    raise RuntimeError("Could not allocate an eTIMS invoice number")


async def queue_sale(db: AsyncSession, invoice: Invoice) -> EtimsSubmission | None:
    """Called when an invoice is issued. Does nothing unless the business has turned eTIMS on."""
    if not (await get_settings(db)).etims_enabled:
        return None
    return await _queue(db, invoice, "sale")


async def invoice_voided(db: AsyncSession, invoice: Invoice, user_id: uuid.UUID | None) -> None:
    """A voided invoice KRA already has needs a credit note; one KRA never received just stops being sent."""
    sale = (await db.execute(select(EtimsSubmission).where(EtimsSubmission.invoice_id == invoice.id, EtimsSubmission.kind == "sale"))).scalar_one_or_none()
    if sale is None:
        return
    if sale.status == "submitted":
        await _queue(db, invoice, "credit_note")
    elif sale.status in WAITING:
        sale.status, sale.next_attempt_at, sale.resolved_note = "resolved", None, "The invoice was voided before it was sent to KRA."
        audit.record(db, actor_user_id=user_id, action="etims.cancelled_before_sending", entity_type="etims_submission", entity_id=sale.id, note=sale.resolved_note)


async def connect(db: AsyncSession) -> None:
    """Checks the device with KRA and registers the service item every invoice line is sold as."""
    cfg, business = await get_settings(db), (await db.execute(select(Business).where(Business.id == current_business_id.get()))).scalar_one()
    if not business.kra_pin or not cfg.etims_device_serial:
        raise EtimsRuleError("Enter the business's KRA PIN and the eTIMS device serial number first.")
    device = Device(business.kra_pin, cfg.etims_branch_id, cfg.etims_device_serial)
    client = get_etims()
    await client.connect(device)
    await client.register_item(
        device,
        {
            "itemCd": cfg.etims_item_code, "itemClsCd": cfg.etims_item_class_code, "itemTyCd": "3", "itemNm": "Transport service", "orgnNatCd": "KE",
            "pkgUnitCd": cfg.etims_pkg_unit, "qtyUnitCd": cfg.etims_qty_unit, "taxTyCd": "B", "dftPrc": 0, "isrcAplcbYn": "N", "useYn": "Y",
            "regrId": "FleetTms", "regrNm": "FleetTms", "modrId": "FleetTms", "modrNm": "FleetTms",
        },
    )  # fmt: skip
    cfg.etims_connected_at = datetime.now(UTC)


async def submit(db: AsyncSession, sub: EtimsSubmission) -> EtimsSubmission:
    """Makes one attempt and records how it went. The caller commits."""
    now = datetime.now(UTC)
    cfg = await get_settings(db)
    business = (await db.execute(select(Business).where(Business.id == current_business_id.get()))).scalar_one()
    invoice = (await db.execute(select(Invoice).where(Invoice.id == sub.invoice_id))).scalar_one()
    client = (await db.execute(select(Client).where(Client.id == invoice.client_id))).scalar_one()
    sub.attempts += 1
    sub.last_attempt_at = now
    try:
        if not business.kra_pin or not cfg.etims_device_serial:
            raise EtimsRuleError("The business's KRA PIN or the eTIMS device serial number is missing. Add them in settings.")
        original_no = None
        if sub.kind == "credit_note":
            sale = (await db.execute(select(EtimsSubmission).where(EtimsSubmission.invoice_id == invoice.id, EtimsSubmission.kind == "sale"))).scalar_one()
            original_no = sale.invoice_no
        body = build_sale(
            tin=business.kra_pin, branch_id=cfg.etims_branch_id, invoice_no=sub.invoice_no, original_no=original_no, business_name=business.name,
            client_name=client.name, client_pin=client.kra_pin, client_phone=client.phone,
            lines=[{"description": ln.description, "amount_cents": ln.amount_cents} for ln in invoice.lines], vat_pct=float(invoice.vat_pct), vat_cents=invoice.vat_cents,
            zero_code=cfg.etims_zero_vat_code, item_code=cfg.etims_item_code, item_class_code=cfg.etims_item_class_code, pkg_unit=cfg.etims_pkg_unit,
            qty_unit=cfg.etims_qty_unit, issued_at=invoice.created_at, credit_note=sub.kind == "credit_note",
        )  # fmt: skip
        receipt = await get_etims().submit_sale(Device(business.kra_pin, cfg.etims_branch_id, cfg.etims_device_serial), body)
    except (EtimsRuleError, EtimsRejected) as e:
        sub.status, sub.next_attempt_at, sub.last_error = "needs_review", None, str(e)[:500]
    except Exception as e:
        if not isinstance(e, EtimsTransient):
            log.exception("Unexpected problem sending invoice %s to eTIMS", invoice.number)
            e = EtimsTransient("An unexpected problem on our side. It will be tried again.")
        delay = retry_delay_minutes(sub.attempts)
        if delay is None:
            sub.status, sub.next_attempt_at, sub.last_error = "needs_review", None, f"Gave up after {sub.attempts} tries. Last problem: {e}"[:500]
        else:
            sub.status, sub.next_attempt_at, sub.last_error = "pending", now + timedelta(minutes=delay), str(e)[:500]
    else:
        sub.status, sub.next_attempt_at, sub.last_error, sub.submitted_at = "submitted", None, None, now
        sub.receipt_no, sub.sdc_id, sub.sdc_time, sub.receipt_signature, sub.internal_data = receipt.receipt_no, receipt.sdc_id, receipt.sdc_time, receipt.signature, receipt.internal_data
        audit.record(db, actor_user_id=None, action="etims.submitted", entity_type="invoice", entity_id=invoice.id, after={"kind": sub.kind, "receipt_no": sub.receipt_no, "attempts": sub.attempts})
    if sub.status == "needs_review":
        audit.record(db, actor_user_id=None, action="etims.needs_review", entity_type="invoice", entity_id=invoice.id, after={"kind": sub.kind, "attempts": sub.attempts}, note=sub.last_error)
    return sub


async def submit_due(db: AsyncSession, limit: int = 50) -> int:
    """Sends everything that is due, oldest first. Returns how many were sent to KRA successfully."""
    now = datetime.now(UTC)
    rows = (
        await db.execute(
            select(EtimsSubmission).where(EtimsSubmission.status == "pending", EtimsSubmission.next_attempt_at <= now)
            .order_by(EtimsSubmission.invoice_no).limit(limit).with_for_update(skip_locked=True)
        )
    ).scalars().all()  # fmt: skip
    done = 0
    for sub in rows:
        await submit(db, sub)
        done += sub.status == "submitted"
    return done


async def run_submissions() -> int:
    """Runs across every business (every few minutes)."""
    total = 0
    async with get_sessionmaker()() as db:
        business_ids = (await db.execute(select(Business.id))).scalars().all()
    for business_id in business_ids:
        async with get_sessionmaker()() as db:
            current_business_id.set(business_id)
            try:
                total += await submit_due(db)
                await db.commit()
            finally:
                current_business_id.set(None)
    if total:
        log.info("Sent %s invoices to eTIMS", total)
    return total


async def etims_job(ctx: dict) -> int:
    return await run_submissions()
