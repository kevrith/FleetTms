"""Tenant isolation, checked broadly rather than one endpoint at a time.

1. every model that belongs to a business is filtered by it on every read, whatever the query looks like;
2. only a short, reviewed list of files may switch the filter off;
3. a second business asking for the first one's records by id, on every route that takes one, never gets them.
"""

import importlib
import pkgutil
import re
import uuid
from pathlib import Path

from fastapi.routing import APIRoute
from sqlalchemy import event, func, select
from sqlalchemy.orm import aliased

import app.routers as routers_package
from app.db import get_engine, get_sessionmaker
from app.models import Base
from app.tenancy import TenantMixin, current_business_id
from tests.helpers import bearer, owner_session
from tests.shots import fleet, make_trip

APP_DIR = Path(__file__).resolve().parent.parent / "app"


def tenant_models():
    return sorted((m.class_ for m in Base.registry.mappers if issubclass(m.class_, TenantMixin)), key=lambda c: c.__name__)


async def test_every_model_that_belongs_to_a_business_is_filtered_by_it_however_it_is_queried(client):
    seen: list[str] = []
    engine = get_engine().sync_engine

    def capture(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    current_business_id.set(uuid.uuid4())
    try:
        async with get_sessionmaker()() as db:
            for model in tenant_models():
                table = model.__table__.name
                statements = {
                    "select": select(model).limit(1),
                    "count": select(func.count()).select_from(model),
                    "alias": select(aliased(model)).limit(1),
                    "column": select(model.business_id).limit(1),
                }
                for kind, statement in statements.items():
                    seen.clear()
                    await db.execute(statement)
                    sql = " ".join(seen)
                    assert re.search(rf"{table}\.business_id = ", sql) or re.search(r"business_id = \$\d", sql) or "business_id = %" in sql, f"{table} ({kind}) was read without the business filter: {sql[:200]}"
    finally:
        current_business_id.set(None)
        event.remove(engine, "before_cursor_execute", capture)


# Files allowed to read across businesses with `skip_tenant`, and why. Anything new must be reviewed and added here.
MAY_SKIP_THE_FILTER = {
    "tenancy.py": "defines it",
    "auth_service.py": "signing in happens before a business is chosen",
    "routers/auth.py": "signing in, choosing a business, accepting an invitation",
    "routers/beta.py": "platform admin reads all feedback; the signed-in count of one business uses its own filter",
    "routers/platform_console.py": "platform admin sees customers; every action is written to the business's own audit trail",
    "routers/subscription.py": "the payment callback finds the invoice before any business is known",
    "routers/tracking_links.py": "a client opens a tracking link with no account",
    "tracker_ingest.py": "a tracker is found by its device id before its business is known",
    "tracking_jobs.py": "scheduled jobs that work across every business and then set the business for each row",
    "data_export.py": "deleting expired copies across businesses; the export itself runs inside one business",
    "analytics.py": "the sign-up funnel counts which businesses have done what, across businesses: counts only, never records",
    "partners.py": "a partner's report counts a referred business's subscription and vehicles across businesses: its name, state and size only",
    "retention.py": "the daily retention job works across every business, one at a time, and sets the business for each",
}


def test_only_reviewed_files_can_switch_the_tenant_filter_off():
    users = {p.relative_to(APP_DIR).as_posix() for p in APP_DIR.rglob("*.py") if "skip_tenant" in p.read_text()}
    assert users == set(MAY_SKIP_THE_FILTER), f"who may skip the filter changed: {users ^ set(MAY_SKIP_THE_FILTER)}"


def test_no_hand_written_sql_reads_business_data():
    """Raw SQL is not filtered by business. The few text() uses are column defaults and index conditions in models.py and a ping."""
    offenders = []
    for path in APP_DIR.rglob("*.py"):
        if path.name in ("models.py", "readiness.py"):  # readiness reads the migration version and the archive status: system tables, no business data
            continue
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if re.search(r"\btext\(\s*f?[\"']", line) and "SELECT 1" not in line and "set_config(" not in line:
                offenders.append(f"{path.relative_to(APP_DIR)}:{number}")
            if "exec_driver_sql" in line:
                offenders.append(f"{path.relative_to(APP_DIR)}:{number}")
    assert offenders == []


# ---- another business asking for these records by id ---------------------------------------------------------------------

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def routes_taking_one_id(methods):
    for info in pkgutil.iter_modules(routers_package.__path__):
        module = importlib.import_module(f"app.routers.{info.name}")
        for route in module.router.routes:
            if not isinstance(route, APIRoute):
                continue
            params = re.findall(r"{(\w+)}", route.path)
            if len(params) == 1 and params[0].endswith("id") and route.methods & methods:
                yield route.path, min(route.methods & methods), params[0]


async def harvest(client, tokens) -> set[str]:
    """Every id the first business can see, from every list screen that needs no arguments."""
    ids: set[str] = set()
    for info in pkgutil.iter_modules(routers_package.__path__):
        module = importlib.import_module(f"app.routers.{info.name}")
        for route in module.router.routes:
            if isinstance(route, APIRoute) and "GET" in route.methods and "{" not in route.path and route.path.startswith("/") and "/hooks/" not in route.path:
                if route.path.startswith(("/platform", "/auth", "/media", "/track")):
                    continue
                res = await client.get(route.path, headers=bearer(tokens))
                if res.status_code == 200:
                    ids.update(UUID.findall(res.text))
    return ids


async def test_a_second_business_cannot_read_or_delete_the_first_ones_records_by_id_anywhere(client):
    f = await fleet(client)
    await make_trip(client, f)
    await client.post("/depots", headers=bearer(f.owner), json={"name": "Alpha Yard"})
    await client.post("/clients", headers=bearer(f.owner), json={"name": "Mwangi Cement", "billing_method": "per_tonne", "rate_cents": 300_000})
    await client.post("/suppliers", headers=bearer(f.owner), json={"name": "Kiambu Spares", "phone": "0712345678", "category": "spares"})
    await client.post("/parts", headers=bearer(f.owner), json={"name": "Oil filter", "reorder_level": 3})
    own_ids = await harvest(client, f.owner)
    assert len(own_ids) >= 12, "the first business needs real data for this check to mean anything"

    other, _ = await owner_session(client, "Bravo Transporters", "b@example.com")
    # the second business has made nothing, so any record of the first that its own screens show is already a leak
    seen_by_other = await harvest(client, other)
    assert own_ids & seen_by_other == set(), "a list screen showed another business's records"
    stolen = sorted(own_ids)

    leaks, tried = [], 0
    for path, method, _name in [*routes_taking_one_id({"GET"}), *routes_taking_one_id({"DELETE"})]:
        for record_id in stolen:
            res = await client.request(method, path.replace("{" + _name + "}", record_id), headers=bearer(other))
            tried += 1
            if res.status_code < 300:
                leaked = [i for i in UUID.findall(res.text) if i in stolen]
                if method == "DELETE" or leaked:
                    leaks.append(f"{method} {path} {res.status_code}")
    assert tried > 1000
    assert leaks == [], leaks[:10]

    # and none of the deletes that were tried took anything from the first business
    assert own_ids <= await harvest(client, f.owner)
