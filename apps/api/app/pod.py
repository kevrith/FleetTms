"""Proof of delivery (masterplan 5.18): who received the cargo, when and where, with photos, a signature or a one-time
code texted to the client's phone, and any shortage or damage."""

import hashlib
import hmac
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.db import get_sessionmaker
from app.deps import Principal, error
from app.geo import distance_m
from app.models import Client, Job, PhotoKind, PodCode, ProofOfDelivery, SavedRoute, Trip
from app.photos import claim_photo
from app.sms import get_sms_sender

log = logging.getLogger(__name__)
CODE_TTL = timedelta(minutes=30)
CODE_RESEND = timedelta(seconds=60)
MAX_CODE_ATTEMPTS = 5
MAX_STROKES, MAX_POINTS = 60, 500


class PodIn(BaseModel):
    recipient_name: str = Field(min_length=2, max_length=120)
    method: Literal["code", "signature"]
    code: str | None = Field(default=None, min_length=6, max_length=6, pattern=r"^\d{6}$")
    signature: list[list[list[float]]] | None = None  # strokes, each a list of [x, y] points
    cargo_photo_id: uuid.UUID | None = None
    cargo_photo_client_id: uuid.UUID | None = None  # the id the phone gave the photo while offline
    note_photo_id: uuid.UUID | None = None
    note_photo_client_id: uuid.UUID | None = None
    shortage_qty: Decimal | None = Field(default=None, ge=0, le=1_000_000, decimal_places=2)
    shortage_unit: str | None = Field(default=None, max_length=20)
    damage_notes: str | None = Field(default=None, max_length=1000)
    damage_photo_ids: list[uuid.UUID] = Field(default_factory=list, max_length=6)
    damage_photo_client_ids: list[uuid.UUID] = Field(default_factory=list, max_length=6)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


async def request_code(db: AsyncSession, principal: Principal, trip: Trip) -> dict:
    """Texts a one-time code to the client's phone. The recipient gives it to the driver once the cargo has arrived."""
    job = (await db.execute(select(Job).where(Job.id == trip.job_id))).scalar_one_or_none() if trip.job_id else None
    client = (await db.execute(select(Client).where(Client.id == job.client_id))).scalar_one_or_none() if job else None
    if client is None or not client.phone:
        raise error(422, "client_has_no_phone", "This client has no phone number on file, so use the signature instead.")
    now = datetime.now(UTC)
    last = (await db.execute(select(PodCode).where(PodCode.trip_id == trip.id).order_by(PodCode.created_at.desc()).limit(1))).scalar_one_or_none()
    if last is not None and last.created_at > now - CODE_RESEND and last.verified_at is None:
        raise error(429, "code_just_sent", "A code was sent a moment ago. Wait a minute before asking for another.")
    code = f"{secrets.randbelow(1_000_000):06d}"
    db.add(PodCode(trip_id=trip.id, code_hash=_hash(code), sent_to=client.phone, expires_at=now + CODE_TTL))
    await db.flush()
    try:
        await get_sms_sender().send(client.phone, f"FleetTms: your delivery code for job {job.number} is {code}. Give it to the driver only once your cargo has arrived.")
    except Exception:
        log.exception("Could not text the delivery code for trip %s", trip.id)
        raise error(502, "sms_failed", "The code could not be sent. Try again, or use the signature.") from None
    return {"sent_to_last4": client.phone[-4:], "expires_in_s": int(CODE_TTL.total_seconds())}


async def _count_failed_attempt(code_id: uuid.UUID) -> None:
    """A wrong guess is counted in its own transaction. The request that made it is about to fail and roll back, and the
    count must survive that, or the limit on guesses would never take effect."""
    async with get_sessionmaker()() as other:
        row = (await other.execute(select(PodCode).where(PodCode.id == code_id).with_for_update())).scalar_one()
        row.attempts += 1
        await other.commit()


