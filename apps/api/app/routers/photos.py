import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app import storage
from app.config import settings
from app.db import get_db
from app.deps import Principal, error, require_any
from app.models import PhotoKind, PhotoSource
from app.photos import ingest_photo, photo_out

router = APIRouter(tags=["photos"])


@router.post("/photos", status_code=status.HTTP_201_CREATED)
async def upload_photo(
    file: UploadFile,
    kind: Annotated[PhotoKind, Form()],
    source: Annotated[PhotoSource, Form()],
    captured_at: Annotated[datetime | None, Form()] = None,
    lat: Annotated[float | None, Form()] = None,
    lng: Annotated[float | None, Form()] = None,
    client_id: Annotated[uuid.UUID | None, Form()] = None,
    offline: Annotated[bool, Form()] = False,
    principal: Principal = Depends(require_any("trips.own", "trips.manage")),
    db: AsyncSession = Depends(get_db),
):
    """Uploads one photo. The response carries the id to attach it to a record, and a short-lived viewing link."""
    data = await file.read(settings.max_photo_bytes + 1)
    photo = await ingest_photo(
        db, principal, kind=kind, source=source, data=data, captured_at=captured_at, lat=lat, lng=lng,
        client_id=client_id, offline=offline,
    )
    await db.commit()
    return photo_out(photo)


@router.get("/media/{token}")
async def view_media(token: str):
    """Serves a photo to anyone holding a genuine, unexpired link. Links are only issued to people allowed to see it."""
    key = storage.key_from_token(token)
    path = storage.read_path(key) if key else None
    if path is None:
        raise error(status.HTTP_404_NOT_FOUND, "not_found", "That link has expired.")
    media_type = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(path.suffix[1:], "application/octet-stream")
    return FileResponse(
        path,
        media_type=media_type,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


