"""The address Meta calls for WhatsApp: it checks it once (GET, with our verify token), then sends reports and replies (POST, signed)."""

import hmac
import json

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import ratelimit, whatsapp, whatsapp_inbound
from app.config import settings
from app.db import get_db
from app.deps import error
from app.tenancy import current_business_id

router = APIRouter(tags=["whatsapp"])


@router.get("/hooks/whatsapp", dependencies=[Depends(ratelimit.hook_guard)])
async def verify(request: Request):
    """Meta's one-time check that this address is ours: it sends the verify token and expects its challenge back."""
    q = request.query_params
    token = settings.whatsapp_verify_token
    if not token or q.get("hub.mode") != "subscribe" or not hmac.compare_digest(q.get("hub.verify_token", ""), token):
        raise error(status.HTTP_403_FORBIDDEN, "forbidden", "Not allowed.")
    return Response(q.get("hub.challenge", ""), media_type="text/plain")


@router.post("/hooks/whatsapp", dependencies=[Depends(ratelimit.hook_guard)])
async def receive(request: Request, db: AsyncSession = Depends(get_db)):
    """Reports and replies. Unsigned or wrongly signed is refused; anything signed is answered 200 even if it holds nothing we know, since
    Meta repeats a delivery that is not answered."""
    body = await request.body()
    if not whatsapp.signature_ok(body, request.headers.get("x-hub-signature-256")):
        raise error(status.HTTP_403_FORBIDDEN, "forbidden", "Not allowed.")
    try:
        payload = json.loads(body)
    except ValueError:
        return {"ok": True}
    if not isinstance(payload, dict):
        return {"ok": True}
    try:
        await whatsapp_inbound.process(db, payload)
        await db.commit()
    finally:
        current_business_id.set(None)
    return {"ok": True}
