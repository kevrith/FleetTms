"""Is the system able to do its job right now? This is what an uptime monitor asks (`GET /ready`), and what the on-call person looks at first.

`/health` says the process is alive. `/ready` says everything it depends on is working: the database (and that it has all migrations),
Redis, file storage (a test file is written, read back and removed), the background worker (it writes a heartbeat every minute), and the backups (a recent base backup, and the newest write-ahead log segment
shipped within the recovery point target). A check that cannot be made on this deployment says "not configured" and does not fail it.
It returns only yes or no and short reasons: no customer data, no addresses, no names."""

import logging
import time
from datetime import UTC, datetime
from pathlib import Path

from redis.asyncio import Redis
from sqlalchemy import text

from app import storage
from app.config import settings
from app.db import get_sessionmaker

log = logging.getLogger("fleettms.readiness")
HEARTBEAT_KEY = "worker:heartbeat"
EMPTY_SEGMENT_BYTES = 64  # a WAL segment that has only its header: nothing has been written since the last one was shipped


async def beat() -> None:
    redis = Redis.from_url(settings.redis_url)
    try:
        await redis.set(HEARTBEAT_KEY, str(int(time.time())), ex=600)
    finally:
        await redis.aclose()


def head_revision() -> str:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    api_dir = Path(__file__).resolve().parent.parent
    config = Config(str(api_dir / "alembic.ini"))
    config.set_main_option("script_location", str(api_dir / "migrations"))
    return ScriptDirectory.from_config(config).get_current_head()


async def check_database() -> dict:
    try:
        async with get_sessionmaker()() as db:
            await db.execute(text("SELECT 1"))
            current = (await db.execute(text("SELECT version_num FROM alembic_version"))).scalar_one_or_none()
    except Exception:  # noqa: BLE001 - any failure means "not ready"
        return {"ok": False, "reason": "the database cannot be reached"}
    if current != head_revision():
        return {"ok": False, "reason": "the database is not on the latest migration"}
    return {"ok": True}


async def check_redis() -> dict:
    redis = Redis.from_url(settings.redis_url)
    try:
        return {"ok": bool(await redis.ping())}
    except Exception:  # noqa: BLE001
        return {"ok": False, "reason": "Redis cannot be reached"}
    finally:
        await redis.aclose()


async def check_storage() -> dict:
    """Photos and data copies can be written and read back (the folder, or the bucket with the keys it was given)."""
    result = await storage.probe()
    if result["ok"]:
        return {"ok": True, "backend": result["backend"]}
    return {"ok": False, "reason": "files cannot be stored or read: " + result.get("error", "the test file did not come back")}


async def check_worker() -> dict:
    redis = Redis.from_url(settings.redis_url)
    try:
        value = await redis.get(HEARTBEAT_KEY)
    except Exception:  # noqa: BLE001
        return {"ok": False, "reason": "Redis cannot be reached"}
    finally:
        await redis.aclose()
    if value is None:
        return {"ok": False, "reason": "the background worker has not reported"}
    age = int(time.time()) - int(value)
    if age > settings.worker_heartbeat_max_seconds:
        return {"ok": False, "reason": f"the background worker last reported {age} seconds ago"}
    return {"ok": True, "age_seconds": age}


def check_base_backup(now: float | None = None) -> dict:
    if not settings.backup_dir:
        return {"ok": True, "state": "not configured"}
    files = sorted(Path(settings.backup_dir, "base").glob("*.tar.gz"))
    if not files:
        return {"ok": False, "reason": "there is no base backup"}
    age_hours = ((now or time.time()) - files[-1].stat().st_mtime) / 3600
    if age_hours > settings.backup_max_age_hours:
        return {"ok": False, "reason": f"the newest base backup is {age_hours:.0f} hours old"}
    return {"ok": True, "age_hours": round(age_hours, 1)}


async def check_wal_archive() -> dict:
    """The newest write-ahead log segment shipped to the archive. If there is unshipped WAL, its age is the most data a crash right now
    would lose. A quiet database has nothing unshipped, however long ago the last segment went: that is not a failure."""
    try:
        async with get_sessionmaker()() as db:
            row = (
                await db.execute(
                    text("SELECT current_setting('archive_mode'), last_archived_time, last_failed_time, (pg_walfile_name_offset(pg_current_wal_lsn())).file_offset FROM pg_stat_archiver")
                )
            ).one()
    except Exception:  # noqa: BLE001
        return {"ok": False, "reason": "the archive status cannot be read"}
    mode, last, failed, offset = row
    if mode != "on":
        return {"ok": True, "state": "not configured"}
    if failed is not None and (last is None or failed >= last):
        return {"ok": False, "reason": "the latest archive attempt failed"}
    if last is None:
        return {"ok": False, "reason": "nothing has been archived yet"}
    age_minutes = (datetime.now(UTC) - last).total_seconds() / 60
    nothing_unshipped = offset is not None and offset <= EMPTY_SEGMENT_BYTES
    if age_minutes > settings.wal_max_age_minutes and not nothing_unshipped:
        return {"ok": False, "reason": f"the newest archived segment is {age_minutes:.0f} minutes old and newer changes are waiting"}
    return {"ok": True, "age_minutes": round(age_minutes, 1), "unshipped": not nothing_unshipped}


async def readiness() -> dict:
    checks = {
        "database": await check_database(),
        "redis": await check_redis(),
        "storage": await check_storage(),
        "worker": await check_worker(),
        "base_backup": check_base_backup(),
        "wal_archive": await check_wal_archive(),
    }
    failing = [name for name, c in checks.items() if not c["ok"]]
    if failing:
        log.warning("Not ready: %s", ", ".join(failing))
    return {"ready": not failing, "failing": failing, "checks": checks, "version": settings.version}
