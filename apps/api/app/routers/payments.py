"""Client payments by M-Pesa (masterplan 5.10): the Safaricom callbacks, the queue of payments that could not be matched,
and the business's payment settings."""

import logging
import re
import secrets
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, daraja, ratelimit
from app.config import settings as app_settings
from app.db import get_db
from app.deps import Principal, error, require, require_any
from app.models import Business, Invoice, MpesaTransaction, PaymentSettings
from app.payment_config import get_settings
from app.payments import (
    REASONS,
    PaymentError,
    allocate,
    parse_amount_cents,
    parse_trans_time,
    record_payment,
    suggestions,
)
from app.tenancy import current_business_id

log = logging.getLogger(__name__)
router = APIRouter(tags=["payments"])
MANAGE = ("invoices.manage",)
KRA_PIN = re.compile(r"^[AP]\d{9}[A-Z]$")
ACCEPTED = {"ResultCode": 0, "ResultDesc": "Accepted"}


class MatchIn(BaseModel):
    invoice_id: uuid.UUID
    amount_cents: int | None = Field(default=None, gt=0, le=10_000_000_000)  # default: as much as the invoice owes, or the payment has left


class DismissIn(BaseModel):
    reason: str = Field(min_length=3, max_length=255)


class SettingsIn(BaseModel):
    shortcode: str | None = Field(default=None, pattern=r"^\d{5,10}$")
    shortcode_type: Literal["paybill", "till"] = "paybill"
    reminders_enabled: bool = False
    reminder_offsets: list[int] = Field(default_factory=lambda: [-3, 1, 7, 14, 30], max_length=8)
    reminder_channels: list[Literal["sms", "email"]] = Field(default_factory=lambda: ["sms", "email"])
    etims_enabled: bool = False
    etims_branch_id: str = Field(default="00", pattern=r"^\d{2}$")
    etims_device_serial: str | None = Field(default=None, max_length=100)
    etims_zero_vat_code: Literal["A", "C", "D"] = "A"
    etims_item_code: str = Field(default="KE3NTXU0000001", min_length=5, max_length=20)
    etims_item_class_code: str = Field(default="78101800", min_length=4, max_length=10)
    etims_pkg_unit: str = Field(default="NT", min_length=1, max_length=5)
    etims_qty_unit: str = Field(default="U", min_length=1, max_length=5)
    kra_pin: str | None = Field(default=None, max_length=11)


class SimulateIn(BaseModel):
    amount_cents: int = Field(gt=0, le=10_000_000_00)
    bill_ref: str = Field(max_length=60)


def settings_out(s: PaymentSettings, business: Business, *, secret: bool) -> dict:
    from app import etims

    out = {
        "shortcode": s.shortcode, "shortcode_type": s.shortcode_type, "urls_registered_at": s.urls_registered_at, "daraja_live": daraja.is_live(),
        "reminders_enabled": s.reminders_enabled, "reminder_offsets": sorted(s.reminder_offsets), "reminder_channels": s.reminder_channels,
        "etims_enabled": s.etims_enabled, "etims_branch_id": s.etims_branch_id, "etims_device_serial": s.etims_device_serial,
        "etims_zero_vat_code": s.etims_zero_vat_code, "etims_item_code": s.etims_item_code, "etims_item_class_code": s.etims_item_class_code,
        "etims_pkg_unit": s.etims_pkg_unit, "etims_qty_unit": s.etims_qty_unit, "etims_connected_at": s.etims_connected_at,
        "etims_live": etims.is_live(), "kra_pin": business.kra_pin, "can_simulate": can_simulate(),
    }  # fmt: skip
    if secret and s.shortcode:
        out["confirmation_url"], out["validation_url"] = daraja.callback_urls(business.id)
    return out


def can_simulate() -> bool:
    return (not daraja.is_live() and app_settings.environment == "development") or (daraja.is_live() and app_settings.daraja_env == "sandbox")


def txn_out(t: MpesaTransaction, invoices: list[Invoice] | None = None) -> dict:
    out = {
        "id": t.id, "trans_id": t.trans_id, "amount_cents": t.amount_cents, "allocated_cents": t.allocated_cents, "left_cents": t.amount_cents - t.allocated_cents,
        "bill_ref": t.bill_ref, "payer_name": t.payer_name, "paid_at": t.paid_at, "source": t.source, "status": t.status, "reason": t.reason,
        "reason_text": REASONS.get(t.reason or ""), "dismissed_reason": t.dismissed_reason,
    }  # fmt: skip
    if invoices is not None:
        out["suggestions"] = [{"id": i.id, "number": i.number, "balance_cents": i.total_cents - sum(p.amount_cents for p in i.payments)} for i in invoices]
    return out


# ---- Safaricom's calls (no sign-in: the address itself carries the secret) -----------------------------------------


async def _business_for_hook(db: AsyncSession, business_id: uuid.UUID, key: str) -> Business:
    business = (await db.execute(select(Business).where(Business.id == business_id))).scalar_one_or_none()
    if business is None or not daraja.key_matches(business_id, key):
        raise error(status.HTTP_403_FORBIDDEN, "forbidden", "Not allowed.")
    current_business_id.set(business_id)
    return business


