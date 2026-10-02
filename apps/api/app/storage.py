"""Private photo storage and short-lived signed viewing links (masterplan Section 10).

Photos are never public. Callers that are allowed to see a photo get a link that works for a few minutes and
cannot be changed to point at another file. This is the local-disk backend used in development; the same
`save` / `read_path` / `signed_url` surface will sit in front of the S3-compatible bucket once it exists.
"""

import base64
import hashlib
import hmac
import time
from pathlib import Path

from app.config import settings


def _root() -> Path:
    root = Path(settings.media_dir or "media_store")  # an empty setting means the default folder
    if not root.is_absolute():
        root = Path(__file__).resolve().parent.parent / root
    return root


def _safe_path(key: str) -> Path:
    path = (_root() / key).resolve()
    if not path.is_relative_to(_root().resolve()):
        raise ValueError("Storage key escapes the storage root")
    return path


def save(key: str, data: bytes) -> None:
    path = _safe_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def read_path(key: str) -> Path | None:
    try:
        path = _safe_path(key)
    except ValueError:
        return None  # a key that points outside storage is treated as "not found"
    return path if path.is_file() else None


def _signature(key: str, expires: int) -> str:
    mac = hmac.new(settings.jwt_secret.encode(), f"media:{key}:{expires}".encode(), hashlib.sha256)
    return base64.urlsafe_b64encode(mac.digest()).decode().rstrip("=")


def signed_url(key: str, seconds: int | None = None) -> str:
    expires = int(time.time()) + (seconds or settings.media_link_seconds)
    encoded = base64.urlsafe_b64encode(key.encode()).decode().rstrip("=")
    return f"/media/{encoded}.{expires}.{_signature(key, expires)}"


def key_from_token(token: str) -> str | None:
    """Returns the storage key if the token is genuine and not expired, otherwise None."""
    try:
        encoded, expires_text, signature = token.split(".")
        expires = int(expires_text)
        key = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode()
    except ValueError:
        return None
    if expires < time.time() or not hmac.compare_digest(signature, _signature(key, expires)):
        return None
    return key