async def _check_code(db: AsyncSession, trip: Trip, code: str | None) -> None:
    if not code:
        raise error(422, "code_required", "Enter the code the recipient received by SMS.")
    row = (await db.execute(select(PodCode).where(PodCode.trip_id == trip.id, PodCode.verified_at.is_(None)).order_by(PodCode.created_at.desc()).limit(1))).scalar_one_or_none()
    if row is None or row.expires_at < datetime.now(UTC):
        raise error(422, "code_expired", "That code has expired. Ask for a new one.")
    if row.attempts >= MAX_CODE_ATTEMPTS:
        raise error(429, "too_many_attempts", "Too many wrong codes. Ask for a new one.")
    if not hmac.compare_digest(row.code_hash, _hash(code)):
        await _count_failed_attempt(row.id)
        raise error(422, "wrong_code", "That is not the code that was sent.")
    row.verified_at = datetime.now(UTC)


def _check_signature(strokes: list[list[list[float]]] | None) -> list[list[list[float]]]:
    if not strokes or sum(len(s) for s in strokes) < 5:
        raise error(422, "signature_required", "Ask the recipient to sign.")
    if len(strokes) > MAX_STROKES or any(len(s) > MAX_POINTS for s in strokes):
        raise error(422, "signature_too_big", "That signature is too long. Clear it and sign again.")
    if any(len(pt) != 2 for s in strokes for pt in s):
        raise error(422, "signature_invalid", "That signature could not be read.")
    return strokes


async def confirm_pod(db: AsyncSession, principal: Principal, trip: Trip, body: PodIn, at: datetime) -> ProofOfDelivery:
    """Records the proof of delivery for a trip, as of the time the driver did it. The caller commits."""
    existing = (await db.execute(select(ProofOfDelivery).where(ProofOfDelivery.trip_id == trip.id))).scalar_one_or_none()
    if existing is not None:
        return existing
    strokes = None
    if body.method == "code":
        await _check_code(db, trip, body.code)
    else:
        strokes = _check_signature(body.signature)
    cargo = await claim_photo(db, principal, body.cargo_photo_id, PhotoKind.POD_CARGO, required=True, client_id=body.cargo_photo_client_id, near=at)
    note = await claim_photo(db, principal, body.note_photo_id, PhotoKind.DELIVERY_NOTE, required=True, client_id=body.note_photo_client_id, near=at)
    damage_ids: list[str] = []
    for pid, cid in [(p, None) for p in body.damage_photo_ids] + [(None, c) for c in body.damage_photo_client_ids]:
        photo = await claim_photo(db, principal, pid, PhotoKind.DAMAGE, required=False, client_id=cid, near=at)
        if photo is not None:
            damage_ids.append(str(photo.id))
    damage_notes = (body.damage_notes or "").strip() or None
    if damage_notes and not damage_ids:
        raise error(422, "damage_photo_required", "Take a photo of the damage.")
    shortage = body.shortage_qty if body.shortage_qty and body.shortage_qty > 0 else None

    lat, lng = body.lat, body.lng
    if lat is None or lng is None:  # no reading of its own: the photos were taken on the spot
        for photo in (cargo, note):
            if photo is not None and photo.lat is not None and photo.lng is not None:
                lat, lng = photo.lat, photo.lng
                break
    flags: list[str] = []
    if lat is None or lng is None:
        flags.append("no_location")
    else:
        job = (await db.execute(select(Job).where(Job.id == trip.job_id))).scalar_one_or_none() if trip.job_id else None
        route = (await db.execute(select(SavedRoute).where(SavedRoute.id == job.route_id))).scalar_one_or_none() if job and job.route_id else None
        if route and route.dropoff_lat is not None and route.dropoff_lng is not None and distance_m(lat, lng, route.dropoff_lat, route.dropoff_lng) > route.site_radius_m:
            flags.append("outside_site")  # delivered somewhere other than the client's site
    if shortage:
        flags.append("shortage")
    if damage_notes:
        flags.append("damage")

    pod = ProofOfDelivery(
        trip_id=trip.id, recipient_name=body.recipient_name.strip(), method=body.method, signature=strokes,
        cargo_photo_id=cargo.id if cargo else None, note_photo_id=note.id if note else None, damage_photo_ids=damage_ids,
        shortage_qty=shortage, shortage_unit=body.shortage_unit, damage_notes=damage_notes, lat=lat, lng=lng, captured_at=at,
        flags=flags, created_by_user_id=principal.user.id,
    )  # fmt: skip
    db.add(pod)
    await db.flush()
    audit.record(db, actor_user_id=principal.user.id, action="pod.confirmed", entity_type="trip", entity_id=trip.id, after={"recipient": pod.recipient_name, "method": pod.method, "flags": flags})
    return pod