@router.post("/hooks/c2b/{business_id}/{key}/validation", dependencies=[Depends(ratelimit.hook_guard)])
async def c2b_validation(business_id: uuid.UUID, key: str, db: AsyncSession = Depends(get_db)):
    """Safaricom asks whether to accept a payment. We always accept: an odd account number goes to the office's queue
    rather than bouncing the client's money."""
    await _business_for_hook(db, business_id, key)
    return ACCEPTED


@router.post("/hooks/c2b/{business_id}/{key}/confirmation", dependencies=[Depends(ratelimit.hook_guard)])
async def c2b_confirmation(business_id: uuid.UUID, key: str, request: Request, db: AsyncSession = Depends(get_db)):
    await _business_for_hook(db, business_id, key)
    try:
        body = await request.json()
        trans_id, amount = str(body["TransID"]), body["TransAmount"]
    except (ValueError, KeyError, TypeError):
        raise error(422, "bad_payload", "That is not a payment notice.") from None
    config = await get_settings(db)
    shortcode = str(body.get("BusinessShortCode") or "") or None
    if config.shortcode and shortcode and shortcode != config.shortcode:
        raise error(status.HTTP_403_FORBIDDEN, "wrong_shortcode", "That payment was not made to this business.")
    try:
        await record_payment(
            db, trans_id=trans_id, amount_cents=parse_amount_cents(amount), bill_ref=body.get("BillRefNumber"),
            payer_name=" ".join(p for p in (str(body.get(k) or "").strip() for k in ("FirstName", "MiddleName", "LastName")) if p) or None,
            payer_phone=body.get("MSISDN"), shortcode=shortcode, paid_at=parse_trans_time(body.get("TransTime")), source="daraja",
        )  # fmt: skip
    except PaymentError as e:
        raise error(422, e.code, e.message) from None
    await db.commit()
    return ACCEPTED


# ---- the office's view -----------------------------------------------------------------------------------------------


