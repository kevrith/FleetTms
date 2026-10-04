"""Standing security checks. They fail when someone adds a table, a route or a log line that has not been thought about, so
the review done for Sprint 16 does not quietly stop being true.

- every table that holds a business's data is scoped to that business, and the few that are not are named here;
- every route either needs a permission or is on a short, explained list of exceptions;
- every route that changes something either writes to the audit trail or is on a short, explained list of exceptions;
- no secret is committed and no personal data is written to a log.
"""

import ast
import importlib
import inspect
import pkgutil
import re
import subprocess
from pathlib import Path

import pytest
from fastapi.routing import APIRoute

import app as app_package
import app.routers as routers_package
from app.models import Base
from app.tenancy import TenantMixin
from tests.helpers import PASSWORD, bearer, owner_session

API_DIR = Path(__file__).resolve().parent.parent
REPO = API_DIR.parent.parent

# ---- tables -------------------------------------------------------------------------------------------------------------

# Tables that are deliberately not scoped to one business, and why.
GLOBAL_TABLES = {
    "businesses": "the tenants themselves",
    "users": "a person can belong to several businesses",
    "otp_challenges": "sign-in codes, looked up by phone before anyone is signed in",
    "device_logins": "quick sign-in devices, looked up before anyone is signed in",
    "sessions": "a session can move between a person's businesses; it carries its own business id",
    "breach_incidents": "the platform's own register of data breaches, seen only by platform admins",
    "partners": "the platform's own partner list; a partner sees only their own report",
    "partner_commissions": "what partners have earned; kept after the business that paid it is gone",
    "usage_counters": "counts of which parts of the product are used, keyed by a pseudonym: no person, no content",
}


def test_every_table_is_scoped_to_one_business_except_the_named_few():
    unscoped = {}
    for mapper in Base.registry.mappers:
        table = mapper.class_.__table__
        if not issubclass(mapper.class_, TenantMixin):
            unscoped[table.name] = "business_id" in table.columns
    assert set(unscoped) == set(GLOBAL_TABLES), f"a table is scoped differently from the review: {set(unscoped) ^ set(GLOBAL_TABLES)}"
    # a table that has a business_id column but is not filtered by it must be a named exception
    assert {name for name, has_column in unscoped.items() if has_column} <= set(GLOBAL_TABLES)


# ---- routes -------------------------------------------------------------------------------------------------------------


def all_routes():
    for module_info in pkgutil.iter_modules(routers_package.__path__):
        module = importlib.import_module(f"app.routers.{module_info.name}")
        for route in module.router.routes:
            if isinstance(route, APIRoute):
                yield module_info.name, module, route


def dependency_names(route, module):
    names = []

    def walk(dependant):
        for d in dependant.dependencies:
            names.append(getattr(d.call, "__qualname__", str(d.call)))
            walk(d)

    walk(route.dependant)
    names += [getattr(d.dependency, "__qualname__", "") for d in module.router.dependencies]
    return names


# Open to anyone on the internet, and what protects each one.
PUBLIC = {
    ("POST", "/auth/accept-invite"): "a one-time invitation token; rate limited",
    ("POST", "/auth/login"): "password and second step; lockout and rate limit",
    ("POST", "/auth/otp/request"): "answers the same for every number; limited per address and per phone",
    ("POST", "/auth/otp/verify"): "a five-attempt code; rate limited",
    ("POST", "/auth/quick-login"): "a device secret and a PIN; locks after five wrong PINs",
    ("POST", "/auth/refresh"): "a refresh token; rate limited",
    ("POST", "/auth/signup"): "creates a new business; limited to five an hour per address",
    ("POST", "/hooks/c2b/{business_id}/{key}/confirmation"): "a secret derived per business in the address; wrong keys shut an address out",
    ("POST", "/hooks/c2b/{business_id}/{key}/validation"): "the same",
    ("GET", "/media/{token}"): "a signed, expiring link; rate limited",
    ("GET", "/privacy/documents"): "only the names and versions of public documents",
    ("POST", "/hooks/subscription-pay/{key}"): "a derived secret, the checkout id and the amount are all checked",
    ("GET", "/plans"): "public prices",
    ("POST", "/hooks/traccar/{key}"): "a secret key in the address; wrong keys shut an address out",
    ("GET", "/track/{token}"): "an unguessable link that ends with the delivery; rate limited",
    ("GET", "/contact"): "how to reach support: a number and an address that are meant to be public; rate limited",
    ("POST", "/partners/apply"): "an application only: nothing is given out until a person approves it; five an hour per address",
    ("GET", "/partners/code/{code}"): "returns only a partner's trading name; rate limited",
    ("GET", "/partners/portal"): "a partner's private key in a header; sees only their own referrals; rate limited",
}

