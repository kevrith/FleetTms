"""Reading the odometer from its photo (masterplan 5.4: automatic reading, with the driver confirming).

The server reads the photo itself, with the same service that reads receipts, and what it saw is stored beside what the driver typed. Where the
two differ the reading is flagged and an alert is raised: a typed number that is not the one in the photo is a typing slip or a lie, and the
owner should know which. The server's reading is used, not anything the phone says it read, because a phone can claim whatever it likes.

It never holds a trip up. If the service is not switched on, is slow, fails, cannot make the number out, or is not confident, there is simply
no reading, no flag, and the trip goes ahead as it always did."""

import asyncio
import logging

from app import storage
from app.config import settings
from app.document_reader import ReadError, get_reader
from app.models import Photo
from app.odometer import MAX_ODOMETER_KM

log = logging.getLogger(__name__)
MIN_CONFIDENCE = 0.5


def interpret(raw: dict) -> int | None:
    """The kilometres out of what the service returned, or None when it should not be believed."""
    value, unit, confidence = raw.get("reading"), str(raw.get("unit") or "km").lower(), raw.get("confidence")
    if isinstance(value, bool) or not isinstance(value, int | float) or not isinstance(confidence, int | float) or confidence < MIN_CONFIDENCE:
        return None
    if unit.startswith("mi"):
        return None  # a dashboard in miles cannot be compared with kilometres without guessing
    if value < 0 or value > MAX_ODOMETER_KM or value != int(value):
        return None
    return int(value)


async def read_photo(photo: Photo) -> int | None:
    """What the odometer in this photo says, in kilometres, or None."""
    if not settings.odometer_reading or photo.purged_at is not None:
        return None
    image = await storage.read(photo.storage_key)
    if image is None:
        return None
    try:
        reader = get_reader()
        raw = await asyncio.wait_for(reader.read("odometer", image, photo.content_type), timeout=settings.odometer_read_timeout_seconds)
    except (ReadError, TimeoutError):
        return None
    except Exception:  # noqa: BLE001 - reading is a courtesy: whatever goes wrong, the trip goes on
        log.warning("The odometer photo could not be read")
        return None
    return interpret(raw)
