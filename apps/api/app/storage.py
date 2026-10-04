"""Private file storage and short-lived signed viewing links (masterplan Section 10).

Photos and data copies are never public. Callers that are allowed to see a file get a link that works for a few minutes and
cannot be changed to point at another file. The API reads the bytes and serves them itself, so the link is the same whether the
files sit in a folder (development, a small single-server install) or in an S3-compatible bucket (STORAGE_BACKEND=s3: AWS S3,
Cloudflare R2, DigitalOcean Spaces, MinIO, Backblaze B2). Nothing in the bucket is ever public either.
"""

import asyncio
import base64
import hashlib
import hmac
import mimetypes
import tempfile
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import Response
from fastapi.responses import FileResponse, StreamingResponse

from app.config import settings

CHUNK = 256 * 1024


# --- the folder on disk ---------------------------------------------------------------------------------------------------------

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


def _local_path(key: str) -> Path | None:
    try:
        path = _safe_path(key)
    except ValueError:
        return None  # a key that points outside storage is treated as "not found"
    return path if path.is_file() else None


# --- the bucket -----------------------------------------------------------------------------------------------------------------

_client: Any = None


def uses_bucket() -> bool:
    return settings.storage_backend == "s3"


def config_problem(s: Any = None) -> str | None:
    """What is wrong with the storage settings (these, or the live ones), or None."""
    s = s or settings
    if s.storage_backend not in ("local", "s3"):
        return "STORAGE_BACKEND must be local or s3."
    if s.storage_backend == "s3" and not s.s3_bucket:
        return "STORAGE_BACKEND=s3 needs S3_BUCKET."
    return None


def _bucket_client() -> Any:
    global _client
    if _client is None:
        import boto3
        from botocore.config import Config

        _client = boto3.client(
            "s3",
            region_name=settings.s3_region or None,
            endpoint_url=settings.s3_endpoint_url or None,
            aws_access_key_id=settings.s3_access_key or None,  # empty: the machine's own role or environment is used
            aws_secret_access_key=settings.s3_secret_key or None,
            config=Config(
                s3={"addressing_style": "path" if settings.s3_force_path_style else "auto"},
                retries={"max_attempts": 4, "mode": "standard"},
                connect_timeout=5,
                read_timeout=30,
                signature_version="s3v4",
            ),
        )
    return _client


def reset_client() -> None:
    """Forget the connection, so changed settings take effect (used by tests and the migration command)."""
    global _client
    _client = None


def _object_key(key: str) -> str:
    key = key.replace("\\", "/")
    if key.startswith("/") or ".." in key.split("/"):
        raise ValueError("Storage key escapes the storage root")
    prefix = settings.s3_prefix.strip("/")
    return f"{prefix}/{key}" if prefix else key


def _is_missing(error: Exception) -> bool:
    code = str(getattr(error, "response", {}).get("Error", {}).get("Code", ""))
    return code in ("404", "NoSuchKey", "NotFound")


def _extra_args(content_type: str | None) -> dict:
    args: dict = {}
    if content_type:
        args["ContentType"] = content_type
    if settings.s3_encryption:
        args["ServerSideEncryption"] = settings.s3_encryption  # "AES256", or "aws:kms" on AWS
    return args


# --- what the rest of the app uses ----------------------------------------------------------------------------------------------

async def save(key: str, data: bytes, content_type: str | None = None) -> None:
    if uses_bucket():
        await asyncio.to_thread(lambda: _bucket_client().put_object(Bucket=settings.s3_bucket, Key=_object_key(key), Body=data, **_extra_args(content_type)))
        return
    path = _safe_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


async def save_file(key: str, source: Path, content_type: str | None = None) -> None:
    """Stores a file that is already on disk (a data copy), without holding all of it in memory."""
    if uses_bucket():
        await asyncio.to_thread(lambda: _bucket_client().upload_file(str(source), settings.s3_bucket, _object_key(key), ExtraArgs=_extra_args(content_type)))
        return
    path = _safe_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(lambda: path.write_bytes(source.read_bytes()) if source.resolve() != path else None)


