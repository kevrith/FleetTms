"""Plans and pricing (masterplan Section 9): the price of a fleet, what each plan includes, and whether an account has full access, a
grace period or is read-only. The same as packages/business-rules/src/plans.ts, tested against plan-cases.json on both sides. Money is
whole cents. The prices are the masterplan's proposed starting points, to be validated with real fleet owners."""

from datetime import datetime, timedelta

PLANS = ("starter", "standard", "premium")
RANK = {"starter": 0, "standard": 1, "premium": 2}
PRICE_CENTS = {"starter": 100_000, "standard": 180_000, "premium": 280_000}  # per vehicle per month
PAYROLL_CENTS = 10_000  # per employee per month, when payroll with statutory deductions is on
TRIAL_DAYS = 14
GRACE_DAYS = 7
ANNUAL_MONTHS_PAID = 10  # pay for 10 months, get 12
VOLUME_FROM, VOLUME_TO, VOLUME_PCT = 11, 30, 10
CUSTOM_FROM = 31  # larger fleets are priced by agreement
SMS_BUNDLES = {500: 60_000, 2000: 240_000, 5000: 600_000}  # messages: price, at cost plus a small margin
FEATURES = {  # the cheapest plan that includes each feature
    "trackers": "standard", "live_map": "standard", "replay": "standard", "geofences": "standard", "scorecards": "standard", "tyres_parts": "standard",
    "tracking_links": "standard", "etims": "standard", "custom_reports": "standard", "all_roles": "standard",
    "fuel_sensors": "premium", "immobiliser": "premium", "predictions": "premium", "ask": "premium", "scheduled_reports": "premium",
}  # fmt: skip
VEHICLE_FEATURES = {"trackers", "fuel_sensors", "immobiliser"}  # decided by the vehicle's own plan; the rest by the fleet's best plan


def half_up(numerator: int, denominator: int) -> int:
    return (2 * numerator + denominator) // (2 * denominator)


def allows(plan: str, feature: str) -> bool:
    """Whether a plan includes a feature. Anything not listed is in every plan."""
    needed = FEATURES.get(feature)
    return needed is None or RANK[plan] >= RANK[needed]


def best_plan(plans: list[str]) -> str:
    """The highest plan among a fleet's vehicles. A fleet with no vehicles yet has everything a trial gives: Standard."""
    return max(plans, key=lambda p: RANK[p]) if plans else "standard"


def quote_subscription(plans: list[str], *, period: str = "monthly", payroll_employees: int = 0) -> dict:
    """What a fleet pays. `plans` has one entry per vehicle. 11 to 30 vehicles get 10 percent off the vehicle charges; 31 and more are
    priced by agreement (the list price is shown, `custom` is true). An annual period pays 10 months for 12."""
    counts = {p: plans.count(p) for p in PLANS}
    lines = [{"plan": p, "vehicles": counts[p], "unit_cents": PRICE_CENTS[p], "cents": counts[p] * PRICE_CENTS[p]} for p in PLANS if counts[p]]
    list_cents = sum(line["cents"] for line in lines)
    n = len(plans)
    discount_pct = VOLUME_PCT if VOLUME_FROM <= n <= VOLUME_TO else 0
    discount_cents = half_up(list_cents * discount_pct, 100)
    vehicles_cents = list_cents - discount_cents
    payroll_cents = max(0, payroll_employees) * PAYROLL_CENTS
    monthly_cents = vehicles_cents + payroll_cents
    months_paid, months_covered = (ANNUAL_MONTHS_PAID, 12) if period == "annual" else (1, 1)
    total = monthly_cents * months_paid
    return {
        "vehicles": n, "lines": lines, "list_cents": list_cents, "discount_pct": discount_pct, "discount_cents": discount_cents, "vehicles_cents": vehicles_cents,
        "payroll_cents": payroll_cents, "monthly_cents": monthly_cents, "period": period, "months_paid": months_paid, "months_covered": months_covered,
        "total_cents": total, "saving_cents": monthly_cents * months_covered - total, "custom": n >= CUSTOM_FROM,
    }  # fmt: skip


def access_state(*, complimentary: bool, trial_ends_at: datetime, paid_until: datetime | None, now: datetime, cancelled: bool = False) -> dict:
    """Full access while on trial or paid up; full access with a warning for 7 days after either ends; read-only after that. Read-only
    never deletes anything, and paying brings full access straight back. `ends_at` is when the current trial or paid period ends."""
    if complimentary:
        return {"state": "complimentary", "ends_at": None, "grace_ends_at": None, "days_left": None, "writable": True}
    if cancelled:
        return {"state": "read_only", "ends_at": paid_until or trial_ends_at, "grace_ends_at": None, "days_left": 0, "writable": False}
    ends = paid_until if paid_until is not None else trial_ends_at
    grace = ends + timedelta(days=GRACE_DAYS)
    if now <= ends:
        state = "active" if paid_until is not None else "trialing"
        return {"state": state, "ends_at": ends, "grace_ends_at": grace, "days_left": max(0, -(-int((ends - now).total_seconds()) // 86_400)), "writable": True}
    if now <= grace:
        return {"state": "grace", "ends_at": ends, "grace_ends_at": grace, "days_left": max(0, -(-int((grace - now).total_seconds()) // 86_400)), "writable": True}
    return {"state": "read_only", "ends_at": ends, "grace_ends_at": grace, "days_left": 0, "writable": False}
