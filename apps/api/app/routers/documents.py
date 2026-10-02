import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.db import get_db
from app.deps import Principal, error, require
from app.models import ComplianceDocType, ComplianceDocument, Membership
from app.reminders import nairobi_today
from app.routers.vehicles import get_vehicle
from app.vehicle_scope import vehicle_in_scope

router = APIRouter(prefix="/documents", tags=["documents"])
FIELDS = ["doc_type", "vehicle_id", "membership_id", "reference", "issued_on", "expires_on"]

VEHICLE_ONLY = {
    ComplianceDocType.INSURANCE,
    ComplianceDocType.INSPECTION,
    ComplianceDocType.NTSA_LICENCE,
    ComplianceDocType.TLB_LICENCE,
}
STAFF_ONLY = {ComplianceDocType.DRIVING_LICENCE}


class DocumentIn(BaseModel):
    doc_type: ComplianceDocType
    vehicle_id: uuid.UUID | None = None
    membership_id: uuid.UUID | None = None
    reference: str | None = Field(default=None, max_length=80)
    issued_on: date | None = None
    expires_on: date

    @model_validator(mode="after")
    def _one_owner(self):
        if (self.vehicle_id is None) == (self.membership_id is None):
            raise ValueError("A document belongs to either a vehicle or a staff member.")
        if self.vehicle_id is None and self.doc_type in VEHICLE_ONLY:
            raise ValueError("That document type belongs to a vehicle.")
        if self.membership_id is None and self.doc_type in STAFF_ONLY:
            raise ValueError("That document type belongs to a staff member.")
        if self.issued_on and self.issued_on > self.expires_on:
            raise ValueError("The issue date is after the expiry date.")
        return self


def _out(d: ComplianceDocument) -> dict:
    return {
        "id": d.id,
        "doc_type": d.doc_type.value,
        "vehicle_id": d.vehicle_id,
        "membership_id": d.membership_id,
        "reference": d.reference,
        "issued_on": d.issued_on,
        "expires_on": d.expires_on,
    }



def _check(principal: Principal, vehicle_id: uuid.UUID | None, verb: str) -> None:
    perm = f"{'vehicles' if vehicle_id is not None else 'staff'}.{verb}"
    if perm not in principal.permissions:
        raise error(status.HTTP_403_FORBIDDEN, "forbidden", "You do not have permission to do this.")
    if vehicle_id is not None and not vehicle_in_scope(principal, vehicle_id):
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That document was not found.")


async def _get(db: AsyncSession, principal: Principal, doc_id: uuid.UUID, verb: str) -> ComplianceDocument:
    d = (await db.execute(select(ComplianceDocument).where(ComplianceDocument.id == doc_id))).scalar_one_or_none()
    if d is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That document was not found.")
    _check(principal, d.vehicle_id, verb)
    return d


async def _validate_owner(db: AsyncSession, principal: Principal, body: DocumentIn) -> None:
    if body.vehicle_id is not None:
        await get_vehicle(db, principal, body.vehicle_id)
    elif (await db.execute(select(Membership.id).where(Membership.id == body.membership_id))).first() is None:
        raise error(status.HTTP_404_NOT_FOUND, "staff_not_found", "That staff member was not found.")


@router.get("")
async def list_documents(
    vehicle_id: uuid.UUID | None = None,
    membership_id: uuid.UUID | None = None,
    principal: Principal = Depends(require()),
    db: AsyncSession = Depends(get_db),
):
    if (vehicle_id is None) == (membership_id is None):
        raise error(422, "filter_required", "Pass either vehicle_id or membership_id.")
    _check(principal, vehicle_id, "view")
    if vehicle_id is not None:
        await get_vehicle(db, principal, vehicle_id)  # 404 for a vehicle that is not ours
    query = select(ComplianceDocument).order_by(ComplianceDocument.expires_on)
    query = query.where(
        ComplianceDocument.vehicle_id == vehicle_id if vehicle_id else ComplianceDocument.membership_id == membership_id
    )
    return [_out(d) for d in (await db.execute(query)).scalars()]


@router.get("/expiring")
async def expiring(
    days: int = Query(default=30, ge=0, le=365),
    principal: Principal = Depends(require()),
    db: AsyncSession = Depends(get_db),
):
    """Documents already expired or expiring within `days`, soonest first, limited to what the caller may see."""
    cutoff = nairobi_today() + timedelta(days=days)
    rows = (
        await db.execute(
            select(ComplianceDocument).where(ComplianceDocument.expires_on <= cutoff).order_by(ComplianceDocument.expires_on)
        )
    ).scalars()
    out = []
    for d in rows:
        perm = "vehicles.view" if d.vehicle_id else "staff.view"
        if perm in principal.permissions and (d.vehicle_id is None or vehicle_in_scope(principal, d.vehicle_id)):
            out.append(_out(d))
    return out


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_document(
    body: DocumentIn, principal: Principal = Depends(require()), db: AsyncSession = Depends(get_db)
):
    _check(principal, body.vehicle_id, "manage")
    await _validate_owner(db, principal, body)
    doc = ComplianceDocument(**body.model_dump())
    db.add(doc)
    await db.flush()
    audit.record(
        db, actor_user_id=principal.user.id, action="document.created", entity_type="document",
        entity_id=doc.id, after=audit.snapshot(doc, FIELDS),
    )  # fmt: skip
    await db.commit()
    return _out(doc)


@router.put("/{doc_id}")
async def update_document(
    doc_id: uuid.UUID, body: DocumentIn, principal: Principal = Depends(require()), db: AsyncSession = Depends(get_db)
):
    doc = await _get(db, principal, doc_id, "manage")
    if (body.vehicle_id, body.membership_id) != (doc.vehicle_id, doc.membership_id):
        raise error(422, "owner_fixed", "A document cannot be moved to another vehicle or person.")
    before = audit.snapshot(doc, FIELDS)
    for field, value in body.model_dump().items():
        setattr(doc, field, value)
    audit.record(
        db, actor_user_id=principal.user.id, action="document.updated", entity_type="document",
        entity_id=doc.id, before=before, after=audit.snapshot(doc, FIELDS),
    )  # fmt: skip
    await db.commit()
    return _out(doc)


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    doc_id: uuid.UUID, principal: Principal = Depends(require()), db: AsyncSession = Depends(get_db)
):
    doc = await _get(db, principal, doc_id, "manage")
    audit.record(
        db, actor_user_id=principal.user.id, action="document.deleted", entity_type="document",
        entity_id=doc.id, before=audit.snapshot(doc, FIELDS),
    )  # fmt: skip
    await db.delete(doc)
    await db.commit()
