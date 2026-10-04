"""Rate limits for the endpoints anyone on the internet can reach (sign-in, codes, sign-up, links and hooks).

A fixed window counted in Redis: the first hit in a window starts its clock, and once the count passes the limit every
further hit is refused until the window ends. The limiter fails open: if Redis cannot be reached the request goes ahead
and a warning is logged, because a Redis outage must not lock every driver out of the app. The account lockouts in
`routers/auth.py` still protect passwords and codes when it does.
"""

import logging
import time
from collections.abc import Callable

from fastapi import HTTPException, Request, status
from redis.asyncio import Redis

from app.config import settings
from app.deps import error

log = logging.getLogger("fleettms.ratelimit")

_clients: dict[int, Redis] = {}


def _redis() -> Redis:
    """One connection pool for each event loop (the tests run every test on its own loop)."""
    import asyncio

    key = id(asyncio.get_running_loop())
    if key not in _clients:
        _clients[key] = Redis.from_url(settings.redis_url)
    return _clients[key]


def client_ip(request: Request) -> str:
    """Who is calling. Behind a proxy the address is in X-Forwarded-For, but that header is only believed when the
    deployment says a proxy it controls sets it (TRUST_PROXY_HEADERS), otherwise anyone could invent their own address."""
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def hit(bucket: str, subject: str, limit: int, window_seconds: int) -> int | None:
    """Counts one request. Returns None when it is allowed, or the seconds to wait when the limit has been passed."""
    if not settings.rate_limits_enabled:
        return None
    window = int(time.time() // window_seconds)
    key = f"rl:{bucket}:{subject}:{window}"
    try:
        redis = _redis()
        async with redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, window_seconds)
            count, _ = await pipe.execute()
    except Exception:  # noqa: BLE001 - any Redis failure means "do not block"
        log.warning("Rate limiter could not reach Redis; allowing the request (%s)", bucket)
        return None
    if count > limit:
        return max(1, (window + 1) * window_seconds - int(time.time()))
    return None


def refuse(retry_after: int):
    exc = error(status.HTTP_429_TOO_MANY_REQUESTS, "rate_limited", f"Too many requests. Try again in {retry_after} seconds.")
    exc.headers = {"Retry-After": str(retry_after)}
    return exc


def limit(bucket: str, count: int, window_seconds: int) -> Callable:
    """A route dependency: at most `count` requests from one address in `window_seconds`."""

    async def dependency(request: Request) -> None:
        wait = await hit(bucket, client_ip(request), count, window_seconds)
        if wait is not None:
            raise refuse(wait)

    return dependency


async def limit_subject(bucket: str, subject: str, count: int, window_seconds: int) -> None:
    """The same, for something other than an address (a phone number): refuses with 429."""
    wait = await hit(bucket, subject, count, window_seconds)
    if wait is not None:
        raise refuse(wait)


async def _peek(bucket: str, subject: str, window_seconds: int) -> int:
    window = int(time.time() // window_seconds)
    try:
        value = await _redis().get(f"rl:{bucket}:{subject}:{window}")
    except Exception:  # noqa: BLE001
        return 0
    return int(value or 0)


async def hook_guard(request: Request):
    """For the addresses that carry a secret key (payment callbacks, the tracker forwarder). The senders are few and busy,
    so good requests are never counted; an address that keeps sending the wrong key is shut out, which stops anyone
    guessing the key."""
    if not settings.rate_limits_enabled:
        yield
        return
    ip = client_ip(request)
    if await _peek("wrong_key", ip, 600) >= WRONG_KEYS_PER_10_MIN:
        raise refuse(600)
    try:
        yield
    except HTTPException as e:
        if e.status_code == status.HTTP_403_FORBIDDEN:
            await hit("wrong_key", ip, WRONG_KEYS_PER_10_MIN, 600)
        raise


WRONG_KEYS_PER_10_MIN = 20
