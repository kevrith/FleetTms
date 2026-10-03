from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from app.config import settings
from app.db import database_is_up
from app.routers import (
    audit_log,
    auth,
    behaviour,
    clients,
    dashboard,
    debtors,
    depots,
    devices,
    documents,
    etims,
    expenses,
    finance,
    floats,
    fuel,
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
    parts,
    payments,
    payroll,
    photos,
    portal,
    privacy,
    profit,
    quotes,
    reconciliation,
    report_schedules,
    sos,
    staff,
    statements,
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

app = FastAPI(title="FleetTms API", version=settings.version)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (auth, users, depots, vehicles, staff, documents, imports, photos, inspections, trips, fuel, floats, devices, sync, expenses, reconciliation, workshop, dashboard, tyres, parts, incidents, sos, clients, quotes, jobs, invoices, payments, statements, debtors, etims, leases, finance, payroll, suppliers, profit, portal, locations, livemap, tracking_links, trackers, geofences, behaviour, immobiliser, report_schedules, audit_log, privacy, support):
    app.include_router(module.router)


async def redis_is_up() -> bool:
    client = Redis.from_url(settings.redis_url)
    try:
        return bool(await client.ping())
    except Exception:  # noqa: BLE001 - any failure means "down"
        return False
    finally:
        await client.aclose()


@app.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.version,
        "database": "up" if await database_is_up() else "down",
        "redis": "up" if await redis_is_up() else "down",
    }