# Signed in but not tied to one permission, and why that is right.
SIGNED_IN_ONLY = {
    ("POST", "/auth/quick-login/disable"): "a person's own device",
    ("POST", "/auth/quick-login/enable"): "a person's own device",
    ("GET", "/auth/quick-login/status"): "a person's own device",
    ("POST", "/auth/switch-company"): "only between businesses the person already belongs to",
    ("POST", "/feedback"): "anyone may tell us what is wrong",
    ("POST", "/document-readings"): "every signed-in person may read a photo they uploaded; 200 a day",
    ("POST", "/document-readings/{reading_id}/confirm"): "checks the reader owns it or can manage vehicles inside",
    ("POST", "/document-readings/{reading_id}/reject"): "the same",
    ("POST", "/privacy/accept"): "a person accepting the documents shown to them",
    ("GET", "/report-catalog"): "each report is checked against the person's permissions inside",
    ("GET", "/report-catalog/{key}"): "the same",
    ("GET", "/report-catalog/{key}/export"): "the same",
    ("GET", "/subscription/banner"): "everyone should see a warning about the account",
    ("POST", "/me/data-requests"): "any person may ask their employer about their own data; it is always about themselves",
    ("GET", "/me/data-requests"): "a person sees only their own requests",
}

# Signed in but not through the second step yet, so only the routes that finish signing in.
BEFORE_SECOND_STEP = {
    ("POST", "/auth/2fa/confirm"),
    ("POST", "/auth/2fa/setup"),
    ("POST", "/auth/2fa/sms/confirm"),
    ("POST", "/auth/2fa/sms/setup"),
    ("POST", "/auth/logout"),
    ("POST", "/auth/logout-all"),
    ("GET", "/auth/me"),
}


def classify(route, module):
    names = dependency_names(route, module)
    if any(n.startswith("platform_admin") for n in names):
        return "platform_admin"
    if any(n.startswith(("require.", "require_any.")) for n in names):
        return "permission"
    if any(n.startswith("current_principal") for n in names):
        return "signed_in"
    if any("principal_unverified" in n for n in names):
        return "before_second_step"
    return "public"


def test_no_two_routes_share_a_method_and_path():
    """The second would silently replace the first: that once swapped a names-only list for a detailed one."""
    seen: dict = {}
    for name, _module, route in all_routes():
        for method in route.methods:
            assert (method, route.path) not in seen, f"{method} {route.path} is in both {seen[(method, route.path)]} and {name}"
            seen[(method, route.path)] = name


def test_every_route_needs_a_permission_or_is_on_the_reviewed_lists():
    found = {"public": {}, "signed_in": {}, "before_second_step": {}}
    for _, module, route in all_routes():
        kind = classify(route, module)
        if kind in found:
            for method in route.methods:
                found[kind][(method, route.path)] = True
    assert set(found["public"]) == set(PUBLIC), f"public routes changed: {set(found['public']) ^ set(PUBLIC)}"
    assert set(found["signed_in"]) == set(SIGNED_IN_ONLY), f"signed-in-only routes changed: {set(found['signed_in']) ^ set(SIGNED_IN_ONLY)}"
    assert set(found["before_second_step"]) == BEFORE_SECOND_STEP


