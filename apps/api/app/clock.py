"""Capture times for records made on a phone, possibly while offline (masterplan Section 13)."""

from datetime import UTC, datetime, timedelta

from app.deps import error

FUTURE_SKEW = timedelta(minutes=5)  # a phone clock a little ahead is fine
MAX_OFFLINE_AGE = timedelta(days=7)  # older than this and it is no longer believable as "just captured"


def capture_time(raw: datetime | None, now: datetime | None = None) -> datetime:
    """The time a person did something. Missing means now. The server never accepts the future or ancient past."""
    now = now or datetime.now(UTC)
    if raw is None:
        return now
    if raw.tzinfo is None:
        raw = raw.replace(tzinfo=UTC)
    if raw > now + FUTURE_SKEW:
        raise error(422, "bad_capture_time", "That time is in the future. Check the phone's clock.")
    if raw < now - MAX_OFFLINE_AGE:
        raise error(422, "bad_capture_time", "That record is too old to accept. Contact your manager.")
    return raw