@router.get("/payments/mpesa")
async def list_payments(status_filter: str | None = None, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    query = select(MpesaTransaction).order_by(MpesaTransaction.paid_at.desc()).limit(300)
    if status_filter == "needs_attention":
        query = query.where(MpesaTransaction.status.in_(("unmatched", "partly_matched")))
    elif status_filter:
        query = query.where(MpesaTransaction.status == status_filter)
    return [txn_out(t) for t in (await db.execute(query)).scalars()]


async def _txn(db: AsyncSession, txn_id: uuid.UUID) -> MpesaTransaction:
    txn = (await db.execute(select(MpesaTransaction).where(MpesaTransaction.id == txn_id).with_for_update())).scalar_one_or_none()
    if txn is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That payment was not found.")
    return txn


@router.get("/payments/mpesa/{txn_id}")
async def read_payment(txn_id: uuid.UUID, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    txn = await _txn(db, txn_id)
    return txn_out(txn, await suggestions(db, txn) if txn.status in ("unmatched", "partly_matched") else [])


@router.post("/payments/mpesa/{txn_id}/match")
async def match_payment(txn_id: uuid.UUID, body: MatchIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    """A person puts a payment (or part of it) against an invoice."""
    txn = await _txn(db, txn_id)
    invoice = (await db.execute(select(Invoice).where(Invoice.id == body.invoice_id))).scalar_one_or_none()
    if invoice is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That invoice was not found.")
    owed = invoice.total_cents - sum(p.amount_cents for p in invoice.payments)
    cents = body.amount_cents or min(owed, txn.amount_cents - txn.allocated_cents)
    try:
        await allocate(db, txn, invoice.id, cents, principal.user.id)
    except PaymentError as e:
        raise error(422 if e.code != "not_found" else 404, e.code, e.message) from None
    await db.commit()
    return txn_out(txn, [])


@router.post("/payments/mpesa/{txn_id}/dismiss")
async def dismiss_payment(txn_id: uuid.UUID, body: DismissIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    """Sets a payment aside with a reason (for example: refunded, or not for us). It stays on record."""
    txn = await _txn(db, txn_id)
    if txn.status == "matched":
        raise error(status.HTTP_409_CONFLICT, "already_matched", "That payment is already fully matched.")
    txn.status, txn.dismissed_reason = "dismissed", body.reason
    audit.record(db, actor_user_id=principal.user.id, action="mpesa.payment_dismissed", entity_type="mpesa_transaction", entity_id=txn.id, after={"trans_id": txn.trans_id, "left_cents": txn.amount_cents - txn.allocated_cents}, note=body.reason)
    await db.commit()
    return txn_out(txn)


# ---- settings -----------------------------------------------------------------------------------------------------


@router.get("/payments/settings")
async def read_settings(principal: Principal = Depends(require_any(*MANAGE, "business.manage")), db: AsyncSession = Depends(get_db)):
    business = (await db.execute(select(Business).where(Business.id == principal.business_id))).scalar_one()
    out = settings_out(await get_settings(db), business, secret="business.manage" in principal.permissions)
    await db.commit()  # the row may have just been created
    return out


@router.put("/payments/settings")
async def save_settings(body: SettingsIn, principal: Principal = Depends(require("business.manage")), db: AsyncSession = Depends(get_db)):
    s = await get_settings(db)
    business = (await db.execute(select(Business).where(Business.id == principal.business_id))).scalar_one()
    if body.reminders_enabled and not body.reminder_channels:
        raise error(422, "no_channel", "Choose how reminders are sent: SMS, email or both.")
    if any(o < -30 or o > 180 for o in body.reminder_offsets):
        raise error(422, "bad_offsets", "Reminders can go from 30 days before the due date to 180 days after it.")
    pin = (body.kra_pin or "").strip().upper() or None
    if pin and not KRA_PIN.match(pin):
        raise error(422, "invalid_kra_pin", "A KRA PIN is a letter, nine digits and a letter, like A012345678Z.")
    if body.etims_enabled and not (pin or business.kra_pin):
        raise error(422, "kra_pin_required", "Enter the business's KRA PIN to turn on eTIMS.")
    if body.etims_enabled and not body.etims_device_serial:
        raise error(422, "device_serial_required", "Enter the eTIMS device serial number KRA gave you.")
    before = {"shortcode": s.shortcode, "reminders_enabled": s.reminders_enabled, "etims_enabled": s.etims_enabled, "kra_pin": business.kra_pin}
    if body.shortcode != s.shortcode:
        s.urls_registered_at = None  # the new number has to be registered with Safaricom
    if (body.etims_branch_id, body.etims_device_serial) != (s.etims_branch_id, s.etims_device_serial):
        s.etims_connected_at = None
    s.shortcode, s.shortcode_type = body.shortcode, body.shortcode_type
    s.reminders_enabled, s.reminder_offsets, s.reminder_channels = body.reminders_enabled, sorted(set(body.reminder_offsets)), list(dict.fromkeys(body.reminder_channels))
    s.etims_enabled, s.etims_branch_id, s.etims_device_serial = body.etims_enabled, body.etims_branch_id, body.etims_device_serial
    s.etims_zero_vat_code, s.etims_item_code, s.etims_item_class_code = body.etims_zero_vat_code, body.etims_item_code, body.etims_item_class_code
    s.etims_pkg_unit, s.etims_qty_unit = body.etims_pkg_unit, body.etims_qty_unit
    if pin:
        business.kra_pin = pin
    audit.record(
        db, actor_user_id=principal.user.id, action="payment_settings.changed", entity_type="payment_settings", entity_id=s.id, before=before,
        after={"shortcode": s.shortcode, "reminders_enabled": s.reminders_enabled, "etims_enabled": s.etims_enabled, "kra_pin": business.kra_pin},
    )  # fmt: skip
    await db.commit()
    return settings_out(s, business, secret=True)


@router.post("/payments/settings/register-urls")
async def register_urls(principal: Principal = Depends(require("business.manage")), db: AsyncSession = Depends(get_db)):
    """Tells Safaricom where to send this business's payments."""
    s = await get_settings(db)
    if not s.shortcode:
        raise error(422, "no_shortcode", "Enter the Paybill or Till number first.")
    confirmation, validation = daraja.callback_urls(principal.business_id)
    if daraja.is_live() and not app_settings.public_api_url:
        raise error(422, "no_public_url", "Set PUBLIC_API_URL to the address Safaricom can reach, then try again.")
    try:
        await daraja.get_daraja().register_urls(s.shortcode, confirmation, validation)
    except daraja.DarajaError as e:
        raise error(502, "daraja_failed", str(e)) from None
    s.urls_registered_at = datetime.now(UTC)
    audit.record(db, actor_user_id=principal.user.id, action="payment_settings.urls_registered", entity_type="payment_settings", entity_id=s.id, after={"shortcode": s.shortcode})
    await db.commit()
    return {"registered_at": s.urls_registered_at}


@router.post("/payments/simulate", status_code=status.HTTP_201_CREATED)
async def simulate_payment(body: SimulateIn, principal: Principal = Depends(require("business.manage")), db: AsyncSession = Depends(get_db)):
    """Development and the Safaricom sandbox only: makes a client payment so the whole path can be watched working."""
    if not can_simulate():
        raise error(status.HTTP_403_FORBIDDEN, "not_allowed", "Payments can only be simulated in development or the Safaricom sandbox.")
    s = await get_settings(db)
    if not s.shortcode:
        raise error(422, "no_shortcode", "Enter the Paybill or Till number first.")
    if daraja.is_live():
        try:
            await daraja.get_daraja().simulate(s.shortcode, body.amount_cents // 100, body.bill_ref, "254708374149")
        except daraja.DarajaError as e:
            raise error(502, "daraja_failed", str(e)) from None
        await db.commit()
        return {"sent_to_safaricom": True}
    txn, _ = await record_payment(
        db, trans_id="SIM" + "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(7)), amount_cents=body.amount_cents, bill_ref=body.bill_ref,
        payer_name="Simulated Client", payer_phone=None, shortcode=s.shortcode, paid_at=datetime.now(UTC), source="simulated",
    )  # fmt: skip
    await db.commit()
    return txn_out(txn)
