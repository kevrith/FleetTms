"""Leasing, asset finance, ownership costs and net profit (masterplan 5.23 and 5.15). The same rules as
packages/business-rules/src/lease.ts, tested against lease-cases.json, finance-cases.json and profit-cases.json on both sides.
Money is whole cents. Percentages are held in hundredths of a percent so no float touches the money."""

import calendar
from dataclasses import dataclass
from datetime import date, timedelta


def div_half(n: int, d: int) -> int:
    """n / d rounded half up, for n >= 0 and d > 0."""
    return (2 * n + d) // (2 * d)


def pct_hundredths(pct: float) -> int:
    return round(float(pct) * 100)


def share(amount_cents: int, pct: float) -> int:
    """pct percent of an amount, rounded half up. Nothing is shared out of a loss."""
    return div_half(max(0, amount_cents) * pct_hundredths(pct), 10_000)


def month_bounds(day: date) -> tuple[date, date]:
    return day.replace(day=1), day.replace(day=calendar.monthrange(day.year, day.month)[1])


def add_months(day: date, months: int) -> date:
    """The same day of a later month, or its last day if that month is shorter (31 Jan plus a month is 28 or 29 Feb)."""
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    return date(year, month + 1, min(day.day, calendar.monthrange(year, month + 1)[1]))


# ---- lease charges ------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class LeaseTerms:
    start: date
    end: date | None = None
    fixed_cents: int = 0
    fixed_period: str | None = None  # month, week or day
    per_trip_cents: int = 0
    per_km_cents: int = 0
    revenue_pct: float = 0
    profit_pct: float = 0
    min_guarantee_cents: int = 0  # per month


@dataclass(frozen=True)
class Usage:
    trips: int = 0
    km: int = 0
    revenue_cents: int = 0
    profit_cents: int = 0  # gross profit before the lease, for a share of profit


def active_days(terms: LeaseTerms, month: date) -> tuple[int, int]:
    """(days the agreement runs in the month, days in the month)."""
    first, last = month_bounds(month)
    start = max(first, terms.start)
    end = min(last, terms.end) if terms.end else last
    return max(0, (end - start).days + 1), last.day


def month_charge(terms: LeaseTerms, month: date, usage: Usage) -> dict:
    """What the lease charges for one calendar month. The parts add up (a fixed amount, a rate per trip or km, a share of
    revenue or profit); a minimum guarantee is a floor under the total, so "at least 120,000, or 30% of revenue, whichever
    is higher" is a guarantee of 120,000 with a revenue share of 30%."""
    days, in_month = active_days(terms, month)
    if days == 0:
        return {"days_active": 0, "days_in_month": in_month, "fixed_cents": 0, "trips_cents": 0, "km_cents": 0, "revenue_share_cents": 0, "profit_share_cents": 0, "subtotal_cents": 0, "guarantee_cents": 0, "guarantee_applied": False, "charge_cents": 0}  # fmt: skip
    if terms.fixed_period == "month":
        fixed = div_half(terms.fixed_cents * days, in_month)
    elif terms.fixed_period == "week":
        fixed = div_half(terms.fixed_cents * days, 7)
    elif terms.fixed_period == "day":
        fixed = terms.fixed_cents * days
    else:
        fixed = 0
    trips, km = terms.per_trip_cents * max(0, usage.trips), terms.per_km_cents * max(0, usage.km)
    revenue_share, profit_share = share(usage.revenue_cents, terms.revenue_pct), share(usage.profit_cents, terms.profit_pct)
    subtotal = fixed + trips + km + revenue_share + profit_share
    guarantee = div_half(terms.min_guarantee_cents * days, in_month) if terms.min_guarantee_cents else 0
    return {
        "days_active": days, "days_in_month": in_month, "fixed_cents": fixed, "trips_cents": trips, "km_cents": km, "revenue_share_cents": revenue_share,
        "profit_share_cents": profit_share, "subtotal_cents": subtotal, "guarantee_cents": guarantee, "guarantee_applied": guarantee > subtotal,
        "charge_cents": max(subtotal, guarantee),
    }  # fmt: skip


