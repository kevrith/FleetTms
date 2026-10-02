"""KRA eTIMS (masterplan 5.10): the status of every invoice sent to KRA, and the queue of ones a person must look at."""

import uuid

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, etims_service
from app.db import get_db
from app.deps import Principal, error, require, require_any
from app.etims import EtimsRejected, EtimsTransient
from app.etims_rules import EtimsRuleError
from app.models import Client, EtimsSubmission, Invoice
from app.payment_config import get_settings

router = APIRouter(tags=["etims"])
MANAGE = ("invoices.manage",)
LABELS = {"pending": "Waiting to send", "submitted": "Sent to KRA", "needs_review": "Needs a person", "resolved": "Handled by hand"}


class ResolveIn(BaseModel):
    note: str = Field(min_length=3, max_length=255)
    receipt_no: str | None = Field(default=None, max_length=40)


def submission_out(s: EtimsSubmission, invoice: Invoice | None = None, client: Client | None = None) -> dict:
    return {
        "id": s.id, "invoice_id": s.invoice_id, "invoice_number": invoice.number if invoice else None, "client_name": client.name if client else None,
        "total_cents": invoice.total_cents if invoice else None, "kind": s.kind, "status": s.status, "status_text": LABELS[s.status], "invoice_no": s.invoice_no,
        "attempts": s.attempts, "next_attempt_at": s.next_attempt_at, "last_attempt_at": s.last_attempt_at, "last_error": s.last_error, "receipt_no": s.receipt_no,
        "sdc_id": s.sdc_id, "submitted_at": s.submitted_at, "resolved_note": s.resolved_note,
    }  # fmt: skip


async def _get(db: AsyncSession, sub_id: uuid.UUID) -> EtimsSubmission:
    sub = (await db.execute(select(EtimsSubmission).where(EtimsSubmission.id == sub_id).with_for_update())).scalar_one_or_none()
    if sub is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That submission was not found.")
    return sub


async def _out(db: AsyncSession, sub: EtimsSubmission) -> dict:
    invoice = (await db.execute(select(Invoice).where(Invoice.id == sub.invoice_id))).scalar_one()
    client = (await db.execute(select(Client).where(Client.id == invoice.client_id))).scalar_one()
    return submission_out(sub, invoice, client)


@router.get("/etims/submissions")
async def list_submissions(status_filter: str | None = None, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    query = select(EtimsSubmission).order_by(EtimsSubmission.created_at.desc()).limit(300)
    if status_filter == "attention":
        query = query.where(EtimsSubmission.status.in_(("needs_review",)))
    elif status_filter:
        query = query.where(EtimsSubmission.status == status_filter)
    invoices = {i.id: i for i in (await db.execute(select(Invoice))).scalars()}
    clients = {c.id: c for c in (await db.execute(select(Client))).scalars()}
    return [submission_out(s, invoices.get(s.invoice_id), clients.get(invoices[s.invoice_id].client_id) if s.invoice_id in invoices else None) for s in (await db.execute(query)).scalars()]


@router.get("/etims/summary")
async def summary(principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    counts = dict((await db.execute(select(EtimsSubmission.status, func.count()).group_by(EtimsSubmission.status))).all())
    cfg = await get_settings(db)
    await db.commit()
    return {"enabled": cfg.etims_enabled, "connected_at": cfg.etims_connected_at, **{k: int(counts.get(k, 0)) for k in LABELS}}


@router.post("/etims/connect")
async def connect_device(principal: Principal = Depends(require("business.manage")), db: AsyncSession = Depends(get_db)):
    """Checks the device with KRA and registers the service every invoice line is sold as."""
    try:
        await etims_service.connect(db)
    except EtimsRuleError as e:
        raise error(422, "etims_setup", str(e)) from None
    except EtimsRejected as e:
        raise error(422, "etims_refused", f"KRA refused the device: {e}") from None
    except EtimsTransient as e:
        raise error(502, "etims_unreachable", str(e)) from None
    cfg = await get_settings(db)
    audit.record(db, actor_user_id=principal.user.id, action="etims.connected", entity_type="payment_settings", entity_id=cfg.id)
    await db.commit()
    return {"connected_at": cfg.etims_connected_at}


@router.post("/etims/submissions/{sub_id}/retry")
async def retry(sub_id: uuid.UUID, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    """Tries again now (after fixing what KRA complained about, or to skip the wait)."""
    sub = await _get(db, sub_id)
    if sub.status in ("submitted", "resolved"):
        raise error(status.HTTP_409_CONFLICT, "done", "That invoice is already dealt with.")
    if sub.status == "needs_review":
        sub.attempts = 0
    await etims_service.submit(db, sub)
    audit.record(db, actor_user_id=principal.user.id, action="etims.retried", entity_type="etims_submission", entity_id=sub.id, after={"status": sub.status})
    await db.commit()
    return await _out(db, sub)


@router.post("/etims/submissions/{sub_id}/resolve")
async def resolve(sub_id: uuid.UUID, body: ResolveIn, principal: Principal = Depends(require_any(*MANAGE)), db: AsyncSession = Depends(get_db)):
    """The invoice was dealt with outside FleetTms (for example entered on the KRA portal). Say how, and optionally keep the receipt number."""
    sub = await _get(db, sub_id)
    if sub.status in ("submitted", "resolved"):
        raise error(status.HTTP_409_CONFLICT, "done", "That invoice is already dealt with.")
    sub.status, sub.next_attempt_at, sub.resolved_note, sub.receipt_no = "resolved", None, body.note, body.receipt_no or sub.receipt_no
    audit.record(db, actor_user_id=principal.user.id, action="etims.resolved_by_hand", entity_type="etims_submission", entity_id=sub.id, after={"receipt_no": sub.receipt_no}, note=body.note)
    await db.commit()
    return await _out(db, sub)
