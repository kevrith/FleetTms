"""The partner programme: from an installer applying, to the commission on a referred business's first payment."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app import partner_rules, subscriptions
from app.config import settings
from app.db import get_sessionmaker
from app.models import Business, Partner, PartnerCommission, SubscriptionInvoice
from app.sms import get_sms_sender
from tests.billing_helpers import pay_invoice
from tests.fleet import add_vehicle
from tests.helpers import PASSWORD, bearer, enable_2fa, owner_session
from tests.leasing import in_db
from tests.test_support_and_privacy import make_platform_admin


async def plain(fn):
    """A query on the platform's own tables, which belong to no business."""
    async with get_sessionmaker()() as db:
        result = await fn(db)
        await db.commit()
        return result


APPLICATION = {"name": "Savanna Trackers Ltd", "contact_name": "Peter Mwangi", "phone": "0711 222 333", "email": "peter@savanna.example.com", "city": "Nairobi", "message": "We fit about 40 lorries a month."}


async def apply(client, **extra):
    res = await client.post("/partners/apply", json={**APPLICATION, **extra})
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def approved_partner(client, admin, pct=None):
    partner_id = await apply(client)
    res = await client.post(f"/platform/partners/{partner_id}/approve", headers=bearer(admin), json={"commission_pct": pct})
    assert res.status_code == 200, res.text
    return partner_id, res.json()


async def referred_owner(client, code, business="Mwangi Haulage", email="mwangi@example.com"):
    body = {"business_name": business, "name": "Owner Mwangi", "email": email, "phone": None, "password": PASSWORD, "accept_terms": True, "accept_privacy": True, "accept_dpa": True, "referral_code": code}
    res = await client.post("/auth/signup", json=body)
    assert res.status_code == 201, res.text
    tokens = res.json()
    await enable_2fa(client, tokens)
    return tokens


async def portal(client, key):
    res = await client.get("/partners/portal", headers={"X-Partner-Key": key})
    assert res.status_code == 200, res.text
    return res.json()


# ---- the money rules -----------------------------------------------------------------------------------------------------


def test_commission_is_a_share_of_what_was_paid_rounded_down_to_the_cent():
    assert partner_rules.commission_cents(180_000, 2000) == 36_000  # 20 percent of 1,800.00
    assert partner_rules.commission_cents(180_001, 2000) == 36_000
    assert partner_rules.commission_cents(99, 2000) == 19
    assert partner_rules.commission_cents(1_800_000, 1250) == 225_000
    assert partner_rules.commission_cents(0, 2000) == 0


def test_months_are_added_by_the_calendar_and_the_window_is_inclusive_of_the_first_months():
    d = datetime(2026, 1, 31, tzinfo=UTC)
    assert partner_rules.add_months(d, 1) == datetime(2026, 2, 28, tzinfo=UTC)
    assert partner_rules.add_months(datetime(2024, 1, 31, tzinfo=UTC), 1) == datetime(2024, 2, 29, tzinfo=UTC)
    assert partner_rules.add_months(d, 24) == datetime(2028, 1, 31, tzinfo=UTC)
    assert partner_rules.add_months(datetime(2026, 11, 15, tzinfo=UTC), 3) == datetime(2027, 2, 15, tzinfo=UTC)
    first = datetime(2026, 1, 10, tzinfo=UTC)
    assert partner_rules.in_window(first, datetime(2027, 12, 31, tzinfo=UTC), 24)
    assert not partner_rules.in_window(first, datetime(2028, 1, 10, tzinfo=UTC), 24)
    assert partner_rules.in_window(first, datetime(2040, 1, 1, tzinfo=UTC), 0)  # zero means for as long as they pay


def test_codes_are_short_unambiguous_and_typed_forgivingly():
    codes = {partner_rules.new_code() for _ in range(200)}
    assert all(len(c) == 6 and not set(c) & set("01OIL") for c in codes) and len(codes) > 190
    assert partner_rules.normalise_code(" sav-4nn a ") == "SAV4NNA"


# ---- applying and approving ----------------------------------------------------------------------------------------------


async def test_anyone_can_apply_and_nothing_is_given_out_until_a_person_approves(client):
    partner_id = await apply(client)
    admin = await make_platform_admin(client)
    [row] = (await client.get("/platform/partners", headers=bearer(admin))).json()
    assert row["id"] == partner_id and row["status"] == "pending" and row["code"] is None and row["phone"] == "+254711222333"
    assert (await client.get("/partners/code/ANYTHING")).status_code == 404
    assert (await client.get("/platform/partner-summary", headers=bearer(admin))).json() == {"applications_waiting": 1, "owed_cents": 0}
    assert (await client.post("/partners/apply", json={**APPLICATION, "phone": "12"})).status_code == 422


