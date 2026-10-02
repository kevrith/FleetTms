"""Role to permission matrix, from masterplan Section 3.

A user's permissions in a business are the union of their roles. Later sprints add permissions
here; the per-role tests in tests/test_permissions.py must be updated with them.
"""

from app.models import Role

ALL = {
    "business.manage",
    "subscription.manage",
    "users.view",
    "users.manage",
    "depots.view",
    "depots.manage",
    "audit.view",
    "support.grant",
    "vehicles.view",
    "vehicles.manage",
    "staff.view",
    "staff.manage",
    "data.import",
    "trips.view",
    "trips.manage",
    "trips.own",
    "expenses.own",
    "inspections.override",
    "floats.manage",
    "expenses.view",
    "expenses.manage",
    "expenses.approve_limit",
    "reconciliations.approve",
    "approvals.approve",
    "livemap.view",
    "finance.view",
    "payroll.view",
    "reports.view",
    "reports.schedule",
    "workshop.manage",
    "incidents.manage",
    "sos.respond",
    "clients.manage",
    "jobs.manage",
    "lease.view_own",
}

ROLE_PERMISSIONS: dict[Role, set[str]] = {
    Role.OWNER: set(ALL),
    # No payroll details, subscription billing, or deleting the business.
    Role.MANAGER: {
        "users.view",
        "depots.view",
        "audit.view",
        "vehicles.view",
        "vehicles.manage",
        "staff.view",
        "staff.manage",
        "data.import",
        "trips.view",
        "trips.manage",
        "inspections.override",
        "floats.manage",
        "expenses.view",
        "expenses.manage",
        "reconciliations.approve",
        "approvals.approve",
        "livemap.view",
        "reports.view",
        "reports.schedule",
        "workshop.manage",
        "incidents.manage",
        "sos.respond",
        "clients.manage",
        "jobs.manage",
    },
    # Assigned vehicles only (enforced by vehicle_scope); no company-wide finances or payroll.
    Role.SUPERVISOR: {
        "depots.view",
        "vehicles.view",
        "trips.view",
        "expenses.view",
        "reconciliations.approve",
        "approvals.approve",
        "livemap.view",
        "sos.respond",
    },
    # Money only: no live map, no editing trips, no user management.
    Role.ACCOUNTANT: {
        "depots.view",
        "finance.view",
        "payroll.view",
        "reports.view",
        "expenses.view",
        "expenses.manage",
        "clients.manage",
    },
    Role.DRIVER: {"trips.own", "expenses.own"},
    Role.TURNBOY: {"trips.own", "expenses.own"},
    Role.WORKSHOP: {"workshop.manage"},
    Role.LESSOR: {"lease.view_own"},
}

# Read-only access a platform admin gets inside a tenant that granted support access.
SUPPORT_PERMISSIONS = {"users.view", "depots.view", "audit.view"}

# Roles that must use password plus two-step verification (masterplan Section 10).
MFA_REQUIRED_ROLES = {Role.OWNER, Role.MANAGER, Role.SUPERVISOR, Role.ACCOUNTANT}
# Roles that sign in with a phone number and one-time code only.
OTP_ONLY_ROLES = {Role.DRIVER, Role.TURNBOY}


def permissions_for(roles: set[Role]) -> set[str]:
    perms: set[str] = set()
    for role in roles:
        perms |= ROLE_PERMISSIONS[role]
    return perms
