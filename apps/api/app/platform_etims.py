"""FleetTms's own tax invoices to KRA eTIMS: a business pays for a subscription period or a text bundle, and the platform, as the seller,
sends that sale to KRA from its own device. (A business's invoices to its clients are in etims_service.py, from the business's device.)

An invoice is queued when it is paid, whichever way (M-Pesa, bank transfer marked paid, card): that is when the sale happens, and an invoice
raised and never paid is no sale and needs no credit note. A worker sends what is due, tries again with growing gaps when KRA cannot be
reached, and anything KRA refuses waits for the platform admin. Prices are VAT inclusive: the VAT is worked out from the total."""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.config import settings
from app.db import get_sessionmaker
from app.etims import Device, EtimsRejected, EtimsTransient, get_etims
from app.etims_rules import EtimsRuleError, build_sale, retry_delay_minutes
from app.models import Business, PlatformEtimsSubmission, SubscriptionInvoice
from app.plan_rules import half_up
from app.reminders import NAIROBI
from app.tenancy import current_business_id

log = logging.getLogger(__name__)
WAITING = ("pending", "needs_review")
ITEM_CODE, ITEM_CLASS, PKG_UNIT, QTY_UNIT = "KE3NTXU0000002", "81112000", "NT", "U"  # a software service, UNSPSC 81112000: data services
NOT_VAT = "D"  # the tax code when the platform is not VAT registered


def enabled() -> bool:
    return bool(settings.platform_kra_pin and settings.platform_etims_device_serial)


def device() -> Device:
    return Device(settings.platform_kra_pin, settings.platform_etims_branch_id, settings.platform_etims_device_serial)


def amounts(total_cents: int, vat_pct: float | None = None) -> tuple[int, int]:
    """(price before VAT, VAT) of a VAT-inclusive total. The two always add up to the total."""
    pct = settings.platform_vat_pct if vat_pct is None else vat_pct
    if pct <= 0:
        return total_cents, 0
    net = half_up(total_cents * 10_000, round((100 + pct) * 100))
    return net, total_cents - net


def description(invoice: SubscriptionInvoice) -> str:
    if invoice.kind == "sms_bundle":
        return f"FleetTms text messages: bundle of {invoice.sms_messages:,}"
    vehicles = (invoice.quote or {}).get("vehicles")
    start, end = invoice.period_start, invoice.period_end
    span = f", {start.astimezone(NAIROBI).date().isoformat()} to {end.astimezone(NAIROBI).date().isoformat()}" if start and end else ""
    return f"FleetTms fleet software subscription{span}" + (f" ({vehicles} vehicles)" if vehicles else "")


async def _next_invoice_no(db: AsyncSession) -> int:
    highest = max([0, *(await db.execute(select(PlatformEtimsSubmission.invoice_no))).scalars()])
    return highest + 1


async def queue(db: AsyncSession, invoice: SubscriptionInvoice) -> PlatformEtimsSubmission | None:
    """Called when the invoice is paid. Does nothing until the platform's device is configured, and never twice for one invoice."""
    if not enabled():
        return None
    existing = (await db.execute(select(PlatformEtimsSubmission).where(PlatformEtimsSubmission.subscription_invoice_id == invoice.id))).scalar_one_or_none()
    if existing is not None:
        return existing
    for _ in range(5):
        row = PlatformEtimsSubmission(business_id=invoice.business_id, subscription_invoice_id=invoice.id, invoice_no=await _next_invoice_no(db), status="pending", next_attempt_at=datetime.now(UTC))
        try:
            async with db.begin_nested():
                db.add(row)
                await db.flush()
        except IntegrityError:  # another payment took that number
            continue
        return row
    raise RuntimeError("Could not allocate an eTIMS invoice number")


async def for_invoice(db: AsyncSession, invoice_id: uuid.UUID) -> PlatformEtimsSubmission | None:
    return (await db.execute(select(PlatformEtimsSubmission).where(PlatformEtimsSubmission.subscription_invoice_id == invoice_id))).scalar_one_or_none()


async def connect() -> None:
    """Checks the platform's device with KRA and registers the service every invoice is sold as."""
    if not enabled():
        raise EtimsRuleError("Set PLATFORM_KRA_PIN and PLATFORM_ETIMS_DEVICE_SERIAL first.")
    client = get_etims()
    await client.connect(device())
    await client.register_item(
        device(),
        {
            "itemCd": ITEM_CODE, "itemClsCd": ITEM_CLASS, "itemTyCd": "3", "itemNm": "Fleet software subscription", "orgnNatCd": "KE", "pkgUnitCd": PKG_UNIT,
            "qtyUnitCd": QTY_UNIT, "taxTyCd": "B" if settings.platform_vat_pct == 16 else NOT_VAT, "dftPrc": 0, "isrcAplcbYn": "N", "useYn": "Y",
            "regrId": "FleetTms", "regrNm": "FleetTms", "modrId": "FleetTms", "modrNm": "FleetTms",
        },
    )  # fmt: skip