async def test_approving_gives_a_code_and_a_key_texts_them_and_shows_the_key_once(client):
    admin = await make_platform_admin(client)
    partner_id, approved = await approved_partner(client, admin)
    assert approved["status"] == "approved" and len(approved["code"]) == 6 and approved["commission_pct"] == settings.partner_commission_pct and approved["portal_key"]
    texted = [t for phone, t in get_sms_sender().outbox if phone == "+254711222333"]
    assert len(texted) == 1 and approved["code"] in texted[0] and approved["portal_key"] in texted[0]
    assert "portal_key" not in (await client.get(f"/platform/partners/{partner_id}", headers=bearer(admin))).json()
    again = await client.post(f"/platform/partners/{partner_id}/approve", headers=bearer(admin), json={})
    assert again.status_code == 409
    stored = await plain(lambda db: db.get(Partner, uuid.UUID(partner_id)))
    assert approved["portal_key"] not in (stored.portal_key_hash or "") and len(stored.portal_key_hash) == 64  # only a hash is kept


async def test_the_share_can_be_set_when_approving_and_changed_for_the_future(client):
    admin = await make_platform_admin(client)
    partner_id, approved = await approved_partner(client, admin, pct=25)
    assert approved["commission_pct"] == 25
    changed = await client.post(f"/platform/partners/{partner_id}/commission", headers=bearer(admin), json={"commission_pct": 15})
    assert changed.json()["commission_pct"] == 15
    assert (await client.post(f"/platform/partners/{partner_id}/commission", headers=bearer(admin), json={})).status_code == 422
    assert (await client.post(f"/platform/partners/{partner_id}/approve", headers=bearer(admin), json={"commission_pct": 90})).status_code in (409, 422)


async def test_an_application_can_be_rejected_and_only_platform_admins_decide(client):
    partner_id = await apply(client)
    owner, _ = await owner_session(client)
    for action in ("approve", "reject", "suspend", "payout"):
        assert (await client.post(f"/platform/partners/{partner_id}/{action}", headers=bearer(owner), json={"reference": "ABC123"})).status_code == 403
    assert (await client.get("/platform/partners", headers=bearer(owner))).status_code == 403
    assert (await client.get("/platform/partners")).status_code == 401
    admin = await make_platform_admin(client)
    assert (await client.post(f"/platform/partners/{partner_id}/reject", headers=bearer(admin))).json() == {"deleted": True}
    assert (await client.get("/platform/partners", headers=bearer(admin))).json() == []
    approved_id, _ = await approved_partner(client, admin)
    assert (await client.post(f"/platform/partners/{approved_id}/reject", headers=bearer(admin))).status_code == 409


# ---- referral ------------------------------------------------------------------------------------------------------------


async def test_a_code_typed_at_sign_up_ties_the_business_to_the_partner_and_a_wrong_one_is_ignored(client):
    admin = await make_platform_admin(client)
    _, partner = await approved_partner(client, admin)
    assert (await client.get(f"/partners/code/{partner['code'].lower()}")).json() == {"partner": "Savanna Trackers Ltd"}  # forgiving of case
    await referred_owner(client, partner["code"].lower())
    await referred_owner(client, "WRONG1", business="Other Haulage", email="other@example.com")
    async def referred(db):
        return {b.name: b.referred_by_partner_id for b in (await db.execute(select(Business))).scalars()}

    seen = await plain(referred)
    assert seen["Mwangi Haulage"] is not None and seen["Other Haulage"] is None  # a mistyped code never stops anyone signing up


async def test_a_pending_or_suspended_partners_code_brings_in_no_referrals(client):
    admin = await make_platform_admin(client)
    await apply(client)  # an application nobody has approved
    await referred_owner(client, "ABCDEF")
    partner_id, partner = await approved_partner(client, admin)
    assert (await client.post(f"/platform/partners/{partner_id}/suspend", headers=bearer(admin))).json()["status"] == "suspended"
    assert (await client.get(f"/partners/code/{partner['code']}")).status_code == 404
    await referred_owner(client, partner["code"], business="Late Haulage", email="late@example.com")
    count = await plain(lambda db: db.execute(select(Business.id).where(Business.referred_by_partner_id.is_not(None))))
    assert count.all() == []


# ---- the acceptance test: a referral tracked through to a paid subscription -----------------------------------------------


