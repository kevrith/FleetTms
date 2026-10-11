"""Renewals with proof (masterplan 5.1): a driver sends the new expiry date of their licence with the NTSA digital licence or the payment
receipt; a manager sends an insurance renewal with the insurer's certificate. A manager or the owner looks at the proof and approves, and only
then does the record change, so a date typed to get past the block means nothing. Rules in app/renewal_rules.py."""

import uuid
from datetime import UTC, date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, push, renewal_check, renewal_rules
from app.db import get_db
from app.deps import Principal, error, require, require_any
from app.models import (
    ComplianceDocType,
    ComplianceDocument,
    Membership,
    MembershipStatus,
    Photo,
    PhotoKind,
    RenewalRequest,
    Role,
    User,
    Vehicle,
)
from app.photos import photo_out
from app.reminders import LABELS, nairobi_today
from app.routers.documents import FIELDS
from app.routers.vehicles import get_vehicle
from app.sms import get_sms_sender

router = APIRouter(tags=["renewals"])
DRIVER_DOCS = ("driving_licence",)


class RenewalIn(BaseModel):
    doc_type: Literal["driving_licence", "insurance", "inspection", "ntsa_licence", "tlb_licence", "permit"]
    vehicle_id: uuid.UUID | None = None
    membership_id: uuid.UUID | None = None
    new_expires_on: date
    proof_kind: Literal["digital_licence", "receipt", "certificate"]
    reference: str | None = Field(default=None, max_length=80)  # the receipt number, policy number or similar
    photo_id: uuid.UUID | None = None
    photo_client_id: uuid.UUID | None = None  # the id the phone gave the file when it queued it offline

    @model_validator(mode="after")
    def _one_subject(self):
        if (self.photo_id is None) == (self.photo_client_id is None):
            raise ValueError("Name the proof by one id.")
        if self.doc_type in DRIVER_DOCS:  # no person named means the sender's own licence
            if self.vehicle_id is not None:
                raise ValueError("A driving licence belongs to a person.")
        elif self.vehicle_id is None or self.membership_id is not None:
            raise ValueError("That document belongs to a vehicle.")
        return self


class ApproveIn(BaseModel):
    expires_on: date | None = None  # a date corrected after looking at the proof
    note: str | None = Field(default=None, max_length=200)


class RejectIn(BaseModel):
    note: str = Field(min_length=3, max_length=200)


async def _current_expiry(db: AsyncSession, r: RenewalRequest | RenewalIn) -> ComplianceDocument | None:
    query = select(ComplianceDocument).where(ComplianceDocument.doc_type == ComplianceDocType(r.doc_type)).order_by(ComplianceDocument.expires_on.desc()).limit(1)
    query = query.where(ComplianceDocument.vehicle_id == r.vehicle_id) if r.vehicle_id else query.where(ComplianceDocument.membership_id == r.membership_id)
    return (await db.execute(query)).scalar_one_or_none()


async def _tell(users: list[User], title: str, body: str, data: dict) -> None:
    sms = get_sms_sender()
    for phone in sorted({u.phone for u in users if u.phone}):
        await sms.send(phone, f"FleetTms: {title}. {body}")
    await push.send(sorted({u.push_token for u in users if u.push_token}), title, body, data)


async def _approvers(db: AsyncSession) -> list[User]:
    return [m.user for m in (await db.execute(select(Membership))).scalars() if m.status == MembershipStatus.ACTIVE and {r.role for r in m.roles} & {Role.OWNER, Role.MANAGER}]


async def _out(db: AsyncSession, r: RenewalRequest) -> dict:
    vehicle = (await db.execute(select(Vehicle).where(Vehicle.id == r.vehicle_id))).scalar_one_or_none() if r.vehicle_id else None
    member = (await db.execute(select(Membership).where(Membership.id == r.membership_id))).scalar_one_or_none() if r.membership_id else None
    photo = (await db.execute(select(Photo).where(Photo.id == r.photo_id))).scalar_one_or_none() if r.photo_id else None
    submitter = (await db.execute(select(User).where(User.id == r.submitted_by_user_id))).scalar_one_or_none() if r.submitted_by_user_id else None
    current = await _current_expiry(db, r)
    return {
        "id": r.id, "doc_type": r.doc_type, "label": LABELS.get(r.doc_type, r.doc_type), "vehicle_id": r.vehicle_id, "membership_id": r.membership_id,
        "subject": vehicle.registration if vehicle else (member.user.name if member else "Former staff"),
        "new_expires_on": r.new_expires_on, "current_expires_on": current.expires_on if current else None, "proof_kind": r.proof_kind, "reference": r.reference,
        "proof": {**photo_out(photo), "is_pdf": photo.content_type == "application/pdf"} if photo else None, "status": r.status,
        "submitted_by": submitter.name if submitter else None, "submitted_at": r.submitted_at, "decided_at": r.decided_at, "decision_note": r.decision_note, "proof_check": r.proof_check,
    }  # fmt: skip


