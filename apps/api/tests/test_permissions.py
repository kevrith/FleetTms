"""Each role's access must match the masterplan Section 3 table."""

import pytest

from app.models import Role
from app.permissions import ROLE_PERMISSIONS, permissions_for
from tests.helpers import bearer, driver_session, owner_session, staff_session

# endpoint -> (method, path, json, permission needed)
CHECKS = {
    "list_users": ("GET", "/users", None, "users.view"),
    "invite_user": ("POST", "/users", {"name": "New Person", "email": "new@example.com", "roles": ["manager"]}, "users.manage"),
    "list_depots": ("GET", "/depots", None, "depots.view"),
    "create_depot": ("POST", "/depots", {"name": "Yard"}, "depots.manage"),
    "audit": ("GET", "/audit", None, "audit.view"),
    "list_vehicles": ("GET", "/vehicles", None, "vehicles.view"),
    "create_party": ("POST", "/parties", {"kind": "lessor", "name": "Some Lessor"}, "vehicles.manage"),
    "add_tyre": ("POST", "/tyres", {"serial": "PERM1234", "brand": "Michelin", "size": "315/80R22.5"}, "workshop.manage"),
    "list_parts": ("GET", "/parts", None, "workshop.manage"),
    "list_claims": ("GET", "/claims", None, "incidents.manage"),
    "fines_summary": ("GET", "/fines/summary", None, "incidents.manage"),
    "list_clients": ("GET", "/clients", None, "clients.manage"),
    "list_quotes": ("GET", "/quotes", None, "clients.manage"),
    "list_jobs": ("GET", "/jobs", None, "trips.view"),
    "dispatch_calendar": ("GET", "/dispatch/calendar", None, "trips.view"),
    "list_invoices": ("GET", "/invoices", None, "invoices.manage"),
    "live_map": ("GET", "/map/vehicles", None, "livemap.view"),
    "tracking_gaps": ("GET", "/map/gaps", None, "livemap.view"),
    "list_trackers": ("GET", "/trackers", None, "livemap.view"),
    "tracker_alerts": ("GET", "/tracker/alerts", None, "livemap.view"),
    "list_geofences": ("GET", "/geofences", None, "livemap.view"),
    "geofence_events": ("GET", "/geofences/events", None, "livemap.view"),
    "create_geofence": ("POST", "/geofences", {"name": "Yard", "kind": "depot", "shape": {"type": "circle", "lat": -1.29, "lng": 36.82, "radius_m": 300}, "alert_on": ["enter"]}, "geofences.manage"),
    "behaviour_events": ("GET", "/behaviour/events", None, "livemap.view"),
    "behaviour_summary": ("GET", "/behaviour/summary", None, "livemap.view"),
    "list_leases": ("GET", "/leases", None, "finance.view"),
    "list_loans": ("GET", "/finance", None, "finance.view"),
    "list_ownership_costs": ("GET", "/ownership-costs", None, "finance.view"),
    "profit": ("GET", "/profit", None, "finance.view"),
    "payroll_runs": ("GET", "/payroll/runs", None, "payroll.view"),
    "list_suppliers": ("GET", "/suppliers", None, "workshop.manage"),
    "my_leases": ("GET", "/portal/leases", None, "lease.view_own"),
    "list_sos": ("GET", "/sos", None, "sos.respond"),
    "list_report_schedules": ("GET", "/report-schedules", None, "reports.schedule"),
    "list_staff": ("GET", "/staff", None, "staff.view"),
    "list_trips": ("GET", "/trips", None, "trips.view"),
    "my_trips": ("GET", "/me/trips", None, "trips.own"),
    "list_expenses": ("GET", "/expenses", None, "expenses.view"),
    "import_template": ("GET", "/imports/staff/template", None, "data.import"),
    "grant_support": ("POST", "/support/grants", {"hours": 1, "reason": "help"}, "support.grant"),
}


async def session_for(client, owner, role):
    if role in (Role.DRIVER, Role.TURNBOY):
        return await driver_session(client, owner, "0712345678" if role == Role.DRIVER else "0722345678", role=role.value)
    if role == Role.LESSOR:
        party = await client.post("/parties", headers=bearer(owner), json={"kind": "lessor", "name": "Wanjiku Transporters"})
        assert party.status_code == 201, party.text
        res = await client.post("/users", headers=bearer(owner), json={"name": "Lessor user", "email": "lessor@example.com", "roles": ["lessor"], "party_id": party.json()["id"]})
        assert res.status_code == 201, res.text
        from tests.helpers import PASSWORD, login

        accepted = await client.post("/auth/accept-invite", json={"token": res.json()["invite_token"], "password": PASSWORD})
        assert accepted.status_code == 204, accepted.text
        return (await login(client, "lessor@example.com")).json()
    needs_2fa = role in {Role.MANAGER, Role.SUPERVISOR, Role.ACCOUNTANT}
    tokens, _ = await staff_session(client, owner, role.value, f"{role.value}@example.com", with_2fa=needs_2fa)
    return tokens