async def test_a_partner_referral_is_tracked_through_to_a_paid_subscription_and_its_commission(client):
    admin = await make_platform_admin(client)
    partner_id, partner = await approved_partner(client, admin)
    owner = await referred_owner(client, partner["code"])
    await add_vehicle(client, owner, "KCA 123A")

    seen = await portal(client, partner["portal_key"])
    assert seen["partner"]["name"] == "Savanna Trackers Ltd" and seen["totals"] == {"owed_cents": 0, "paid_cents": 0, "referred": 1, "paying": 0}
    assert [(r["business"], r["state"], r["vehicles"]) for r in seen["referrals"]] == [("Mwangi Haulage", "trialing", 1)]

    paid = await pay_invoice(client, owner)  # the trial ends with a real payment: 1,800.00 for one Standard vehicle
    assert paid["status"] == "paid" and paid["total_cents"] == 180_000

    seen = await portal(client, partner["portal_key"])
    assert seen["totals"] == {"owed_cents": 36_000, "paid_cents": 0, "referred": 1, "paying": 1}
    assert [(r["business"], r["state"]) for r in seen["referrals"]] == [("Mwangi Haulage", "active")]
    [c] = seen["commissions"]
    assert (c["business"], c["invoice"], c["paid_by_business_cents"], c["share_pct"], c["amount_cents"], c["status"]) == ("Mwangi Haulage", "SUB-0001", 180_000, 20.0, 36_000, "accrued")

    # the next period pays commission again, once
    await pay_invoice(client, owner)
    assert (await portal(client, partner["portal_key"]))["totals"]["owed_cents"] == 72_000

    # the platform sees what is owed and settles it
    assert (await client.get("/platform/partner-summary", headers=bearer(admin))).json()["owed_cents"] == 72_000
    csv = (await client.get("/platform/partners/commissions.csv", headers=bearer(admin))).text.splitlines()
    assert csv[0].startswith("partner,phone,business,invoice") and len(csv) == 3 and "Savanna Trackers Ltd" in csv[1] and "360.00" in csv[1]
    settled = await client.post(f"/platform/partners/{partner_id}/payout", headers=bearer(admin), json={"reference": "QWE9876543"})
    assert settled.json()["paid_cents"] == 72_000 and settled.json()["owed_cents"] == 0 and settled.json()["paid_cents"] == 72_000
    after = await portal(client, partner["portal_key"])
    assert after["totals"]["paid_cents"] == 72_000 and {c["payout_reference"] for c in after["commissions"]} == {"QWE9876543"}
    assert (await client.post(f"/platform/partners/{partner_id}/payout", headers=bearer(admin), json={"reference": "AGAIN123"})).json()["detail"]["code"] == "nothing_owed"
    assert (await client.get("/platform/partners/commissions.csv?state=accrued", headers=bearer(admin))).text.count("\n") == 1  # header only


async def test_a_business_nobody_referred_earns_no_one_anything(client):
    admin = await make_platform_admin(client)
    owner, _ = await owner_session(client)
    await add_vehicle(client, owner, "KCA 123A")
    await pay_invoice(client, owner)
    assert (await plain(lambda db: db.execute(select(PartnerCommission.id)))).all() == []
    assert (await client.get("/platform/partner-summary", headers=bearer(admin))).json()["owed_cents"] == 0


async def test_text_bundles_earn_no_commission_and_a_payment_applied_twice_earns_it_once(client):
    admin = await make_platform_admin(client)
    _, partner = await approved_partner(client, admin)
    owner = await referred_owner(client, partner["code"])
    await add_vehicle(client, owner, "KCA 123A")
    bundle = (await client.post("/subscription/sms-bundles", headers=bearer(owner), json={"messages": 500})).json()
    pay = await client.post(f"/subscription/invoices/{bundle['id']}/pay", headers=bearer(owner), json={"phone": "0712345678"})
    assert pay.status_code == 200, pay.text
    from tests.billing_helpers import answer_prompt

    assert (await answer_prompt(client)).status_code == 200
    assert (await portal(client, partner["portal_key"]))["totals"]["owed_cents"] == 0  # a bundle is not a subscription

    await pay_invoice(client, owner)

    async def pay_again(db):
        invoice = (await db.execute(select(SubscriptionInvoice).where(SubscriptionInvoice.kind == "subscription"))).scalars().one()
        await subscriptions.apply_paid(db, invoice, method="mpesa", code="AGAIN")  # already paid: left alone

    await in_db(pay_again, business="Mwangi Haulage")
    assert (await portal(client, partner["portal_key"]))["totals"]["owed_cents"] == 36_000


async def test_commission_runs_for_the_agreed_months_after_the_first_payment_and_then_stops(client, monkeypatch):
    monkeypatch.setattr(settings, "partner_commission_months", 2)
    admin = await make_platform_admin(client)
    _, partner = await approved_partner(client, admin)
    owner = await referred_owner(client, partner["code"])
    await add_vehicle(client, owner, "KCA 123A")
    await pay_invoice(client, owner)

    async def first_payment_was_long_ago(db):
        await db.execute(update(SubscriptionInvoice).values(paid_at=datetime.now(UTC) - timedelta(days=75)))
        await db.execute(update(PartnerCommission).values(accrued_at=datetime.now(UTC) - timedelta(days=75)))

    await in_db(first_payment_was_long_ago, business="Mwangi Haulage")
    await pay_invoice(client, owner)  # the first payment was 75 days ago, past the two months: no commission
    assert (await portal(client, partner["portal_key"]))["totals"]["owed_cents"] == 36_000


