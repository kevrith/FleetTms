"""Checks the token Google's "Sign in with Google" button hands the browser: signed by Google, meant for this app, not expired, and for an
address Google itself has verified. Nothing is trusted from the browser except that token."""

import asyncio
from functools import lru_cache

import jwt
from jwt import PyJWKClient

from app.config import settings

CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")


class GoogleTokenError(Exception):
    pass


@lru_cache(maxsize=1)
def _keys() -> PyJWKClient:
    return PyJWKClient(CERTS_URL, cache_keys=True, lifespan=3600)


def _verify(credential: str) -> dict:
    try:
        key = _keys().get_signing_key_from_jwt(credential)
        claims = jwt.decode(credential, key.key, algorithms=["RS256"], audience=settings.google_client_id, options={"require": ["exp", "iss", "aud", "sub"]})
    except (jwt.PyJWTError, OSError) as e:
        raise GoogleTokenError("That Google sign-in could not be checked.") from e
    if claims.get("iss") not in ISSUERS:
        raise GoogleTokenError("That Google sign-in could not be checked.")
    if not claims.get("email") or claims.get("email_verified") is not True:
        raise GoogleTokenError("Google has not verified that email address.")
    return claims


async def verify_id_token(credential: str) -> dict:
    """The token's claims (sub, email, name) or GoogleTokenError. The key fetch is a blocking request, so it runs off the event loop."""
    return await asyncio.to_thread(_verify, credential)