def lease_standing(entries: list[dict], today: date) -> dict:
    """Where a lease account stands. Each entry is {kind, amount_cents, due_date}: charges and adjustments add to what is
    owed, offsets and payments take away. Overdue is what is past its due date after everything paid and offset."""
    balance = sum(e["amount_cents"] for e in entries)
    due_now = sum(e["amount_cents"] for e in entries if e["kind"] in ("charge", "adjustment") and e["due_date"] is not None and e["due_date"] < today)
    credits = -sum(e["amount_cents"] for e in entries if e["kind"] in ("offset", "payment"))
    upcoming = sorted(e["due_date"] for e in entries if e["kind"] == "charge" and e["due_date"] is not None and e["due_date"] >= today)
    overdue = max(0, min(balance, due_now - credits))
    return {
        "balance_cents": balance, "overdue_cents": overdue,
        "next_due_date": upcoming[0] if upcoming and balance > 0 else None,
    }  # fmt: skip


# ---- asset finance ------------------------------------------------------------------------------------------------


def instalment_cents(principal_cents: int, annual_rate_pct: float, months: int) -> int:
    """The level monthly repayment on a reducing balance."""
    if months <= 0:
        raise ValueError("A loan needs at least one month.")
    rate = float(annual_rate_pct) / 1200
    if rate == 0:
        return div_half(principal_cents, months)
    return round(principal_cents * rate / (1 - (1 + rate) ** -months))


def finance_schedule(principal_cents: int, annual_rate_pct: float, months: int, first_due: date, instalment: int | None = None) -> list[dict]:
    """Every repayment: what is paid, how much of it is interest, and the balance after. The last repayment clears whatever
    is left, so rounding never leaves a few cents owing."""
    payment = instalment if instalment is not None else instalment_cents(principal_cents, annual_rate_pct, months)
    rate_h = pct_hundredths(annual_rate_pct)
    balance, rows = principal_cents, []
    for n in range(1, months + 1):
        interest = div_half(balance * rate_h, 12 * 10_000)
        if n == months or payment >= balance + interest:
            amount, principal = balance + interest, balance
        else:
            amount = payment
            principal = max(0, amount - interest)
        balance -= principal
        rows.append({"number": n, "due_date": add_months(first_due, n - 1), "amount_cents": amount, "interest_cents": interest, "principal_cents": principal, "balance_cents": balance})
        if balance == 0:
            break
    return rows


# ---- ownership costs ------------------------------------------------------------------------------------------------


def ownership_monthly(*, kind: str, amount_cents: int, period: str, salvage_cents: int, life_months: int | None, start: date, end: date | None, month: date) -> int:
    """What a fixed ownership cost comes to for one calendar month. An insurance or licence paid yearly is spread over twelve
    months; depreciation is the cost less what it will be worth, spread evenly over its life; a part month is pro-rated."""
    first, last = month_bounds(month)
    run_start = max(first, start)
    run_end = min(last, end) if end else last
    if kind == "depreciation":
        if not life_months or life_months <= 0:
            return 0
        life_end = add_months(start, life_months) - timedelta(days=1)
        run_end = min(run_end, life_end)
        base = div_half(max(0, amount_cents - salvage_cents), life_months)
    else:
        base = div_half(amount_cents, 12) if period == "year" else amount_cents
    days = (run_end - run_start).days + 1
    if days <= 0:
        return 0
    return base if days == last.day else div_half(base * days, last.day)


# ---- profit ---------------------------------------------------------------------------------------------------------


def net_profit(*, revenue_cents: int, operating_cents: int, lease_charges_cents: int = 0, offsets_cents: int = 0, finance_cents: int = 0, ownership_cents: int = 0) -> dict:
    """Gross profit is revenue less what it cost to run. What is paid to a lorry's owner (the lease charges less any costs the
    operator paid on the owner's behalf) comes off next, then loan repayments and the fixed ownership costs."""
    gross = revenue_cents - operating_cents
    payable = lease_charges_cents - offsets_cents
    return {"gross_profit_cents": gross, "lease_payable_cents": payable, "net_profit_cents": gross - payable - finance_cents - ownership_cents}


def lease_not_paying(months: list[dict], run: int = 3) -> bool:
    """True when, for the last `run` months in a row, the lorry's owner earned more than the operator did. Each month is
    {lessor_cents, operator_net_cents}, oldest first."""
    recent = months[-run:]
    return len(recent) == run and all(m["lessor_cents"] > m["operator_net_cents"] for m in recent)
