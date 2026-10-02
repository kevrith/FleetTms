"""What a lease agreement says, as the rest of the system reads it: its terms, and who pays for what."""

from app.lease_rules import LeaseTerms
from app.models import ExpenseCategory, LeaseAgreement

# The cost responsibility matrix (masterplan 5.23). Anything not listed here is always the operator's (tolls, parking, food).
RESPONSIBILITY_ITEMS = {
    "fuel": "Fuel",
    "routine_service": "Routine service",
    "major_repairs": "Major repairs",
    "tyres": "Tyres",
    "insurance": "Insurance",
    "licences": "Licences and permits",
    "driver_salary": "Driver and turnboy pay",
    "tracker": "Tracker subscription",
    "fines": "Fines",
}
# The usual split: the operator runs the lorry; the owner keeps it insured, licensed and fit for the road.
DEFAULT_RESPONSIBILITIES = {
    "fuel": "lessee", "routine_service": "lessee", "major_repairs": "lessor", "tyres": "lessee", "insurance": "lessor",
    "licences": "lessor", "driver_salary": "lessee", "tracker": "lessee", "fines": "lessee",
}  # fmt: skip

CATEGORY_ITEM = {
    ExpenseCategory.SERVICE: "routine_service",
    ExpenseCategory.GARAGE: "routine_service",
    ExpenseCategory.REPAIR: "major_repairs",
    ExpenseCategory.TYRES: "tyres",
    ExpenseCategory.INSURANCE: "insurance",
    ExpenseCategory.LICENCE: "licences",
    ExpenseCategory.PERMIT: "licences",
}
# Expense categories a fixed ownership cost of the same kind already covers, so they are not counted twice.
CATEGORY_OWNERSHIP_KIND = {ExpenseCategory.INSURANCE: "insurance", ExpenseCategory.LICENCE: "licence", ExpenseCategory.PERMIT: "licence"}


def item_for_category(category: ExpenseCategory) -> str | None:
    return CATEGORY_ITEM.get(category)


def matrix_of(agreement: LeaseAgreement) -> dict[str, str]:
    return {**DEFAULT_RESPONSIBILITIES, **(agreement.responsibilities or {})}


def terms_of(a: LeaseAgreement) -> LeaseTerms:
    return LeaseTerms(
        start=a.start_date, end=a.end_date, fixed_cents=a.fixed_cents, fixed_period=a.fixed_period, per_trip_cents=a.per_trip_cents,
        per_km_cents=a.per_km_cents, revenue_pct=float(a.revenue_pct), profit_pct=float(a.profit_pct), min_guarantee_cents=a.min_guarantee_cents,
    )  # fmt: skip


def has_variable_terms(a: LeaseAgreement) -> bool:
    """True if the charge depends on what the lorry did (trips, km, revenue or profit), not just on time."""
    return bool(a.per_trip_cents or a.per_km_cents or float(a.revenue_pct) or float(a.profit_pct))