async def test_a_suspended_partner_earns_nothing_new_but_keeps_what_was_earned(client):
    admin = await make_platform_admin(client)
    partner_id, partner = await approved_partner(client, admin)
    owner = await referred_owner(client, partner["code"])
    await add_vehicle(client, owner, "KCA 123A")
    await pay_invoice(client, owner)
    await client.post(f"/platform/partners/{partner_id}/suspend", headers=bearer(admin))
    await pay_invoice(client, owner)
    assert (await portal(client, partner["portal_key"]))["totals"]["owed_cents"] == 36_000
    await client.post(f"/platform/partners/{partner_id}/reactivate", headers=bearer(admin))
    await pay_invoice(client, owner)
    assert (await portal(client, partner["portal_key"]))["totals"]["owed_cents"] == 72_000


async def test_a_change_of_share_applies_to_new_commission_only(client):
    admin = await make_platform_admin(client)
    partner_id, partner = await approved_partner(client, admin)
    owner = await referred_owner(client, partner["code"])
    await add_vehicle(client, owner, "KCA 123A")
    await pay_invoice(client, owner)
    await client.post(f"/platform/partners/{partner_id}/commission", headers=bearer(admin), json={"commission_pct": 10})
    await pay_invoice(client, owner)
    shares = sorted(c["share_pct"] for c in (await portal(client, partner["portal_key"]))["commissions"])
    assert shares == [10.0, 20.0]


# ---- what a partner can see ----------------------------------------------------------------------------------------------


async def test_a_partner_sees_only_their_own_referrals_and_nothing_inside_a_business(client):
    admin = await make_platform_admin(client)
    _, mine = await approved_partner(client, admin)
    other_id = await apply(client, name="Rival Trackers", phone="0722 333 444")
    other = (await client.post(f"/platform/partners/{other_id}/approve", headers=bearer(admin), json={})).json()
    await referred_owner(client, mine["code"])
    await referred_owner(client, other["code"], business="Rival Haulage", email="rival@example.com")
    seen = await portal(client, mine["portal_key"])
    assert [r["business"] for r in seen["referrals"]] == ["Mwangi Haulage"]
    assert set(seen["referrals"][0]) == {"business", "referred_at", "state", "vehicles"}  # no people, no records, no money of the business
    everything = str(seen)
    assert "mwangi@example.com" not in everything and "Owner Mwangi" not in everything and "Rival" not in everything


async def test_the_key_is_checked_replaced_and_rate_limited(client, rate_limits):
    admin = await make_platform_admin(client)
    partner_id, partner = await approved_partner(client, admin)
    assert (await client.get("/partners/portal")).status_code == 401
    assert (await client.get("/partners/portal", headers={"X-Partner-Key": "nonsense"})).status_code == 401
    assert (await client.get(f"/partners/portal?key={partner['portal_key']}")).status_code == 401  # a key in the address is not accepted
    fresh = (await client.post(f"/platform/partners/{partner_id}/reissue-key", headers=bearer(admin))).json()["portal_key"]
    assert (await client.get("/partners/portal", headers={"X-Partner-Key": partner["portal_key"]})).status_code == 401  # the old key is dead
    assert (await portal(client, fresh))["partner"]["code"] == partner["code"]
    codes = [(await client.get("/partners/portal", headers={"X-Partner-Key": f"guess{i}"})).status_code for i in range(40)]
    assert codes[-1] == 429


async def test_applying_is_limited_to_five_an_hour_from_one_address(client, rate_limits):
    codes = [(await client.post("/partners/apply", json=APPLICATION)).status_code for _ in range(7)]
    assert codes == [201] * 5 + [429, 429]


async def test_what_a_partner_earned_outlives_the_business_that_paid_it(client):
    admin = await make_platform_admin(client)
    _, partner = await approved_partner(client, admin)
    owner = await referred_owner(client, partner["code"])
    await add_vehicle(client, owner, "KCA 123A")
    await pay_invoice(client, owner)
    from app import retention

    business_id = uuid.UUID((await client.get("/auth/me", headers=bearer(owner))).json()["business"]["id"])

    async def erase(db):
        await retention.erase_business(db, business_id)
        await db.commit()

    await plain(erase)
    seen = await portal(client, partner["portal_key"])
    assert seen["totals"]["owed_cents"] == 36_000 and seen["commissions"][0]["business"] == "Mwangi Haulage" and seen["referrals"] == []
