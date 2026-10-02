import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.config import settings

_hasher = PasswordHasher()
# Verified against when the account does not exist, so response time does not reveal it.
_DUMMY_HASH = _hasher.hash("not-a-real-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, InvalidHashError):
        return False


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_secret_token() -> str:
    return secrets.token_urlsafe(32)


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


def new_otp_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


# ---- access tokens ---------------------------------------------------------------------------


def _jwt_key() -> str:
    if not settings.jwt_secret:
        raise RuntimeError("JWT_SECRET is not configured")
    return settings.jwt_secret


def create_access_token(user_id: uuid.UUID, session_id: uuid.UUID) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "sid": str(session_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_minutes),
    }
    return jwt.encode(payload, _jwt_key(), algorithm="HS256")


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, _jwt_key(), algorithms=["HS256"], options={"require": ["exp", "sid"]})
    except jwt.PyJWTError:
        return None


# ---- two-step verification (authenticator app) ------------------------------------------------


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, account: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=account, issuer_name="FleetTms")


def verify_totp(secret: str | None, code: str) -> bool:
    return bool(secret) and pyotp.TOTP(secret).verify(code.strip(), valid_window=1)