async def do_submit_renewal(db: AsyncSession, principal: Principal, body: RenewalIn) -> RenewalRequest:
    """Sends a renewal with its proof. The proof is a file already uploaded as a document photo by the sender. The owner's own renewal is
    approved at once (the proof is still kept); anyone else's waits for a manager or the owner. The caller commits, then calls `announce`."""
    if body.membership_id is None and body.doc_type in DRIVER_DOCS:
        body.membership_id = principal.membership_id  # a driver's phone does not need to know its own membership id
    if body.membership_id is not None:
        own = principal.membership_id == body.membership_id and "trips.own" in principal.permissions
        if not own and "staff.manage" not in principal.permissions:
            raise error(status.HTTP_403_FORBIDDEN, "forbidden", "You can only send a renewal for your own licence.")
        member = (await db.execute(select(Membership).where(Membership.id == body.membership_id))).scalar_one_or_none()
        if member is None:
            raise error(status.HTTP_404_NOT_FOUND, "not_found", "That person was not found.")
    else:
        if "vehicles.manage" not in principal.permissions:
            raise error(status.HTTP_403_FORBIDDEN, "forbidden", "You do not have permission to do that.")
        await get_vehicle(db, principal, body.vehicle_id)
    column = Photo.id if body.photo_id is not None else Photo.client_id
    photo = (await db.execute(select(Photo).where(column == (body.photo_id or body.photo_client_id)))).scalar_one_or_none()
    if photo is None or photo.kind != PhotoKind.DOCUMENT or photo.uploaded_by_user_id != principal.user.id:
        raise error(422, "photo_invalid", "Upload the proof first, then send the renewal.")
    pending = (await db.execute(select(RenewalRequest.id).where(RenewalRequest.status == "pending", RenewalRequest.doc_type == body.doc_type, RenewalRequest.vehicle_id == body.vehicle_id, RenewalRequest.membership_id == body.membership_id))).first()
    if pending is not None:
        raise error(status.HTTP_409_CONFLICT, "already_pending", "A renewal for this is already waiting to be approved.")
    current = await _current_expiry(db, body)
    why = renewal_rules.problem(doc_type=body.doc_type, proof_kind=body.proof_kind, new_expires_on=body.new_expires_on, current_expires_on=current.expires_on if current else None, today=nairobi_today())
    if why:
        raise error(422, "renewal_invalid", why)
    r = RenewalRequest(
        doc_type=body.doc_type, vehicle_id=body.vehicle_id, membership_id=body.membership_id, new_expires_on=body.new_expires_on, proof_kind=body.proof_kind,
        reference=body.reference, photo_id=photo.id, submitted_by_user_id=principal.user.id,
    )  # fmt: skip
    db.add(r)
    await db.flush()
    audit.record(db, actor_user_id=principal.user.id, action="renewal.submitted", entity_type="renewal", entity_id=r.id, after={"doc_type": r.doc_type, "new_expires_on": r.new_expires_on.isoformat(), "proof": r.proof_kind})
    if Role.OWNER in principal.roles:
        await _apply(db, r, principal, r.new_expires_on, None)
    return r


async def announce(db: AsyncSession, r: RenewalRequest) -> None:
    """Tells the owner and managers there is something to approve. Called after the renewal is saved."""
    if r.status != "pending":
        return
    out = await _out(db, r)
    await _tell(await _approvers(db), f"{out['label']} renewal for {out['subject']} to approve", f"New date {r.new_expires_on.isoformat()}. Check the proof, then approve it in the app.", {"type": "renewal", "renewal_id": str(r.id)})


@router.post("/renewals", status_code=status.HTTP_201_CREATED)
async def submit(body: RenewalIn, principal: Principal = Depends(require_any("trips.own", "vehicles.manage", "staff.manage")), db: AsyncSession = Depends(get_db)):
    r = await do_submit_renewal(db, principal, body)
    await db.commit()
    if r.status == "pending":
        try:
            await renewal_check.run(db, r)  # best effort: the approver can ask again from the queue
            await db.commit()
        except Exception:  # noqa: BLE001 - a reading that fails must never lose the renewal that was just saved
            await db.rollback()
    await announce(db, r)
    return await _out(db, r)


@router.post("/renewals/{renewal_id}/check")
async def check_proof(renewal_id: uuid.UUID, again: bool = False, principal: Principal = Depends(require("documents.approve")), db: AsyncSession = Depends(get_db)):
    """Reads the proof and compares it with what was typed, if that has not been done (or `again`). The answer is for the approver to weigh;
    it never approves or turns anything down. Without a reading service the renewal comes back with no check."""
    r = (await db.execute(select(RenewalRequest).where(RenewalRequest.id == renewal_id))).scalar_one_or_none()
    if r is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That renewal was not found.")
    await renewal_check.run(db, r, again=again)
    await db.commit()
    return await _out(db, r)


