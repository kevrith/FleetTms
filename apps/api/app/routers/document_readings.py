"""Reading documents from photos (masterplan 5.28): a photo goes in, suggested fields and what to check come out, and a person
confirms them (correcting what is wrong). The photo is not used up, so the same one can then back the fuel entry or the ticket."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, document_reader, document_rules, storage
from app.config import settings
from app.db import get_db
from app.deps import Principal, current_principal, error, require
from app.models import ComplianceDocType, ComplianceDocument, DocumentReading, Photo, Vehicle
from app.vehicle_scope import scope_vehicles

router = APIRouter(tags=["document-readings"])
Kind = Literal["fuel_receipt", "weighbridge_ticket", "delivery_note", "insurance_certificate", "logbook"]


class ReadIn(BaseModel):
    photo_id: uuid.UUID
    kind: Kind
    vehicle_id: uuid.UUID | None = None  # the vehicle the document is said to be for, so a plate that disagrees is pointed out


class ConfirmIn(BaseModel):
    fields: dict


def reading_out(r: DocumentReading, plate: str | None = None) -> dict:
    return {
        "id": r.id, "photo_id": r.photo_id, "kind": r.kind, "vehicle_id": r.vehicle_id, "fields": r.confirmed_fields if r.confirmed_fields is not None else r.read_fields,
        "read_fields": r.read_fields, "warnings": r.warnings, "missing": [f for f in document_rules.REQUIRED[r.kind] if (r.confirmed_fields or r.read_fields).get(f) is None],
        "confidence": r.confidence, "provider": r.provider, "status": r.status, "corrections": r.corrections, "created_at": r.created_at, "confirmed_at": r.confirmed_at,
    }  # fmt: skip


async def _get(db: AsyncSession, principal: Principal, reading_id: uuid.UUID) -> DocumentReading:
    r = (await db.execute(select(DocumentReading).where(DocumentReading.id == reading_id))).scalar_one_or_none()
    if r is None or (r.read_by_user_id != principal.user.id and "vehicles.manage" not in principal.permissions):
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That reading was not found.")
    return r


@router.post("/document-readings", status_code=status.HTTP_201_CREATED)
async def read_document(body: ReadIn, principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    """Reads a photo that was already uploaded. Returns suggested fields, what is missing, and anything that does not add up."""
    photo = (await db.execute(select(Photo).where(Photo.id == body.photo_id))).scalar_one_or_none()
    if photo is None or (photo.uploaded_by_user_id != principal.user.id and "vehicles.view" not in principal.permissions):
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That photo was not found.")
    vehicle = None
    if body.vehicle_id is not None:
        vehicle = (await db.execute(scope_vehicles(select(Vehicle), principal).where(Vehicle.id == body.vehicle_id))).scalar_one_or_none()
        if vehicle is None:
            raise error(status.HTTP_404_NOT_FOUND, "not_found", "That vehicle was not found.")
    today_reads = (await db.execute(select(func.count()).select_from(DocumentReading).where(DocumentReading.read_by_user_id == principal.user.id, DocumentReading.created_at >= datetime.now(UTC) - timedelta(days=1)))).scalar_one()
    if today_reads >= settings.document_reads_per_day:
        raise error(status.HTTP_429_TOO_MANY_REQUESTS, "too_many_reads", "That is a lot of documents for one day. Type the rest in, or try again tomorrow.")
    image = await storage.read(photo.storage_key)
    if image is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That photo is no longer stored.")
    try:
        reader = document_reader.get_reader()
        raw = await reader.read(body.kind, image, photo.content_type)
    except document_reader.ReadError as e:
        raise error(status.HTTP_503_SERVICE_UNAVAILABLE, "reading_unavailable", str(e)) from None
    fields = document_rules.normalise(body.kind, raw)
    verdict = document_rules.check(body.kind, fields, registration=vehicle.registration if vehicle else None, gvw_limit_kg=vehicle.gvw_limit_kg if vehicle else None)
    confidence = raw.get("confidence")
    row = DocumentReading(
        photo_id=photo.id, kind=body.kind, vehicle_id=vehicle.id if vehicle else None, read_fields=fields, warnings=verdict["warnings"], provider=reader.name,
        confidence=float(confidence) if isinstance(confidence, int | float) and 0 <= confidence <= 1 else None, read_by_user_id=principal.user.id,
    )  # fmt: skip
    db.add(row)
    await db.flush()
    audit.record(db, actor_user_id=principal.user.id, action="document.read", entity_type="document_reading", entity_id=row.id, after={"kind": body.kind, "provider": reader.name})
    await db.commit()
    return {**reading_out(row), "missing": verdict["missing"]}


@router.post("/document-readings/{reading_id}/confirm")
async def confirm_reading(reading_id: uuid.UUID, body: ConfirmIn, principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    """Records what the person says the document really says, so a wrong reading never becomes a wrong record. Returns the clean
    values, ready to go into the fuel entry, the ticket or the form. How many fields were corrected is kept, to see how good the reading is."""
    r = await _get(db, principal, reading_id)
    if r.status != "pending":
        raise error(status.HTTP_409_CONFLICT, "already_answered", "That reading has already been confirmed or rejected.")
    fields = document_rules.normalise(r.kind, body.fields)
    vehicle = (await db.execute(select(Vehicle).where(Vehicle.id == r.vehicle_id))).scalar_one_or_none() if r.vehicle_id else None
    verdict = document_rules.check(r.kind, fields, registration=vehicle.registration if vehicle else None, gvw_limit_kg=vehicle.gvw_limit_kg if vehicle else None)
    if verdict["missing"]:
        raise error(422, "fields_missing", f"Fill in: {', '.join(f.replace('_', ' ') for f in verdict['missing'])}.")
    r.confirmed_fields, r.status, r.confirmed_by_user_id, r.confirmed_at = fields, "confirmed", principal.user.id, datetime.now(UTC)
    r.corrections = sum(1 for k in fields if fields[k] != r.read_fields.get(k))
    audit.record(db, actor_user_id=principal.user.id, action="document.confirmed", entity_type="document_reading", entity_id=r.id, after={"kind": r.kind, "corrections": r.corrections})
    await db.commit()
    return {**reading_out(r), "warnings": verdict["warnings"]}


@router.post("/document-readings/{reading_id}/reject", status_code=status.HTTP_204_NO_CONTENT)
async def reject_reading(reading_id: uuid.UUID, principal: Principal = Depends(current_principal), db: AsyncSession = Depends(get_db)):
    r = await _get(db, principal, reading_id)
    if r.status != "pending":
        raise error(status.HTTP_409_CONFLICT, "already_answered", "That reading has already been confirmed or rejected.")
    r.status = "rejected"
    audit.record(db, actor_user_id=principal.user.id, action="document.rejected", entity_type="document_reading", entity_id=r.id)
    await db.commit()


@router.post("/document-readings/{reading_id}/apply")
async def apply_reading(reading_id: uuid.UUID, principal: Principal = Depends(require("vehicles.manage")), db: AsyncSession = Depends(get_db)):
    """An insurance certificate that has been confirmed becomes the vehicle's insurance record, with its expiry date, so the expiry
    reminders start. Other documents are used by the form they came from."""
    r = await _get(db, principal, reading_id)
    if r.kind != "insurance_certificate" or r.status != "confirmed":
        raise error(status.HTTP_409_CONFLICT, "cannot_apply", "Only a confirmed insurance certificate can be saved as a vehicle record.")
    f = r.confirmed_fields or {}
    vehicle_id = r.vehicle_id
    if vehicle_id is None and f.get("registration"):
        vehicle_id = (await db.execute(select(Vehicle.id).where(Vehicle.registration == f["registration"]))).scalar_one_or_none()
    if vehicle_id is None:
        raise error(422, "vehicle_unknown", "Choose the vehicle this certificate is for.")
    doc = ComplianceDocument(doc_type=ComplianceDocType.INSURANCE, vehicle_id=vehicle_id, reference=f.get("policy_no"), issued_on=datetime.fromisoformat(f["valid_from"]).date() if f.get("valid_from") else None, expires_on=datetime.fromisoformat(f["valid_to"]).date())
    db.add(doc)
    await db.flush()
    audit.record(db, actor_user_id=principal.user.id, action="document.created", entity_type="compliance_document", entity_id=doc.id, after={"doc_type": "insurance", "from_reading": str(r.id)})
    await db.commit()
    return {"document_id": doc.id, "vehicle_id": vehicle_id, "expires_on": doc.expires_on}


@router.get("/document-readings/summary")
async def reading_summary(principal: Principal = Depends(require("vehicles.manage")), db: AsyncSession = Depends(get_db)):
    """How good the reading has been, by document type: how many were confirmed exactly as read, and how many needed a correction."""
    out: dict = {}
    for r in (await db.execute(select(DocumentReading).where(DocumentReading.created_at >= datetime.now(UTC) - timedelta(days=90)))).scalars():
        s = out.setdefault(r.kind, {"kind": r.kind, "read": 0, "confirmed": 0, "rejected": 0, "pending": 0, "exact": 0, "fields_corrected": 0})
        s["read"] += 1
        s[r.status] += 1
        if r.status == "confirmed":
            s["exact"] += r.corrections == 0
            s["fields_corrected"] += r.corrections
    return [{**s, "exact_pct": round(s["exact"] / s["confirmed"] * 100) if s["confirmed"] else None} for s in sorted(out.values(), key=lambda x: -x["read"])]
