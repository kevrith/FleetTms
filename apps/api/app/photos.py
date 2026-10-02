"""Photo intake. Every photo passes the same gate: real image, big enough, fresh, not seen before."""

import hashlib
import io
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import status
from PIL import ExifTags, Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import storage
from app.config import settings
from app.deps import Principal, error
from app.models import Photo, PhotoKind, PhotoSource
from app.reminders import NAIROBI

ALLOWED = {"JPEG": ("image/jpeg", "jpg"), "PNG": ("image/png", "png"), "WEBP": ("image/webp", "webp")}
MIN_SHORT_SIDE = 480
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


def check_fresh(captured_at: datetime, now: datetime) -> None:
    oldest = now - timedelta(minutes=settings.photo_fresh_minutes)
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
) -> Photo:
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
    check_fresh(captured_at, now)

    digest = hashlib.sha256(data).hexdigest()
    if (await db.execute(select(Photo.id).where(Photo.sha256 == digest))).first() is not None:
        raise error(status.HTTP_409_CONFLICT, "duplicate_photo", "That exact photo was already used. Take a new one.")

    content_type, ext = ALLOWED[img.format]
    key = f"{principal.business_id}/{kind.value}/{uuid.uuid4()}.{ext}"
    photo = Photo(
        kind=kind, source=source, storage_key=key, content_type=content_type, size_bytes=len(data), sha256=digest,
        width=width, height=height, captured_at=captured_at, lat=lat, lng=lng, uploaded_by_user_id=principal.user.id,
    )  # fmt: skip
    storage.save(key, data)
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
        "url": storage.signed_url(photo.storage_key),  # short-lived; fetch it again when it expires
    }


async def claim_photo(
    db: AsyncSession, principal: Principal, photo_id: uuid.UUID | None, kind: PhotoKind, *, required: bool
) -> Photo | None:
    """Looks up an uploaded photo for attaching to a record. It must be this person's, unused, and the right kind."""
    if photo_id is None:
        if required:
            raise error(422, "photo_required", "A photo is required.")
        return None
    photo = (await db.execute(select(Photo).where(Photo.id == photo_id))).scalar_one_or_none()
    if (
        photo is None
        or photo.kind != kind
        or photo.used_at is not None
        or photo.uploaded_by_user_id != principal.user.id
    ):
        raise error(422, "photo_invalid", "That photo cannot be used here. Take a new one.")
    photo.used_at = datetime.now(UTC)
    return photo
