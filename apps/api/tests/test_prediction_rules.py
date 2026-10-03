import pytest

from app import prediction_rules as pr


@pytest.mark.parametrize(("trips", "hours", "back", "days"), [(1, 6, False, 1), (1, 12, True, 1), (2, 14, True, 3), (1, 12.5, True, 2), (5, 24, False, 5), (1, 0, True, 1)])
def test_a_job_ties_the_lorry_up_for_whole_days(trips, hours, back, days):
    assert pr.job_days(trips, hours, back) == days


def test_every_part_of_a_lease_is_charged_for_the_job():
    terms = {"fixed_cents": 3_000_000, "fixed_period": "month", "per_trip_cents": 100_000, "per_km_cents": 500, "revenue_pct": 10, "profit_pct": 20}
    got = pr.job_lease_charge(terms, price_cents=24_000_000, gross_profit_cents=14_280_000, trips=2, total_km=1920, days=3)
    assert got["fixed_cents"] == 300_000  # 3 of 30 days of the monthly charge
    assert got["trips_cents"] == 200_000 and got["km_cents"] == 960_000
    assert got["revenue_share_cents"] == 2_400_000 and got["profit_share_cents"] == 2_856_000
    assert got["total_cents"] == 300_000 + 200_000 + 960_000 + 2_400_000 + 2_856_000


@pytest.mark.parametrize(("period", "fixed", "days", "expected"), [("day", 100_000, 3, 300_000), ("week", 700_000, 3, 300_000), ("month", 3_000_000, 3, 300_000), (None, 3_000_000, 3, 0)])
def test_a_fixed_charge_is_shared_by_the_days_of_use(period, fixed, days, expected):
    got = pr.job_lease_charge({"fixed_cents": fixed, "fixed_period": period}, price_cents=0, gross_profit_cents=0, trips=1, total_km=0, days=days)
    assert got["fixed_cents"] == expected


def test_nothing_is_shared_out_of_a_loss():
    got = pr.job_lease_charge({"profit_pct": 30, "revenue_pct": 0}, price_cents=1_000_000, gross_profit_cents=-500_000, trips=1, total_km=100, days=1)
    assert got["profit_share_cents"] == 0 and got["total_cents"] == 0


def test_a_month_ends_where_it_is_plus_what_the_rest_usually_brings():
    got = pr.project_month(to_date_cents=10_000_000, days_elapsed=10, days_in_month=30, history_cents=90_000_000, history_days=90)
    assert got == {"per_day_cents": 1_000_000, "remaining_days": 20, "projected_cents": 30_000_000}
    last_day = pr.project_month(to_date_cents=10_000_000, days_elapsed=30, days_in_month=30, history_cents=90_000_000, history_days=90)
    assert last_day["projected_cents"] == 10_000_000


def test_with_no_earlier_months_there_is_no_forecast():
    got = pr.project_month(to_date_cents=10_000_000, days_elapsed=10, days_in_month=30, history_cents=0, history_days=0)
    assert got["projected_cents"] is None and got["per_day_cents"] is None and got["remaining_days"] == 20
