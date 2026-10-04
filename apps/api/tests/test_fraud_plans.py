"""Which fraud checks each plan runs: the phone-based ones everywhere, the full set from Standard, the learned fuel model on Premium."""

from sqlalchemy import update

from app.models import Business
from tests.billing_helpers import pay_invoice
from tests.fraud_scenarios import by_kind, drive, open_alerts, seeded
from tests.helpers import bearer
from tests.leasing import in_db

BASIC = {"fuel_variance"}  # a fuel claim 20 percent above what the lorry normally uses
FULL_ONLY = {"excess_idling", "side_trip"}


async def on_plan(client, f, plan):
    """The vehicle on `plan`, and the business past its trial (a trial counts as Standard, so it would hide the difference)."""
    res = await client.put("/subscription/plans", headers=bearer(f.owner), json={"vehicles": [{"vehicle_id": f.vehicle["id"], "plan": plan}]})
    assert res.status_code == 200, res.text
    await pay_invoice(client, f.owner)


async def kinds_after_the_same_three_trips(client, f):
    await drive(client, f, litres=360, km=1000)  # fuel a fifth above normal: a basic check
    await drive(client, f, litres=360, km=1000, idle_minutes=1200)  # hours of idling: a full check
    return set(by_kind(await open_alerts(client, f.owner)))


async def test_a_starter_business_gets_the_phone_based_checks_but_not_the_full_set(client, billing):
    f = await seeded(client)
    await on_plan(client, f, "starter")
    kinds = await kinds_after_the_same_three_trips(client, f)
    assert BASIC <= kinds and not (FULL_ONLY & kinds), kinds


async def test_a_standard_business_gets_everything_starter_gets_and_the_full_set(client, billing):
    f = await seeded(client)
    await on_plan(client, f, "standard")
    kinds = await kinds_after_the_same_three_trips(client, f)
    assert BASIC <= kinds and "excess_idling" in kinds, kinds


async def test_a_side_trip_is_a_full_check_too(client, billing):
    f = await seeded(client, km=480)
    await on_plan(client, f, "starter")
    await drive(client, f, litres=150, km=700, phone_km=700)
    assert "side_trip" not in {a["kind"] for a in await open_alerts(client, f.owner)}
    await client.put("/subscription/plans", headers=bearer(f.owner), json={"vehicles": [{"vehicle_id": f.vehicle["id"], "plan": "standard"}]})
    await drive(client, f, litres=150, km=700, phone_km=700)
    assert "side_trip" in {a["kind"] for a in await open_alerts(client, f.owner)}  # from the day it moved up; earlier trips are not looked at again


async def test_a_business_on_trial_gets_the_full_checks(client, billing):
    f = await seeded(client)  # signed up today: a trial, which has Standard's features
    assert "excess_idling" in await kinds_after_the_same_three_trips(client, f)


async def test_a_free_account_gets_the_full_checks(client, billing):
    f = await seeded(client)
    await in_db(lambda db: db.execute(update(Business).values(complimentary=True)))
    res = await client.put("/subscription/plans", headers=bearer(f.owner), json={"vehicles": [{"vehicle_id": f.vehicle["id"], "plan": "starter"}]})
    assert res.status_code == 200, res.text  # a free account may set any plan, and still has everything
    assert "excess_idling" in await kinds_after_the_same_three_trips(client, f)


async def test_the_alerts_summary_says_what_the_plan_does_not_check(client, billing):
    f = await seeded(client)
    await on_plan(client, f, "starter")
    plan = (await client.get("/fraud/summary", headers=bearer(f.owner))).json()["plan"]
    assert plan["full_checks"] is False and plan["plan_needed"] == "standard"
    assert {"side_trip", "excess_idling", "long_stop", "tyre_swap", "parts_unfitted", "tamper_then_stop"} <= set(plan["not_included"])
    await client.put("/subscription/plans", headers=bearer(f.owner), json={"vehicles": [{"vehicle_id": f.vehicle["id"], "plan": "premium"}]})
    plan = (await client.get("/fraud/summary", headers=bearer(f.owner))).json()["plan"]
    assert plan["full_checks"] is True and plan["not_included"] == []


async def test_with_plan_limits_off_every_check_runs_as_before(client):
    f = await seeded(client)  # the default in tests: no plan limits
    assert {"fuel_variance", "excess_idling"} <= await kinds_after_the_same_three_trips(client, f)