@pytest.mark.parametrize("role", [r for r in Role if r != Role.OWNER])
async def test_endpoint_access_matches_role_matrix(client, role):
    owner, _ = await owner_session(client)
    tokens = await session_for(client, owner, role)
    allowed = ROLE_PERMISSIONS[role]
    for name, (method, path, body, perm) in CHECKS.items():
        res = await client.request(method, path, headers=bearer(tokens), json=body)
        if perm in allowed:
            assert res.status_code < 300, f"{role} should be allowed {name}: {res.status_code} {res.text}"
        else:
            assert res.status_code == 403, f"{role} must be denied {name}: {res.status_code}"


async def test_owner_can_do_everything(client):
    owner, _ = await owner_session(client)
    for name, (method, path, body, _) in CHECKS.items():
        res = await client.request(method, path, headers=bearer(owner), json=body)
        assert res.status_code < 300, f"owner denied {name}: {res.text}"


async def test_unauthenticated_requests_are_rejected(client):
    for method, path, body, _ in CHECKS.values():
        res = await client.request(method, path, json=body)
        assert res.status_code == 401, path


# ---- the masterplan Section 3 table, restated as rules ------------------------------------------


def test_manager_has_no_payroll_billing_or_business_deletion():
    perms = permissions_for({Role.MANAGER})
    assert not perms & {"payroll.view", "subscription.manage", "business.manage", "users.manage"}
    assert {"vehicles.manage", "approvals.approve", "reports.view"} <= perms


def test_supervisor_has_no_company_finances_or_payroll():
    perms = permissions_for({Role.SUPERVISOR})
    assert not perms & {"finance.view", "payroll.view", "reports.view", "users.manage"}
    assert {"livemap.view", "trips.view", "approvals.approve"} <= perms


def test_accountant_has_money_but_no_live_map_or_trip_editing_or_user_access():
    perms = permissions_for({Role.ACCOUNTANT})
    assert {"finance.view", "payroll.view", "reports.view"} <= perms
    assert not perms & {"livemap.view", "trips.manage", "users.manage", "users.view"}


def test_driver_and_turnboy_only_see_their_own_work():
    for role in (Role.DRIVER, Role.TURNBOY):
        assert permissions_for({role}) == {"trips.own", "expenses.own"}


def test_workshop_only_does_workshop_and_lessor_only_their_own_lease():
    assert permissions_for({Role.WORKSHOP}) == {"workshop.manage"}
    assert permissions_for({Role.LESSOR}) == {"lease.view_own"}


def test_only_owner_and_manager_can_override_a_blocked_inspection():
    allowed = {r for r in Role if "inspections.override" in permissions_for({r})}
    assert allowed == {Role.OWNER, Role.MANAGER}


def test_only_the_owner_approves_over_limit_expenses_and_the_senior_staff_approve_the_day():
    assert {r for r in Role if "expenses.approve_limit" in permissions_for({r})} == {Role.OWNER}
    assert {r for r in Role if "reconciliations.approve" in permissions_for({r})} == {Role.OWNER, Role.MANAGER, Role.SUPERVISOR}
    assert {r for r in Role if "expenses.manage" in permissions_for({r})} == {Role.OWNER, Role.MANAGER, Role.ACCOUNTANT}
    assert {r for r in Role if "floats.manage" in permissions_for({r})} == {Role.OWNER, Role.MANAGER}
    for role in (Role.DRIVER, Role.TURNBOY, Role.WORKSHOP, Role.LESSOR):
        assert not permissions_for({role}) & {"expenses.view", "expenses.manage", "reconciliations.approve", "expenses.approve_limit"}


def test_owner_driver_gets_union_of_permissions():
    perms = permissions_for({Role.OWNER, Role.DRIVER})
    assert perms == permissions_for({Role.OWNER})
    assert "trips.own" in perms


async def test_multiple_roles_combine_permissions(client):
    owner, _ = await owner_session(client)
    res = await client.post(
        "/users", headers=bearer(owner), json={"name": "Dual", "email": "dual@example.com", "roles": ["accountant", "workshop"]}
    )
    assert res.status_code == 201
    assert sorted(res.json()["roles"]) == ["accountant", "workshop"]