async def read(key: str) -> bytes | None:
    """The stored bytes, or None if there is no such file."""
    if uses_bucket():
        try:
            obj = await asyncio.to_thread(lambda: _bucket_client().get_object(Bucket=settings.s3_bucket, Key=_object_key(key)))
            return await asyncio.to_thread(obj["Body"].read)
        except ValueError:
            return None
        except Exception as e:
            if _is_missing(e):
                return None
            raise
    path = _local_path(key)
    return await asyncio.to_thread(path.read_bytes) if path else None


async def exists(key: str) -> bool:
    if uses_bucket():
        try:
            await asyncio.to_thread(lambda: _bucket_client().head_object(Bucket=settings.s3_bucket, Key=_object_key(key)))
            return True
        except ValueError:
            return False
        except Exception as e:
            if _is_missing(e):
                return False
            raise
    return _local_path(key) is not None


async def delete(key: str) -> bool:
    """Removes a stored file. True if there was one to remove."""
    if uses_bucket():
        try:
            if not await exists(key):
                return False
            await asyncio.to_thread(lambda: _bucket_client().delete_object(Bucket=settings.s3_bucket, Key=_object_key(key)))
            return True
        except ValueError:
            return False
    path = _local_path(key)
    if path is None:
        return False
    path.unlink()
    return True


async def stream(key: str) -> AsyncIterator[bytes] | None:
    """The bytes of a stored file a piece at a time, or None if there is no such file (checked before anything is sent)."""
    if uses_bucket():
        try:
            obj = await asyncio.to_thread(lambda: _bucket_client().get_object(Bucket=settings.s3_bucket, Key=_object_key(key)))
        except ValueError:
            return None
        except Exception as e:
            if _is_missing(e):
                return None
            raise
        body = obj["Body"]

        async def pieces() -> AsyncIterator[bytes]:
            try:
                while chunk := await asyncio.to_thread(body.read, CHUNK):
                    yield chunk
            finally:
                body.close()

        return pieces()
    path = _local_path(key)
    if path is None:
        return None

    async def from_disk() -> AsyncIterator[bytes]:
        with path.open("rb") as f:
            while chunk := await asyncio.to_thread(f.read, CHUNK):
                yield chunk

    return from_disk()


async def serve(key: str, media_type: str | None = None, *, filename: str | None = None, headers: dict | None = None) -> Response | None:
    """A response carrying the stored file, or None if there is no such file."""
    media_type = media_type or mimetypes.guess_type(key)[0] or "application/octet-stream"
    if not uses_bucket():
        path = _local_path(key)
        return FileResponse(path, media_type=media_type, filename=filename, headers=headers) if path else None
    pieces = await stream(key)
    if pieces is None:
        return None
    out = dict(headers or {})
    if filename:
        out["Content-Disposition"] = f'attachment; filename="{filename}"'
    return StreamingResponse(pieces, media_type=media_type, headers=out)


class Scratch:
    """A temporary file to build something large in (a data copy) before it goes to storage; removed when done."""

    def __init__(self) -> None:
        self.path = Path(tempfile.gettempdir()) / f"fleettms-{uuid.uuid4().hex}.tmp"

    def __enter__(self) -> Path:
        return self.path

    def __exit__(self, *exc: object) -> None:
        self.path.unlink(missing_ok=True)


async def probe() -> dict:
    """Can files be written, read and removed right now? What `/ready` asks."""
    problem = config_problem()
    if problem:
        return {"ok": False, "backend": settings.storage_backend, "error": problem}
    key = f"_probe/{uuid.uuid4().hex}"
    try:
        await save(key, b"ok", "text/plain")
        ok = await read(key) == b"ok"
        await delete(key)
    except Exception as e:  # noqa: BLE001 - any failure means "not ready"
        return {"ok": False, "backend": settings.storage_backend, "error": type(e).__name__}
    return {"ok": ok, "backend": settings.storage_backend}


# --- signed links ---------------------------------------------------------------------------------------------------------------

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
