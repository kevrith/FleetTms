"""Privacy-respecting product analytics (masterplan Section 7): which parts of the product are used, and where new businesses get stuck.

Two things, neither of which holds personal data:

* **Usage counts.** Each signed-in request adds one to a counter for (day, part of the product, business). The part is the first word of the
  address ("vehicles", "trips", "map"). The business is a pseudonym: a keyed hash that cannot be turned back into a name without the server's
  secret, and that is not stored anywhere else. No person, no IP address, no id, no record and no content is recorded, and support
  sessions are not counted. Counts are held in Redis for the day and written to the database once a day.
* **The sign-up funnel.** Worked out from the records the business already has (did it add a vehicle, invite someone, make a job, start a trip,
  raise an invoice, pay), so it needs no tracking at all. It is for the platform admin only.

`ANALYTICS_ENABLED=false` switches the counting off."""

import hashlib
import hmac
import logging
import re
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_sessionmaker
from app.models import (
    Business,
    Invoice,
    Job,
    Membership,
    SubscriptionInvoice,
    Trip,
    UsageCounter,
    Vehicle,
)

log = logging.getLogger("fleettms.analytics")

# Parts of the address that are not product features (account plumbing, machine feeds, public pages).
NOT_FEATURES = {"auth", "me", "health", "ready", "hooks", "media", "track", "plans", "privacy", "platform", "partners", "docs", "openapi.json", "redoc", "subscription", "feedback"}
_WORD = re.compile(r"^[a-z][a-z-]{1,29}$")
_clients: dict[int, Redis] = {}


def _redis() -> Redis:
    import asyncio

    key = id(asyncio.get_running_loop())
    if key not in _clients:
        _clients[key] = Redis.from_url(settings.redis_url)
    return _clients[key]


def feature_of(path: str) -> str | None:
    """The first word of an address, if it names a part of the product. Ids and anything else in the address are never looked at."""
    first = path.strip("/").split("/", 1)[0].lower()
    return first if _WORD.match(first) and first not in NOT_FEATURES else None


def business_key(business_id) -> str:
    """A pseudonym for a business: stable day to day (so we can count distinct businesses), meaningless without the server's secret."""
    return hmac.new(f"analytics:{settings.jwt_secret}".encode(), str(business_id).encode(), hashlib.sha256).hexdigest()[:12]


def _day_key(day: date) -> str:
    return f"usage:{day.isoformat()}"


async def note(principal, path: str) -> None:
    """Counts one request. Never raises and never waits on anything slow: a failure to count is not a failure to serve."""
    if not settings.analytics_enabled or principal.business_id is None or principal.support:
        return
    feature = feature_of(path)
    if feature is None:
        return
    try:
        redis = _redis()
        key = _day_key(datetime.now(UTC).date())
        async with redis.pipeline(transaction=False) as pipe:
            pipe.hincrby(key, f"{feature}:{business_key(principal.business_id)}", 1)
            pipe.expire(key, 10 * 86_400)
            await pipe.execute()
    except Exception:  # noqa: BLE001
        log.debug("Usage could not be counted")


async def flush(today: date | None = None) -> int:
    """Moves the counts of finished days from Redis into the database, adding to what is there so running it twice does no harm. Returns
    the number of counters written."""
    today = today or datetime.now(UTC).date()
    redis = Redis.from_url(settings.redis_url)
    written = 0
    try:
        async for raw in redis.scan_iter("usage:*"):
            key = raw.decode()
            day = date.fromisoformat(key.split(":", 1)[1])
            if day >= today:
                continue  # today is still being counted
            rows = await redis.hgetall(key)
            counters = []
            for field, value in rows.items():
                feature, _, who = field.decode().partition(":")
                counters.append({"day": day, "feature": feature, "business_key": who, "requests": int(value)})
            if counters:
                async with get_sessionmaker()() as db:
                    stmt = pg_insert(UsageCounter).values(counters)
                    await db.execute(stmt.on_conflict_do_update(index_elements=["day", "feature", "business_key"], set_={"requests": UsageCounter.requests + stmt.excluded.requests}))
                    await db.commit()
                written += len(counters)
            await redis.delete(key)  # only after the database has them
    finally:
        await redis.aclose()
    return written


async def usage_flush_job(ctx: dict) -> int:
    return await flush()