def test_the_public_routes_that_take_a_secret_are_all_rate_limited():
    limited = {}
    for _, module, route in all_routes():
        for method in route.methods:
            if (method, route.path) in PUBLIC:
                names = dependency_names(route, module)
                limited[(method, route.path)] = any("ratelimit" in (getattr(d.call, "__module__", "") or "") for d in route.dependant.dependencies) or any(
                    n.startswith(("limit.", "hook_guard")) for n in names
                )
    unlimited = sorted(k for k, v in limited.items() if not v)
    assert unlimited == [("GET", "/plans"), ("GET", "/privacy/documents")]  # public information with nothing to guess


# ---- the audit trail ----------------------------------------------------------------------------------------------------


def _auditing_functions():
    out = set()
    for info in pkgutil.walk_packages(app_package.__path__, "app."):
        module = importlib.import_module(info.name)
        for name, fn in inspect.getmembers(module, inspect.isfunction):
            if fn.__module__ == module.__name__ and "audit.record" in inspect.getsource(fn):
                out.add((module.__name__, name))
    return out


def writes_to_the_audit_trail(route, module, auditing):
    """True if the route writes an audit entry itself or calls (one level down) a function that does."""
    source = inspect.getsource(route.endpoint)
    if "audit.record" in source:
        return True
    for owner, name in re.findall(r"(?:(\w+)\.)?(\w+)\(", source):
        target = getattr(getattr(module, owner, None), name, None) if owner else getattr(module, name, None)
        if inspect.isfunction(target) and target is not route.endpoint and (target.__module__, target.__name__) in auditing:
            return True
    return False


# Routes that change something but write no audit entry of their own, and why that is enough.
AUDIT_EXEMPT = {
    ("POST", "/ask/lookup"): "reads figures; changes nothing",
    ("POST", "/partners/apply"): "the application is the record: it is the platform's own, with no business",
    ("POST", "/platform/partners/{partner_id}/approve"): "the partner row records who approved it and when",
    ("POST", "/platform/partners/{partner_id}/commission"): "the partner row holds the share; each commission keeps the share it was earned at",
    ("POST", "/platform/partners/{partner_id}/payout"): "each commission records when it was paid and the payment's reference",
    ("POST", "/platform/partners/{partner_id}/reissue-key"): "replaces a credential; only its hash is kept",
    ("POST", "/platform/partners/{partner_id}/{action}"): "suspending or rejecting a partner: the platform's own list, no business involved",
    ("POST", "/platform/breaches"): "the register is the record: it is the platform's own, has no business, and keeps who made each entry and when",
    ("PATCH", "/platform/breaches/{breach_id}"): "the same",
    ("POST", "/auth/otp/request"): "asks for a code; the challenge row is the record and the sign-in that follows is audited",
    ("POST", "/quotes/preview"): "works a quote out without saving it",
    ("POST", "/auth/2fa/setup"): "only starts setting up; turning it on is audited as auth.2fa_enabled",
    ("POST", "/auth/2fa/sms/setup"): "the same",
    ("POST", "/auth/refresh"): "session housekeeping; each session is a row with its start and end",
    ("POST", "/auth/logout"): "the same",
    ("POST", "/auth/switch-company"): "moves between businesses the person already belongs to; the session records it",
    ("POST", "/onboarding/dismiss"): "hides the checklist card; no business record",
    ("POST", "/onboarding/restore"): "the same",
    ("POST", "/fraud/scan"): "runs the checks; each alert is its own record with its evidence",
    ("POST", "/fuel-prices/fetch"): "fetches public prices, stored with their source",
    ("POST", "/routes/suggest"): "looks up a route; nothing is saved",
    ("POST", "/imports/vehicles"): "every row created is audited by the function that creates it (vehicle.created)",
    ("POST", "/imports/staff"): "every person added is audited when they are invited",
    ("POST", "/trips/{trip_id}/locations"): "a stream of positions; the points are the record",
    ("POST", "/me/messages/{message_id}/read"): "the read receipt is on the message",
    ("POST", "/hooks/c2b/{business_id}/{key}/validation"): "Safaricom's pre-check; the confirmation is audited as mpesa.payment_received",
    ("POST", "/photos"): "the photo row records who uploaded it, when, and its checks",
    ("POST", "/report-schedules/{schedule_id}/send-now"): "the delivery is recorded on the schedule",
    ("POST", "/sos/{alert_id}/location"): "a stream of positions for an open alert",
    ("POST", "/hooks/traccar/{key}"): "a machine feed; every position and event is stored",
    ("POST", "/trips/{trip_id}/pod/code"): "texts a one-time code; the delivery record shows when it was confirmed",
    ("POST", "/tyres/{tyre_id}/tread"): "a measurement row that records who took it",
}