async def submit(db: AsyncSession, sub: PlatformEtimsSubmission) -> PlatformEtimsSubmission:
    """Makes one attempt and records how it went. The caller commits."""
    now = datetime.now(UTC)
    invoice = (await db.execute(select(SubscriptionInvoice).where(SubscriptionInvoice.id == sub.subscription_invoice_id).execution_options(skip_tenant=True))).scalar_one()
    business = (await db.execute(select(Business).where(Business.id == sub.business_id).execution_options(skip_tenant=True))).scalar_one()
    sub.attempts += 1
    sub.last_attempt_at = now
    try:
        if not enabled():
            raise EtimsRuleError("The platform's KRA PIN or eTIMS device serial number is not set.")
        net, vat = amounts(invoice.total_cents)
        body = build_sale(
            tin=settings.platform_kra_pin, branch_id=settings.platform_etims_branch_id, invoice_no=sub.invoice_no, original_no=None, business_name="FleetTms",
            client_name=business.name, client_pin=business.kra_pin, client_phone=None, lines=[{"description": description(invoice), "amount_cents": net}],
            vat_pct=settings.platform_vat_pct, vat_cents=vat, zero_code=NOT_VAT, item_code=ITEM_CODE, item_class_code=ITEM_CLASS, pkg_unit=PKG_UNIT,
            qty_unit=QTY_UNIT, issued_at=invoice.paid_at or invoice.created_at, credit_note=False,
        )  # fmt: skip
        receipt = await get_etims().submit_sale(device(), body)
    except (EtimsRuleError, EtimsRejected) as e:
        sub.status, sub.next_attempt_at, sub.last_error = "needs_review", None, str(e)[:500]
    except Exception as e:
        if not isinstance(e, EtimsTransient):
            log.exception("Unexpected problem sending platform invoice %s to eTIMS", invoice.number)
            e = EtimsTransient("An unexpected problem on our side. It will be tried again.")
        delay = retry_delay_minutes(sub.attempts)
        if delay is None:
            sub.status, sub.next_attempt_at, sub.last_error = "needs_review", None, f"Gave up after {sub.attempts} tries. Last problem: {e}"[:500]
        else:
            sub.status, sub.next_attempt_at, sub.last_error = "pending", now + timedelta(minutes=delay), str(e)[:500]
    else:
        sub.status, sub.next_attempt_at, sub.last_error, sub.submitted_at = "submitted", None, None, now
        sub.receipt_no, sub.sdc_id, sub.sdc_time, sub.receipt_signature, sub.internal_data = receipt.receipt_no, receipt.sdc_id, receipt.sdc_time, receipt.signature, receipt.internal_data
        current_business_id.set(sub.business_id)  # the entry goes in the paying business's own trail, so its owner sees its tax invoice was filed
        audit.record(db, actor_user_id=None, action="platform_etims.submitted", entity_type="subscription_invoice", entity_id=invoice.id, after={"receipt_no": sub.receipt_no, "attempts": sub.attempts})
        await db.flush()
    if sub.status == "needs_review":
        log.warning("Platform invoice %s needs review: %s", invoice.number, sub.last_error)
    return sub


async def submit_due(db: AsyncSession, limit: int = 50) -> int:
    """Sends everything that is due, oldest first. Returns how many KRA accepted."""
    rows = (
        await db.execute(
            select(PlatformEtimsSubmission).where(PlatformEtimsSubmission.status == "pending", PlatformEtimsSubmission.next_attempt_at <= datetime.now(UTC))
            .order_by(PlatformEtimsSubmission.invoice_no).limit(limit).with_for_update(skip_locked=True)
        )
    ).scalars().all()  # fmt: skip
    done = 0
    for sub in rows:
        await submit(db, sub)
        done += sub.status == "submitted"
    return done


async def run_submissions() -> int:
    """Runs across the whole platform (every few minutes)."""
    if not enabled():
        return 0
    async with get_sessionmaker()() as db:
        try:
            total = await submit_due(db)
            await db.commit()
        finally:
            current_business_id.set(None)
    if total:
        log.info("Sent %s platform invoices to eTIMS", total)
    return total


async def platform_etims_job(ctx: dict) -> int:
    return await run_submissions()
