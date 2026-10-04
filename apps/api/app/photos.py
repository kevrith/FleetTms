"""Photo intake. Every photo passes the same gate: real image, big enough, fresh, not seen before."""

import hashlib
import io
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import status
from PIL import ExifTags, Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import fraud, storage
from app.clock import MAX_OFFLINE_AGE
from app.config import settings
from app.deps import Principal, error
from app.models import Photo, PhotoKind, PhotoSource
from app.reminders import NAIROBI

ALLOWED = {"JPEG": ("image/jpeg", "jpg"), "PNG": ("image/png", "png"), "WEBP": ("image/webp", "webp")}
MIN_SHORT_SIDE = 480
PHOTO_ACTION_WINDOW_MINUTES = 15  # a photo must be taken within this of the record it backs
BLANK_SHARE = 0.92  # a photo that is this much near-black or near-white is a covered lens or a dark pocket
MAX_SIDE = 12_000
FUTURE_SKEW = timedelta(minutes=5)  # tolerated clock difference between a phone and the server


def _exif_taken_at(img: Image.Image) -> datetime | None:
    """The time the picture was taken, from its metadata. Cameras write local time, usually without an offset."""
    exif = img.getexif()
    sub = exif.get_ifd(ExifTags.IFD.Exif)
    raw = sub.get(ExifTags.Base.DateTimeOriginal) or exif.get(ExifTags.Base.DateTime)
    if not raw:
        return None
    try:
        taken = datetime.strptime(str(raw), "%Y:%m:%d %H:%M:%S")  # noqa: DTZ007 - zone is applied below
    except ValueError:
        return None
    return taken.replace(tzinfo=NAIROBI).astimezone(UTC)


def _mostly_blank(img: Image.Image) -> bool:
    """True when almost every pixel is near-black or near-white (a lens cap, a dark pocket, a washed-out frame)."""
    histogram = img.convert("L").histogram()
    total = sum(histogram)
    return sum(histogram[:17]) / total > BLANK_SHARE or sum(histogram[240:]) / total > BLANK_SHARE


def check_fresh(captured_at: datetime, now: datetime, *, offline: bool = False) -> None:
    """Online photos must be minutes old. A phone that was offline may send older ones, up to a week."""
    oldest = now - (MAX_OFFLINE_AGE if offline else timedelta(minutes=settings.photo_fresh_minutes))
    if captured_at < oldest or captured_at > now + FUTURE_SKEW:
        raise error(
            422, "photo_not_fresh",
            f"That photo was not taken in the last {settings.photo_fresh_minutes} minutes. Take a new one.",
        )  # fmt: skip