def test_every_route_that_changes_something_is_audited_or_explained():
    auditing = _auditing_functions()
    unaudited = {}
    for _, module, route in all_routes():
        for method in route.methods & {"POST", "PUT", "PATCH", "DELETE"}:
            if not writes_to_the_audit_trail(route, module, auditing):
                unaudited[(method, route.path)] = True
    assert set(unaudited) == set(AUDIT_EXEMPT), f"audit coverage changed: {sorted(set(unaudited) ^ set(AUDIT_EXEMPT))}"


async def audit_actions(client, owner, action):
    return (await client.get("/audit", params={"action": action}, headers=bearer(owner))).json()


async def test_editing_a_part_an_order_and_recalculating_payroll_are_audited(client):
    from tests.test_finance_payroll import MONTH, payroll_setup
    from tests.test_suppliers import order_body, part, supplier

    owner, _vehicle, _driver, _turnboy = await payroll_setup(client)
    p = await part(client, owner)
    res = await client.put(f"/parts/{p['id']}", headers=bearer(owner), json={"name": "Oil filter (big)", "unit": "pcs", "reorder_level": 9})
    assert res.status_code == 200, res.text
    (entry,) = await audit_actions(client, owner, "part.updated")
    assert entry["before"]["reorder_level"] == 4 and entry["after"]["reorder_level"] == 9
    assert entry["after"]["name"] == "Oil filter (big)"

    sup = await supplier(client, owner)
    order = (await client.post("/orders", headers=bearer(owner), json=order_body(sup))).json()
    res = await client.put(f"/orders/{order['id']}", headers=bearer(owner), json=order_body(sup, lines=[{"description": "Fan belt", "quantity": 1, "unit_cost_cents": 90_000}]))
    assert res.status_code == 200, res.text
    (entry,) = await audit_actions(client, owner, "order.updated")
    assert entry["before"]["lines"] == 2 and entry["after"]["lines"] == 1

    run = (await client.post("/payroll/runs", headers=bearer(owner), json={"month": MONTH()})).json()
    assert (await client.post(f"/payroll/runs/{run['id']}/recalculate", headers=bearer(owner))).status_code == 200
    (entry,) = await audit_actions(client, owner, "payroll.run_recalculated")
    assert entry["before"]["people"] == entry["after"]["people"] > 0


async def test_accepting_an_invitation_is_audited_in_the_business_that_invited(client):
    owner, _ = await owner_session(client)
    res = await client.post("/users", headers=bearer(owner), json={"name": "New Manager", "email": "new.manager@example.com", "roles": ["manager"]})
    assert res.status_code == 201, res.text
    accepted = await client.post("/auth/accept-invite", json={"token": res.json()["invite_token"], "password": PASSWORD})
    assert accepted.status_code == 204, accepted.text
    entries = await audit_actions(client, owner, "auth.invite_accepted")
    assert len(entries) == 1 and entries[0]["entity_type"] == "user"


# ---- secrets and personal data ------------------------------------------------------------------------------------------


def tracked_files():
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not inside a git checkout")
    return [REPO / p for p in out.decode().split("\0") if p]


SECRET_SHAPES = [
    re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA |)PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"\bxox[abp]-[A-Za-z0-9-]{20,}"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    re.compile(r"postgres(ql)?(\+\w+)?://[^:/\s@]+:(?![A-Z_]+@)[^@\s${}<>]{4,}@"),
]
ASSIGNED = re.compile(r"""(?i)\b(password|passwd|secret|api_?key|token|passkey|consumer_secret)\w*\s*[:=]\s*["']([A-Za-z0-9/+_\-]{16,})["']""")


