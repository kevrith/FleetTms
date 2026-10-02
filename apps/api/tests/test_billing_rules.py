"""The billing and load rules must give exactly what the web shows: both sides are checked against shared case files."""

import json
from datetime import date
from pathlib import Path

import pytest

from app.billing_rules import invoice_standing, invoice_totals, trip_amount
from app.debtor_rules import ageing_bucket, invoice_number_from, reminder_offset_due
from app.load_rules import overload_kg
from app.quote_rules import BillingMethod

RULES = Path(__file__).resolve().parents[3] / "packages/business-rules/src"
BILLING = json.loads((RULES / "billing-cases.json").read_text())
LOAD = json.loads((RULES / "load-cases.json").read_text())
DEBTORS = json.loads((RULES / "debtor-cases.json").read_text())


@pytest.mark.parametrize("case", BILLING["trip_amounts"], ids=[c["name"] for c in BILLING["trip_amounts"]])
def test_trip_amounts(case):
    i = case["input"]
    assert trip_amount(method=BillingMethod(i["method"]), rate_cents=i["rate_cents"], weight_kg=i["weight_kg"], distance_km=i["distance_km"]) == case["expected"]


@pytest.mark.parametrize("case", BILLING["totals"], ids=[c["name"] for c in BILLING["totals"]])
def test_invoice_totals(case):
    assert invoice_totals(case["lines"], case["vat_pct"]) == case["expected"]


@pytest.mark.parametrize("case", BILLING["payments"], ids=[c["name"] for c in BILLING["payments"]])
def test_invoice_standing(case):
    got = invoice_standing(total_cents=case["total_cents"], paid=case["paid"], voided=case["voided"], due=date.fromisoformat(case["due"]), today=date.fromisoformat(case["today"]))
    assert got == case["expected"]


@pytest.mark.parametrize("case", LOAD, ids=[c["name"] for c in LOAD])
def test_overload(case):
    i = case["input"]
    assert overload_kg(cargo_kg=i["cargo_kg"], tare_kg=i["tare_kg"], gvw_limit_kg=i["gvw_limit_kg"], capacity_tonnes=i["capacity_tonnes"]) == case["expected"]


@pytest.mark.parametrize("case", DEBTORS["ageing"], ids=[c["name"] for c in DEBTORS["ageing"]])
def test_ageing(case):
    assert ageing_bucket(date.fromisoformat(case["due"]), date.fromisoformat(case["today"])) == case["expected"]


@pytest.mark.parametrize("case", DEBTORS["references"], ids=[c["name"] for c in DEBTORS["references"]])
def test_invoice_references(case):
    assert invoice_number_from(case["text"]) == case["expected"]


@pytest.mark.parametrize("case", DEBTORS["reminders"], ids=[c["name"] for c in DEBTORS["reminders"]])
def test_reminder_offsets(case):
    got = reminder_offset_due(due=date.fromisoformat(case["due"]), today=date.fromisoformat(case["today"]), offsets=case["offsets"], sent=case["sent"])
    assert got == case["expected"]


# ---- leasing, finance, ownership and profit (Sprint 10) ----

from app.lease_rules import (
    LeaseTerms,
    Usage,
    finance_schedule,
    instalment_cents,
    lease_not_paying,
    lease_standing,
    month_charge,
    net_profit,
    ownership_monthly,
)

LEASE = json.loads((RULES / "lease-cases.json").read_text())
FINANCE = json.loads((RULES / "finance-cases.json").read_text())
PROFIT = json.loads((RULES / "profit-cases.json").read_text())


def _terms(t: dict) -> LeaseTerms:
    return LeaseTerms(
        start=date.fromisoformat(t["start"]), end=date.fromisoformat(t["end"]) if t.get("end") else None, fixed_cents=t.get("fixed_cents", 0), fixed_period=t.get("fixed_period"),
        per_trip_cents=t.get("per_trip_cents", 0), per_km_cents=t.get("per_km_cents", 0), revenue_pct=t.get("revenue_pct", 0), profit_pct=t.get("profit_pct", 0),
        min_guarantee_cents=t.get("min_guarantee_cents", 0),
    )  # fmt: skip


@pytest.mark.parametrize("case", LEASE["charges"], ids=[c["name"] for c in LEASE["charges"]])
def test_lease_charges(case):
    assert month_charge(_terms(case["terms"]), date.fromisoformat(case["month"]), Usage(**case["usage"])) == case["expected"]


@pytest.mark.parametrize("case", LEASE["standing"], ids=[c["name"] for c in LEASE["standing"]])
def test_lease_standing(case):
    entries = [{**e, "due_date": date.fromisoformat(e["due_date"]) if e["due_date"] else None} for e in case["entries"]]
    got = lease_standing(entries, date.fromisoformat(case["today"]))
    assert got == {**case["expected"], "next_due_date": date.fromisoformat(case["expected"]["next_due_date"]) if case["expected"]["next_due_date"] else None}


@pytest.mark.parametrize("case", [c for c in FINANCE["instalments"] if c["months"] > 1], ids=[c["name"] for c in FINANCE["instalments"] if c["months"] > 1])
def test_instalments(case):
    assert instalment_cents(case["principal_cents"], case["annual_rate_pct"], case["months"]) == case["expected"]


@pytest.mark.parametrize("case", FINANCE["schedules"], ids=[c["name"] for c in FINANCE["schedules"]])
def test_finance_schedules(case):
    rows = finance_schedule(case["principal_cents"], case["annual_rate_pct"], case["months"], date.fromisoformat(case["first_due"]), case["instalment"])
    as_json = lambda r: {**r, "due_date": r["due_date"].isoformat()}
    assert len(rows) == case["rows"] and as_json(rows[0]) == case["first"] and as_json(rows[-1]) == case["last"]
    assert sum(r["principal_cents"] for r in rows) == case["principal_cents"]


@pytest.mark.parametrize("case", FINANCE["ownership"], ids=[c["name"] for c in FINANCE["ownership"]])
def test_ownership_costs(case):
    i = case["item"]
    got = ownership_monthly(
        kind=i["kind"], amount_cents=i["amount_cents"], period=i["period"], salvage_cents=i["salvage_cents"], life_months=i["life_months"], start=date.fromisoformat(i["start"]),
        end=date.fromisoformat(i["end"]) if i["end"] else None, month=date.fromisoformat(case["month"]),
    )  # fmt: skip
    assert got == case["expected"]


@pytest.mark.parametrize("case", PROFIT["net"], ids=[c["name"] for c in PROFIT["net"]])
def test_net_profit(case):
    assert net_profit(**case["input"]) == case["expected"]


@pytest.mark.parametrize("case", PROFIT["not_paying"], ids=[c["name"] for c in PROFIT["not_paying"]])
def test_lease_not_paying(case):
    assert lease_not_paying(case["months"]) == case["expected"]
