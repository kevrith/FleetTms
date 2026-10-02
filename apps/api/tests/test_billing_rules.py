"""The billing and load rules must give exactly what the web shows: both sides are checked against shared case files."""

import json
from datetime import date
from pathlib import Path

import pytest

from app.billing_rules import invoice_standing, invoice_totals, trip_amount
from app.load_rules import overload_kg
from app.quote_rules import BillingMethod

RULES = Path(__file__).resolve().parents[3] / "packages/business-rules/src"
BILLING = json.loads((RULES / "billing-cases.json").read_text())
LOAD = json.loads((RULES / "load-cases.json").read_text())


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