def test_no_real_secret_is_committed():
    found = []
    for path in tracked_files():
        if path.suffix in {".png", ".jpg", ".jpeg", ".webp", ".ico", ".lock", ".svg", ".keystore", ".jar", ".zip", ".pdf", ".ttf", ".woff2"} or not path.is_file():
            continue
        if "node_modules" in path.parts or path.name in {"pnpm-lock.yaml"}:
            continue
        try:
            text = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        relative = path.relative_to(REPO)
        for shape in SECRET_SHAPES:
            if shape.search(text):
                found.append(f"{relative}: {shape.pattern[:30]}")
        if relative.parts[:2] != ("apps", "api") or "tests" not in relative.parts:
            for match in ASSIGNED.finditer(text):
                value = match.group(2)
                if not (value.startswith(("change", "your-", "see-")) or value.isupper() or "example" in value.lower()):
                    found.append(f"{relative}: {match.group(1)} assigned a literal")
    assert not found, "possible secrets: " + "; ".join(found)


def test_no_env_file_is_tracked():
    tracked = [p.relative_to(REPO).as_posix() for p in tracked_files()]
    assert [p for p in tracked if re.search(r"(^|/)\.env(\.|$)", p) and not p.endswith((".example", ".sample"))] == []
    ignored = (REPO / ".gitignore").read_text()
    assert re.search(r"(?m)^\.env\s*$", ignored)


PERSONAL = re.compile(r"(?i)phone|email|password|passwd|secret|token|otp|national_?id|id_?number|latitude|longitude|\blat\b|\blng\b|\blon\b|location")
LOG_METHODS = {"debug", "info", "warning", "warn", "error", "exception", "critical", "log"}


def _names_outside_masks(node):
    """Names used in an expression, leaving out anything passed through a mask_*() function (mask_phone, mask_email)."""
    if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")).startswith("mask_"):
        return []
    found = [node.id] if isinstance(node, ast.Name) else [node.attr] if isinstance(node, ast.Attribute) else []
    for child in ast.iter_child_nodes(node):
        found += _names_outside_masks(child)
    return found


def _development_only_lines(tree):
    """Lines inside `if settings.environment == "development":` - the API refuses to start in production with development
    settings, so what is printed there to make local work easier never runs where real people's data is."""
    lines = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and "environment" in ast.unparse(node.test) and "development" in ast.unparse(node.test):
            for inner in node.body:
                lines.update(range(inner.lineno, (inner.end_lineno or inner.lineno) + 1))
    return lines


def test_nothing_personal_is_written_to_a_log():
    offenders = []
    for path in sorted((API_DIR / "app").rglob("*.py")):
        tree = ast.parse(path.read_text())
        development = _development_only_lines(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in LOG_METHODS):
                continue
            target = node.func.value
            if not (isinstance(target, ast.Name) and target.id in {"log", "logger", "logging"}) or node.lineno in development:
                continue
            args = [*node.args[1:], *(k.value for k in node.keywords)]
            if node.args and isinstance(node.args[0], ast.JoinedStr):
                args.append(node.args[0])
            for arg in args:
                bad = [n for n in _names_outside_masks(arg) if PERSONAL.search(n)]
                if bad:
                    offenders.append(f"{path.relative_to(API_DIR)}:{node.lineno} logs {bad}")
    assert not offenders, offenders


async def test_the_setup_guide_leaves_an_audit_trail_for_what_it_creates(client):
    owner, _ = await owner_session(client)
    body = {"client_name": "Mwangi Cement", "billing_method": "per_tonne", "rate_cents": 300_000, "pickup": "Mombasa", "dropoff": "Nairobi", "distance_km": 480, "cargo_description": "Cement", "weight_tonnes": 30, "trips": 1}
    res = await client.post("/onboarding/first-job", headers=bearer(owner), json=body)
    assert res.status_code == 201, res.text
    for action in ("client.added", "route.added", "job.created"):
        assert len(await audit_actions(client, owner, action)) == 1, action
