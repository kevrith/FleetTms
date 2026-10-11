"""Reads the proof sent with a renewal and sets it against what was typed (rules in app/renewal_check_rules.py). Best effort: with reading
switched off, or a file that cannot be read, the approver simply has no automatic check."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import document_reader, document_rules, ratelimit, renewal_check_rules, storage
from app.models import Membership, Photo, RenewalRequest, Vehicle
from app.reminders import nairobi_today

READS_PER_DAY = 100  # for the whole business


def reading_kind(doc_type: str, proof_kind: str) -> str | None:
    if doc_type == "insurance":
        return "insurance_certificate"
    if doc_type == "driving_licence":
        return "driving_licence" if proof_kind == "digital_licence" else "licence_receipt"
    return None  # inspection, permits and the like are not read automatically


async def run(db: AsyncSession, r: RenewalRequest, *, again: bool = False) -> dict | None:
    """The check for this renewal, made now and kept on it (or the one already kept). None when it cannot be made."""
    if r.proof_check is not None and not again:
        return r.proof_check
    kind = reading_kind(r.doc_type, r.proof_kind)
    photo = (await db.execute(select(Photo).where(Photo.id == r.photo_id))).scalar_one_or_none() if r.photo_id else None
    if kind is None or photo is None or photo.purged_at is not None:
        return None
    if await ratelimit.hit("renewal_reads", str(r.business_id), READS_PER_DAY, 86_400) is not None:
        return None
    data = await storage.read(photo.storage_key)
    if data is None:
        return None
    try:
        raw = await document_reader.get_reader().read(kind, data, photo.content_type)
    except document_reader.ReadError:
        return None
    fields = document_rules.normalise(kind, raw)
    confidence = raw.get("confidence")
    vehicle = (await db.execute(select(Vehicle).where(Vehicle.id == r.vehicle_id))).scalar_one_or_none() if r.vehicle_id else None
    member = (await db.execute(select(Membership).where(Membership.id == r.membership_id))).scalar_one_or_none() if r.membership_id else None
    verdict = renewal_check_rules.compare(
        kind=kind, fields=fields, confidence=float(confidence) if isinstance(confidence, int | float) else None, today=nairobi_today(),
        typed={"new_expires_on": r.new_expires_on, "name": member.user.name if member else None, "registration": vehicle.registration if vehicle else None, "reference": r.reference},
    )  # fmt: skip
    r.proof_check = {**verdict, "read": fields, "kind": kind, "at": datetime.now(UTC).isoformat()}
    return r.proof_check
