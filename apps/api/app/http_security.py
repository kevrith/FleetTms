"""Protections that apply to every request: response headers, a cap on request size, a backstop rate limit, and a check
that a production deployment is not running with development settings."""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app import ratelimit
from app.config import Settings, settings

MAX_REQUEST_BYTES = 12 * 1024 * 1024  # a photo is at most 8 MB; the biggest JSON body (an offline sync batch) is far smaller

# Paths whose senders are few machines posting a lot (trackers, Safaricom): they have their own protection, a key in the address.
UNLIMITED_PREFIXES = ("/hooks/", "/health", "/ready")


class SecurityHeaders:
    """Adds the headers that stop a browser guessing content types, framing the app, leaking the address a person came
    from, or keeping an answer that holds someone's business. Whatever a route sets itself is left alone."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in {
                    "X-Content-Type-Options": "nosniff",
                    "X-Frame-Options": "DENY",
                    "Referrer-Policy": "no-referrer",
                    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
                    "Cache-Control": "no-store",
                }.items():
                    if name not in headers:
                        headers[name] = value
                if settings.environment == "production" and "Strict-Transport-Security" not in headers:
                    headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
            await send(message)

        await self.app(scope, receive, with_headers)


class RequestLimits:
    """Refuses a body that says it is bigger than MAX_REQUEST_BYTES, and an address that is sending far more than any person
    could (a script hammering the API). Real sign-in and code limits are on their own routes."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.lower(): v for k, v in scope["headers"]}
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            declared = 0
        if declared > MAX_REQUEST_BYTES:
            await _refuse(send, 413, "too_large", "That request is too large.")
            return
        path = scope["path"]
        if not path.startswith(UNLIMITED_PREFIXES):
            from starlette.requests import Request

            wait = await ratelimit.hit("all", ratelimit.client_ip(Request(scope)), settings.rate_limit_per_minute, 60)
            if wait is not None:
                await _refuse(send, 429, "rate_limited", f"Too many requests. Try again in {wait} seconds.", {"Retry-After": str(wait)})
                return
        await self.app(scope, receive, send)


async def _refuse(send: Send, status_code: int, code: str, message: str, extra: dict | None = None) -> None:
    import json

    body = json.dumps({"detail": {"code": code, "message": message}}).encode()
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    headers += [(k.lower().encode(), v.encode()) for k, v in (extra or {}).items()]
    await send({"type": "http.response.start", "status": status_code, "headers": headers})
    await send({"type": "http.response.body", "body": body})


def production_problems(s: Settings, *, sms_is_stand_in: bool) -> list[str]:
    """What is wrong with these settings for a live deployment. Empty means nothing is, as far as settings can tell."""
    problems = []
    if len(s.jwt_secret) < 32:
        problems.append("JWT_SECRET must be set to a random value of at least 32 characters.")
    origins = [o.strip() for o in s.cors_origins.split(",") if o.strip()]
    if not origins or any(o == "*" or "localhost" in o or "127.0.0.1" in o or not o.startswith("https://") for o in origins):
        problems.append("CORS_ORIGINS must list only the real https:// addresses of the web app.")
    if not s.public_api_url.startswith("https://"):
        problems.append("PUBLIC_API_URL must be the https:// address the payment callbacks and trackers reach.")
    if not (s.enforce_plans and s.enforce_billing):
        problems.append("ENFORCE_PLANS and ENFORCE_BILLING must be on.")
    if not s.rate_limits_enabled:
        problems.append("RATE_LIMITS_ENABLED must be on.")
    if "fake" in (s.document_reader, s.ask_llm):
        problems.append("DOCUMENT_READER and ASK_LLM must not be the test stand-ins.")
    if sms_is_stand_in:
        problems.append("Text messages still go to the in-memory stand-in: sign-in codes would never reach anyone.")
    return problems


def check_production() -> None:
    """Called when the API starts. A development setting in production is a reason not to start, not a warning."""
    if settings.environment != "production":
        return
    from app.sms import FakeSmsSender, get_sms_sender

    inner = getattr(get_sms_sender(), "inner", get_sms_sender())
    problems = production_problems(settings, sms_is_stand_in=isinstance(inner, FakeSmsSender))
    if problems:
        raise RuntimeError("Refusing to start in production:\n- " + "\n- ".join(problems))