async def usage(db: AsyncSession, days: int = 30, today: date | None = None) -> dict:
    """Which parts of the product businesses use: for each, how many different businesses and how many requests, over the last `days`."""
    today = today or datetime.now(UTC).date()
    since = today - timedelta(days=days)
    features = (
        await db.execute(
            select(UsageCounter.feature, func.count(func.distinct(UsageCounter.business_key)), func.sum(UsageCounter.requests)).where(UsageCounter.day >= since).group_by(UsageCounter.feature).order_by(func.count(func.distinct(UsageCounter.business_key)).desc())
        )
    ).all()
    active = (await db.execute(select(UsageCounter.day, func.count(func.distinct(UsageCounter.business_key))).where(UsageCounter.day >= since).group_by(UsageCounter.day).order_by(UsageCounter.day))).all()
    total = (await db.execute(select(func.count(func.distinct(UsageCounter.business_key))).where(UsageCounter.day >= since))).scalar_one()
    return {
        "days": days, "businesses_active": int(total),
        "features": [{"feature": f, "businesses": int(b), "requests": int(r)} for f, b, r in features],
        "daily_active_businesses": [{"day": d, "businesses": int(n)} for d, n in active],
    }  # fmt: skip


STEPS = ("signed_up", "added_a_vehicle", "has_a_team", "made_a_job", "started_a_trip", "raised_an_invoice", "paying")
STEP_LABELS = {
    "signed_up": "Signed up", "added_a_vehicle": "Added a vehicle", "has_a_team": "Invited someone", "made_a_job": "Made a job",
    "started_a_trip": "Started a trip", "raised_an_invoice": "Raised an invoice", "paying": "Paid for a subscription",
}  # fmt: skip


def _all(stmt):
    return stmt.execution_options(skip_tenant=True)


async def funnel(db: AsyncSession, weeks: int = 12, today: date | None = None) -> dict:
    """Of the businesses that signed up in each recent week, how many got as far as each step, and how many are stuck at each. Sample data
    and complimentary accounts are left out: they say nothing about whether a real customer gets going."""
    today = today or datetime.now(UTC).date()
    since = datetime.combine(today - timedelta(weeks=weeks), datetime.min.time(), tzinfo=UTC)
    businesses = (await db.execute(select(Business.id, Business.created_at).where(Business.created_at >= since, Business.complimentary.is_(False)))).all()
    if not businesses:
        return {"weeks": weeks, "steps": [{"step": s, "label": STEP_LABELS[s], "businesses": 0, "stuck": 0, "share_pct": None} for s in STEPS], "cohorts": []}
    ids = {b for b, _ in businesses}

    async def distinct(stmt, column) -> set:
        return {r[0] for r in (await db.execute(_all(stmt.where(column.in_(ids))))).all()}

    reached = {
        "signed_up": ids,
        "added_a_vehicle": await distinct(select(Vehicle.business_id).where(Vehicle.is_sample.is_(False)).distinct(), Vehicle.business_id),
        "has_a_team": {b for (b, n) in (await db.execute(_all(select(Membership.business_id, func.count()).where(Membership.business_id.in_(ids)).group_by(Membership.business_id)))).all() if n >= 2},
        "made_a_job": await distinct(select(Job.business_id).where(Job.is_sample.is_(False)).distinct(), Job.business_id),
        "started_a_trip": await distinct(select(Trip.business_id).where(Trip.started_at.is_not(None)).distinct(), Trip.business_id),
        "raised_an_invoice": await distinct(select(Invoice.business_id).distinct(), Invoice.business_id),
        "paying": await distinct(select(SubscriptionInvoice.business_id).where(SubscriptionInvoice.kind == "subscription", SubscriptionInvoice.status == "paid").distinct(), SubscriptionInvoice.business_id),
    }
    steps = []
    for i, step in enumerate(STEPS):
        here = len(reached[step])
        stuck = len(reached[STEPS[i - 1]] - reached[step]) if i else 0  # got to the step before, and no further
        steps.append({"step": step, "label": STEP_LABELS[step], "businesses": here, "stuck": stuck, "share_pct": round(100 * here / len(ids), 1)})
    by_week: dict[date, list] = defaultdict(list)
    for b, created in businesses:
        by_week[(created.date() - timedelta(days=created.weekday()))].append(b)
    cohorts = [{"week": week, "signed_up": len(members), **{s: sum(1 for m in members if m in reached[s]) for s in STEPS[1:]}} for week, members in sorted(by_week.items())]
    return {"weeks": weeks, "steps": steps, "cohorts": cohorts}