async def _apply(db: AsyncSession, r: RenewalRequest, principal: Principal, expires_on: date, note: str | None) -> None:
    """Puts the approved date on the record, or makes the record if there was none, and says so in the audit trail."""
    doc = await _current_expiry(db, r)
    if doc is None:
        doc = ComplianceDocument(doc_type=ComplianceDocType(r.doc_type), vehicle_id=r.vehicle_id, membership_id=r.membership_id, expires_on=expires_on, reference=r.reference)
        db.add(doc)
        await db.flush()
        audit.record(db, actor_user_id=principal.user.id, action="document.created", entity_type="document", entity_id=doc.id, after=audit.snapshot(doc, FIELDS), note=f"renewal {r.id}")
    else:
        before = audit.snapshot(doc, FIELDS)
        doc.expires_on = expires_on
        if r.reference:
            doc.reference = r.reference
        audit.record(db, actor_user_id=principal.user.id, action="document.updated", entity_type="document", entity_id=doc.id, before=before, after=audit.snapshot(doc, FIELDS), note=f"renewal {r.id}")
    r.status, r.decided_by_user_id, r.decided_at, r.decision_note, r.document_id = "approved", principal.user.id, datetime.now(UTC), note, doc.id
    r.new_expires_on = expires_on
    audit.record(db, actor_user_id=principal.user.id, action="renewal.approved", entity_type="renewal", entity_id=r.id, after={"expires_on": expires_on.isoformat()}, note=note)


async def _pending(db: AsyncSession, renewal_id: uuid.UUID) -> RenewalRequest:
    r = (await db.execute(select(RenewalRequest).where(RenewalRequest.id == renewal_id))).scalar_one_or_none()
    if r is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That renewal was not found.")
    if r.status != "pending":
        raise error(status.HTTP_409_CONFLICT, "already_decided", "That renewal has already been decided.")
    return r


async def _tell_submitter(db: AsyncSession, r: RenewalRequest, title: str, body: str) -> None:
    submitter = (await db.execute(select(User).where(User.id == r.submitted_by_user_id))).scalar_one_or_none() if r.submitted_by_user_id else None
    if submitter is not None:
        await _tell([submitter], title, body, {"type": "renewal", "renewal_id": str(r.id)})


@router.get("/renewals")
async def list_renewals(
    status_: Literal["pending", "approved", "rejected", "all"] = Query(default="pending", alias="status"), principal: Principal = Depends(require_any("documents.approve", "trips.own")), db: AsyncSession = Depends(get_db)
):  # fmt: skip
    """Renewals waiting for approval (or the others), newest first. Someone who cannot approve sees only what they sent themselves."""
    query = select(RenewalRequest).order_by(RenewalRequest.submitted_at.desc()).limit(200)
    if status_ != "all":
        query = query.where(RenewalRequest.status == status_)
    if "documents.approve" not in principal.permissions:
        query = query.where(RenewalRequest.submitted_by_user_id == principal.user.id)
    return [await _out(db, r) for r in (await db.execute(query)).scalars()]


@router.post("/renewals/{renewal_id}/approve")
async def approve(renewal_id: uuid.UUID, body: ApproveIn, principal: Principal = Depends(require("documents.approve")), db: AsyncSession = Depends(get_db)):
    """The proof has been looked at and the date is right: the record changes and the sender is told. Nobody but the owner approves their own."""
    r = await _pending(db, renewal_id)
    if r.submitted_by_user_id == principal.user.id and Role.OWNER not in principal.roles:
        raise error(status.HTTP_403_FORBIDDEN, "own_renewal", "Someone else must approve a renewal you sent.")
    expires_on = body.expires_on or r.new_expires_on
    current = await _current_expiry(db, r)
    why = renewal_rules.problem(doc_type=r.doc_type, proof_kind=r.proof_kind, new_expires_on=expires_on, current_expires_on=current.expires_on if current else None, today=nairobi_today())
    if why:
        raise error(422, "renewal_invalid", why)
    await _apply(db, r, principal, expires_on, body.note)
    await db.commit()
    out = await _out(db, r)
    await _tell_submitter(db, r, f"{out['label']} for {out['subject']} approved", f"Valid until {expires_on.isoformat()}.")
    return out


@router.post("/renewals/{renewal_id}/reject")
async def reject(renewal_id: uuid.UUID, body: RejectIn, principal: Principal = Depends(require("documents.approve")), db: AsyncSession = Depends(get_db)):
    r = await _pending(db, renewal_id)
    r.status, r.decided_by_user_id, r.decided_at, r.decision_note = "rejected", principal.user.id, datetime.now(UTC), body.note.strip()
    audit.record(db, actor_user_id=principal.user.id, action="renewal.rejected", entity_type="renewal", entity_id=r.id, note=r.decision_note)
    await db.commit()
    out = await _out(db, r)
    await _tell_submitter(db, r, f"{out['label']} renewal for {out['subject']} not accepted", r.decision_note or "")
    return out
