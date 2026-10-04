from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from app.config import settings
from app.db import database_is_up
from app.deps import feature
from app.http_security import RequestLimits, SecurityHeaders, check_production
from app.routers import (
    ask,
    audit_log,
    auth,
    behaviour,
    beta,
    breaches,
    clients,
    dashboard,
    data_exports,
    data_requests,
    debtors,
    depots,
    devices,
    document_readings,
    documents,
    etims,
    expenses,
    finance,
    floats,
    fraud,
    fuel,
    fuel_prices,
    fuel_sensor,
    geofences,
    immobiliser,
    imports,
    incidents,
    inspections,
    invoices,
    jobs,
    leases,
    livemap,
    locations,
    messages,
    parts,
    payments,
    payroll,
    photos,
    platform_console,
    portal,
    predictions,
    privacy,
    profit,
    quotes,
    reconciliation,
    report_catalog,
    report_schedules,
    scorecards,
    sos,
    staff,
    statements,
    subscription,
    suppliers,
    support,
    sync,
    trackers,
    tracking_links,
    trips,
    tyres,
    users,
    vehicles,
    workshop,
)

check_production()  # a live deployment with development settings does not start

app = FastAPI(title="FleetTms API", version=settings.version)
app.add_middleware(SecurityHeaders)
app.add_middleware(RequestLimits)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

GATED = {
    geofences: "geofences", scorecards: "scorecards", tyres: "tyres_parts", parts: "tyres_parts", etims: "etims", behaviour: "replay", immobiliser: "immobiliser",
    predictions: "predictions", fuel_sensor: "fuel_sensors", report_schedules: "scheduled_reports", ask: "ask",
}  # fmt: skip  (a whole router that belongs to one plan)

for module in (breaches, data_requests, data_exports, ask, report_catalog, messages, platform_console, subscription, beta, document_readings, fraud, fuel_prices, fuel_sensor, predictions, scorecards, auth, users, depots, vehicles, staff, documents, imports, photos, inspections, trips, fuel, floats, devices, sync, expenses, reconciliation, workshop, dashboard, tyres, parts, incidents, sos, clients, quotes, jobs, invoices, payments, statements, debtors, etims, leases, finance, payroll, suppliers, profit, portal, locations, livemap, tracking_links, trackers, geofences, behaviour, immobiliser, report_schedules, audit_log, privacy, support):
    app.include_router(module.router, dependencies=[Depends(feature(GATED[module]))] if module in GATED else None)


async def redis_is_up() -> bool:
    client = Redis.from_url(settings.redis_url)
    try:
        return bool(await client.ping())
    except Exception:  # noqa: BLE001 - any failure means "down"
        return False
    finally:
        await client.aclose()


@app.get("/ready")
async def ready():
    """Everything the system depends on, for an uptime monitor: 200 when all is well, 503 with the reasons when not (readiness.py)."""
    from fastapi.responses import JSONResponse

    from app.readiness import readiness

    result = await readiness()
    return JSONResponse(result, status_code=200 if result["ready"] else 503)


@app.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.version,
        "database": "up" if await database_is_up() else "down",
        "redis": "up" if await redis_is_up() else "down",
    }
