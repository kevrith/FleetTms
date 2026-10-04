"""How to reach FleetTms support, for the help pages and the apps. Public: someone who cannot sign in needs it most."""

from urllib.parse import quote

from fastapi import APIRouter, Depends

from app import ratelimit
from app.config import settings
from app.phone import normalize_phone

router = APIRouter(tags=["support"])


@router.get("/contact", dependencies=[Depends(ratelimit.limit("contact", 60, 60))])
async def contact():
    """The WhatsApp number (with a ready-to-open link), the email address and the hours. Anything not set up yet is null."""
    number = normalize_phone(settings.support_whatsapp) if settings.support_whatsapp else None
    return {
        "whatsapp": number,
        "whatsapp_link": f"https://wa.me/{number.lstrip('+')}?text={quote('Hello FleetTms, I need help with')}" if number else None,
        "email": settings.support_email or None,
        "hours": settings.support_hours,
    }
