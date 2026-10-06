"""Confirming that a person owns the email address they signed up with, so nobody can run an account on someone else's or a made-up address.

The person gets a link by email; opening it marks the address as theirs. Until then the app refuses their requests (deps.current_principal).
It is enforced only where real email is set up, because nothing else can deliver the link."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import User
from app.security import new_secret_token, sha256


def required() -> bool:
    return settings.require_email_verification and bool(settings.smtp_host)


def pending(user: User) -> bool:
    """True when this person must still confirm their address before using the app. Phone-only accounts (drivers) have no address to confirm."""
    return required() and bool(user.email) and user.email_verified_at is None


def issue(user: User) -> str:
    """A fresh one-time token for the link (the database keeps only its hash). The caller commits and sends the email."""
    token = new_secret_token()
    user.email_verify_token_hash = sha256(token)
    user.email_verify_expires_at = datetime.now(UTC) + timedelta(hours=settings.email_verify_hours)
    return token


def mark_verified(user: User) -> None:
    user.email_verified_at = datetime.now(UTC)
    user.email_verify_token_hash = None
    user.email_verify_expires_at = None


async def confirm(db: AsyncSession, token: str) -> User | None:
    """Marks the address behind this token as confirmed. None when the link is wrong or has expired."""
    user = (await db.execute(select(User).where(User.email_verify_token_hash == sha256(token)))).scalar_one_or_none()
    if user is None or user.email_verify_expires_at is None or user.email_verify_expires_at <= datetime.now(UTC):
        return None
    mark_verified(user)
    return user
