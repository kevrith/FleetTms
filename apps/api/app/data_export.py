"""Full data export for owners (masterplan Section 3 and 11): everything the business has in the system, as a zip of CSV files (one per kind
of record) with a README and a manifest, and optionally the photos. It is the owner's data, so it is always available, even when an account
is read-only. Secrets are never included: no password or token hashes, no two-step keys."""

import csv
import io
import json
import logging
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import storage
from app.db import get_sessionmaker
from app.models import Base, Business, DataExport, Membership
from app.tenancy import current_business_id

log = logging.getLogger(__name__)
SKIP_TABLES = {"data_exports"}
SECRET_WORDS = ("password", "secret", "hash", "totp")
KEEP_DAYS = 7
PHOTO_LIMIT_BYTES = 2 * 1024**3  # stop adding photos past 2 GB and say so in the manifest


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str, separators=(",", ":"))
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, (Decimal, uuid.UUID)):
        return str(value)
    return value


def tables_to_export():
    """Every table that holds a business's records, in alphabetical order."""
    return sorted((t for t in Base.metadata.tables.values() if "business_id" in t.c and t.name not in SKIP_TABLES), key=lambda t: t.name)


def safe_columns(table) -> list[str]:
    return [c.name for c in table.c if not any(w in c.name for w in SECRET_WORDS)]


def storage_key(business_id: uuid.UUID, export_id: uuid.UUID) -> str:
    return f"exports/{business_id}/{export_id}.zip"


async def build(db: AsyncSession, export: DataExport) -> dict:
    """Writes the zip. Returns how many rows went into each file."""
    business_id = current_business_id.get()
    key = storage_key(business_id, export.id)
    path = storage._safe_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    photos = {"included": 0, "skipped": 0, "bytes": 0}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for table in tables_to_export():
            columns = safe_columns(table)
            buffer = io.StringIO(newline="")
            writer = csv.writer(buffer)
            writer.writerow(columns)
            n = 0
            result = await db.stream(select(*[table.c[c] for c in columns]).where(table.c.business_id == business_id))
            async for row in result:
                writer.writerow([_cell(v) for v in row])
                n += 1
            counts[table.name] = n
            if n:
                zf.writestr(f"{table.name}.csv", buffer.getvalue())
        business = (await db.execute(select(Business).where(Business.id == business_id))).scalar_one()
        zf.writestr("business.csv", _single_csv(["id", "name", "kra_pin", "fuel_region", "created_at"], [[business.id, business.name, business.kra_pin, business.fuel_region, business.created_at]]))
        people = []
        for m in (await db.execute(select(Membership))).scalars():
            people.append([m.id, m.user.name, m.user.email, m.user.phone, ";".join(sorted(r.role.value for r in m.roles)), m.status.value, m.created_at])
        zf.writestr("people.csv", _single_csv(["membership_id", "name", "email", "phone", "roles", "status", "joined"], people))
        counts["people"] = len(people)
        if export.include_photos:
            for pid, skey, ctype in (await db.execute(select(Base.metadata.tables["photos"].c.id, Base.metadata.tables["photos"].c.storage_key, Base.metadata.tables["photos"].c.content_type).where(Base.metadata.tables["photos"].c.business_id == business_id))).all():
                src = storage.read_path(skey)
                if src is None or photos["bytes"] + src.stat().st_size > PHOTO_LIMIT_BYTES:
                    photos["skipped"] += 1
                    continue
                zf.write(src, f"photos/{pid}.{ctype.split('/')[-1].replace('jpeg', 'jpg')}")
                photos["included"] += 1
                photos["bytes"] += src.stat().st_size
        manifest = {"business": business.name, "made_at": datetime.now(UTC).isoformat(), "rows": counts, "photos": photos if export.include_photos else None}
        zf.writestr("manifest.json", json.dumps(manifest, indent=1))
        zf.writestr("README.txt", readme(business.name, counts, export.include_photos, photos))
    export.storage_key, export.size_bytes = key, path.stat().st_size
    return counts


def _single_csv(header: list[str], rows: list[list]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(header)
    for row in rows:
        writer.writerow([_cell(v) for v in row])
    return buffer.getvalue()


def readme(name: str, counts: dict, photos: bool, photo_info: dict) -> str:
    lines = [
        f"FleetTms: a full copy of the data of {name}", "",
        "Each .csv file is one kind of record (vehicles, trips, fuel_entries, expenses, invoices, ...), with a header row. Times are in UTC.",
        "Money is in cents (divide by 100 for shillings). Ids are UUIDs and link records together (a trip's vehicle_id is a vehicle's id).",
        "Lists and details are stored as JSON text inside a cell. Passwords, tokens and two-step keys are never included.",
        "people.csv lists everyone with access, and business.csv the business itself. manifest.json counts the rows in each file.", "",
        "Files and how many records each holds:",
    ]  # fmt: skip
    lines += [f"  {t}.csv: {n}" for t, n in sorted(counts.items()) if n]
    lines.append("")
    lines.append(f"Photos: {photo_info['included']} included in the photos folder, named by photo id (see photos.csv)." + (f" {photo_info['skipped']} were left out (too large or missing)." if photo_info["skipped"] else "") if photos else "Photos were not included in this copy. Ask for a copy with photos if you need them.")
    return "\n".join(lines) + "\n"


async def run(business_id: uuid.UUID, export_id: uuid.UUID) -> None:
    """The background job: builds the export in its own session and records how it went."""
    async with get_sessionmaker()() as db:
        current_business_id.set(business_id)
        try:
            export = (await db.execute(select(DataExport).where(DataExport.id == export_id))).scalar_one()
            export.status = "running"
            await db.commit()
            try:
                export.tables = await build(db, export)
                export.status, export.ready_at, export.expires_at = "ready", datetime.now(UTC), datetime.now(UTC) + timedelta(days=KEEP_DAYS)
            except Exception:
                log.exception("A data export failed")
                export.status, export.error = "failed", "The copy could not be made. Please try again."
            await db.commit()
        finally:
            current_business_id.set(None)


async def purge_expired() -> int:
    """Deletes copies older than a week: they hold everything, so they are not kept around."""
    removed = 0
    async with get_sessionmaker()() as db:
        for e in (await db.execute(select(DataExport).where(DataExport.status == "ready", DataExport.expires_at < datetime.now(UTC)).execution_options(skip_tenant=True))).scalars().all():
            path = storage.read_path(e.storage_key) if e.storage_key else None
            if path is not None:
                path.unlink(missing_ok=True)
            current_business_id.set(e.business_id)  # a change is made inside the business it belongs to
            e.status, e.storage_key = "expired", None
            await db.flush()
            removed += 1
        current_business_id.set(None)
        await db.commit()
    return removed


async def data_export_purge_job(ctx: dict) -> int:
    return await purge_expired()