async def ingest_photo(
    db: AsyncSession,
    principal: Principal,
    *,
    kind: PhotoKind,
    source: PhotoSource,
    data: bytes,
    captured_at: datetime | None,
    lat: float | None,
    lng: float | None,
    client_id: uuid.UUID | None = None,
    offline: bool = False,
) -> Photo:
    if client_id is not None:
        # A retry after a lost reply: hand back the photo that is already stored instead of making a second one.
        again = (await db.execute(select(Photo).where(Photo.client_id == client_id))).scalar_one_or_none()
        if again is not None and again.uploaded_by_user_id == principal.user.id:
            return again
    if len(data) > settings.max_photo_bytes:
        raise error(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "photo_too_large", "That photo is too large.")
    try:
        img = Image.open(io.BytesIO(data))
        img.verify()
        img = Image.open(io.BytesIO(data))  # verify() leaves the image unusable, so open it again
    except (UnidentifiedImageError, OSError, SyntaxError):
        raise error(422, "not_an_image", "That file is not a photo.") from None
    if img.format not in ALLOWED:
        raise error(422, "unsupported_image", "Use a JPEG, PNG or WebP photo.")
    width, height = img.size
    if min(width, height) < MIN_SHORT_SIDE or max(width, height) > MAX_SIDE:
        raise error(422, "photo_quality", "That photo is too small or too blurry to read. Take a closer, clearer one.")
    if _mostly_blank(img):
        raise error(422, "photo_blank", "That photo is blank or too dark. Uncover the lens, add light, and try again.")
    if lat is not None and not -90 <= lat <= 90 or lng is not None and not -180 <= lng <= 180:
        raise error(422, "invalid_location", "That location is not valid.")

    now = datetime.now(UTC)
    if kind == PhotoKind.DOCUMENT:
        captured_at = captured_at or now  # a paper read for its contents, not evidence of when something happened
        if captured_at.tzinfo is None:
            captured_at = captured_at.replace(tzinfo=UTC)
        late = False
    else:
        if source == PhotoSource.WEB:
            # The browser tells us nothing we can trust, so the picture's own metadata decides.
            taken = _exif_taken_at(img)
            if taken is None:
                raise error(422, "photo_not_fresh", "That photo has no capture time. Take it with your phone camera and upload it straight away.")  # fmt: skip
            captured_at = taken
        elif captured_at is None:
            raise error(422, "captured_at_required", "The photo needs its capture time.")
        elif captured_at.tzinfo is None:
            captured_at = captured_at.replace(tzinfo=UTC)
        check_fresh(captured_at, now, offline=offline and source == PhotoSource.CAMERA)
        late = captured_at < now - timedelta(minutes=settings.photo_fresh_minutes)

    digest = hashlib.sha256(data).hexdigest()
    if kind == PhotoKind.DOCUMENT:
        again = (await db.execute(select(Photo).where(Photo.sha256 == digest, Photo.kind == PhotoKind.DOCUMENT))).scalars().first()
        if again is not None:
            return again  # reading the same certificate twice is not a claim: hand back the photo already stored
    if (await db.execute(select(Photo.id).where(Photo.sha256 == digest))).first() is not None:
        if kind != PhotoKind.DOCUMENT:  # a paper read for its contents is not a claim, so it is not reported as one
            await fraud.duplicate_photo(db, sha=digest, user_id=principal.user.id)
            await db.commit()  # the photo is refused, but the owner is told someone tried to use it twice
        raise error(status.HTTP_409_CONFLICT, "duplicate_photo", "That exact photo was already used. Take a new one.")

    content_type, ext = ALLOWED[img.format]
    key = f"{principal.business_id}/{kind.value}/{uuid.uuid4()}.{ext}"
    photo = Photo(
        kind=kind, source=source, storage_key=key, content_type=content_type, size_bytes=len(data), sha256=digest,
        width=width, height=height, captured_at=captured_at, lat=lat, lng=lng, uploaded_by_user_id=principal.user.id,
        client_id=client_id, late=late,
    )  # fmt: skip
    await storage.save(key, data, content_type)
    db.add(photo)
    await db.flush()
    return photo


def photo_out(photo: Photo | None) -> dict | None:
    if photo is None:
        return None
    return {
        "id": photo.id,
        "kind": photo.kind.value,
        "source": photo.source.value,
        "captured_at": photo.captured_at,
        "lat": photo.lat,
        "lng": photo.lng,
        "late": photo.late,
        "client_id": photo.client_id,
        "purged": photo.purged_at is not None,  # past its retention period: the record is kept, the picture is not
        "url": None if photo.purged_at is not None else storage.signed_url(photo.storage_key),  # short-lived; fetch it again when it expires
    }


async def claim_photo(
    db: AsyncSession,
    principal: Principal,
    photo_id: uuid.UUID | None,
    kind: PhotoKind,
    *,
    required: bool,
    client_id: uuid.UUID | None = None,
    near: datetime | None = None,
) -> Photo | None:
    """Looks up an uploaded photo for attaching to a record. It must be this person's, unused, and the right kind.

    The photo can be named by its server id, or by the id the phone gave it when it was queued offline. `near` is
    when the record was made: the photo must have been taken around then, so an old photo cannot back a new record.
    """
    if photo_id is None and client_id is None:
        if required:
            raise error(422, "photo_required", "A photo is required.")
        return None
    column = Photo.id if photo_id is not None else Photo.client_id
    photo = (await db.execute(select(Photo).where(column == (photo_id or client_id)))).scalar_one_or_none()
    if (
        photo is None
        or photo.kind != kind
        or photo.used_at is not None
        or photo.uploaded_by_user_id != principal.user.id
    ):
        raise error(422, "photo_invalid", "That photo cannot be used here. Take a new one.")
    if near is not None and abs(photo.captured_at - near) > timedelta(minutes=PHOTO_ACTION_WINDOW_MINUTES):
        raise error(422, "photo_time_mismatch", "That photo was not taken when this was recorded. Take a new one.")
    photo.used_at = datetime.now(UTC)
    return photo
