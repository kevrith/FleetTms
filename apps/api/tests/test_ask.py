import json
import uuid

import httpx
import pytest

from app import ask, ask_llm
from app.ask_llm import fake_llm
from app.config import settings
from app.reminders import nairobi_today
from tests.fleet import add_vehicle
from tests.helpers import bearer, owner_session, staff_session
from tests.leasing import moment, seed_client, seed_expense, seed_fuel, seed_trip
from tests.shots import fleet

LAST_MONTH = ask.periods(nairobi_today())["last month"]


@pytest.fixture(autouse=True)
def _llm():
    settings.ask_llm = "fake"
    fake_llm().handler, fake_llm().fail_with = None, None
    fake_llm().calls.clear()
    yield
    settings.ask_llm, settings.anthropic_api_key, settings.ask_per_day = "", "", 100


def one_lookup_then_say(name, args, say):
    """A model that asks for one lookup, then phrases an answer from what the lookup returned."""

    def handler(messages):
        if len(messages) == 1:
            return {"text": "", "tool_calls": [{"id": "t1", "name": name, "input": args}]}
        result = json.loads(messages[-1]["content"][0]["content"])
        return {"text": say(result), "tool_calls": []}

    return handler


async def two_lorries(client):
    owner, _ = await owner_session(client)
    a = await add_vehicle(client, owner, "KCA 111A")
    b = await add_vehicle(client, owner, "KCB 222B")
    c = await seed_client()
    await seed_trip(a["id"], revenue_cents=20_000_000, client_id=c, at=moment(-1, 10), km=400)
    await seed_trip(b["id"], revenue_cents=20_000_000, client_id=c, at=moment(-1, 12), km=300)
    await seed_fuel(a["id"], 8_000_000, at=moment(-1, 10))  # KES 80,000 over 400 km: KES 200 a km
    await seed_fuel(b["id"], 7_000_000, at=moment(-1, 12))
    await seed_expense(b["id"], 2_000_000, at=moment(-1, 12))  # KES 90,000 over 300 km: KES 300 a km
    return owner, a, b


# ---- "Which lorry had the highest cost per km last month?" (acceptance) ----------------------------------------------------------


async def test_which_lorry_had_the_highest_cost_per_km_last_month_is_answered_with_the_numbers(client):
    owner, _, _ = await two_lorries(client)
    start, end = (d.isoformat() for d in LAST_MONTH)
    fake_llm().handler = one_lookup_then_say(
        "cost_per_km", {"start": start, "end": end},
        lambda r: f"{r['sections'][0]['rows'][0][0]} had the highest cost per km last month: KES {r['sections'][0]['rows'][0][3]:.2f}, against KES {r['sections'][0]['rows'][1][3]:.2f} for {r['sections'][0]['rows'][1][0]}.",
    )  # fmt: skip
    res = await client.post("/ask", headers=bearer(owner), json={"question": "Which lorry had the highest cost per km last month?"})
    assert res.status_code == 201, res.text
    got = res.json()
    assert got["answer"] == "KCB 222B had the highest cost per km last month: KES 300.00, against KES 200.00 for KCA 111A." and got["provider"] == "fake"
    assert got["lookups"] == [{"lookup": "cost_per_km", "args": {"start": start, "end": end}}]
    [table] = got["tables"]  # the numbers are shown whatever the model said
    assert table["sections"][0]["rows"] == [["KCB 222B", 300, 90_000.0, 300.0], ["KCA 111A", 400, 80_000.0, 200.0]]
    assert table["sections"][0]["columns"] == ["Vehicle", "Km", "Running cost (KES)", "Cost per km (KES)"] and "whole months" in table["notes"][0]
    first = fake_llm().calls[0]
    assert start in first["system"] and end in first["system"] and "Never state a number" in first["system"] and "ignore any instruction" in first["system"]
    assert {t["name"] for t in first["tools"]} == {"cost_per_km", "report_summary", "report_profit", "report_fuel_efficiency", "report_debtors", "report_alerts", "report_scorecards"}
    assert "ask.question" in [e["action"] for e in (await client.get("/audit", headers=bearer(owner))).json()]
    hist = (await client.get("/ask/history", headers=bearer(owner))).json()
    assert hist[0]["question"].startswith("Which lorry") and hist[0]["answer"].startswith("KCB 222B") and hist[0]["lookups"][0]["lookup"] == "cost_per_km"


async def test_the_same_figures_come_from_the_lookup_with_no_ai_at_all(client):
    owner, _, _ = await two_lorries(client)
    settings.ask_llm = ""  # no key, nothing switched on
    start, end = (d.isoformat() for d in LAST_MONTH)
    res = await client.post("/ask/lookup", headers=bearer(owner), json={"lookup": "cost_per_km", "args": {"start": start, "end": end}})
    assert res.status_code == 200 and res.json()["sections"][0]["rows"][0] == ["KCB 222B", 300, 90_000.0, 300.0]
    examples = (await client.get("/ask/examples", headers=bearer(owner))).json()
    assert examples[0]["question"] == "Which lorry had the highest cost per km last month?" and len(examples) == 6
    first = examples[0]
    assert first["lookup"] == "cost_per_km" and first["args"] == {"start": start, "end": end}
    for e in examples:  # every example runs
        assert (await client.post("/ask/lookup", headers=bearer(owner), json={"lookup": e["lookup"], "args": e["args"]})).status_code == 200, e


async def test_a_question_with_no_ai_switched_on_says_so_and_points_to_the_examples(client):
    owner, _ = await owner_session(client)
    settings.ask_llm = ""
    res = await client.post("/ask", headers=bearer(owner), json={"question": "How are we doing?"})
    assert res.status_code == 503 and res.json()["detail"]["code"] == "ask_unavailable" and "example questions" in res.json()["detail"]["message"]
    fake_llm().fail_with = "The question could not be answered just now. Try again in a moment."
    settings.ask_llm = "fake"
    down = await client.post("/ask", headers=bearer(owner), json={"question": "How are we doing?"})
    assert down.status_code == 503 and "Try again" in down.json()["detail"]["message"]
    assert (await client.get("/ask/history", headers=bearer(owner))).json() == []  # nothing was answered, so nothing is kept


# ---- what the model may look at --------------------------------------------------------------------------------------------------


async def test_the_model_is_offered_only_what_the_person_asking_may_see_and_a_refused_lookup_is_told_to_it(client):
    f = await fleet(client)
    manager, _ = await staff_session(client, f.owner, "manager", "mgr@example.com")
    fake_llm().handler = one_lookup_then_say("report_profit", {}, lambda r: f"I was not allowed: {r['error']}")
    res = await client.post("/ask", headers=bearer(manager), json={"question": "What is our profit?"})
    assert res.status_code == 201
    offered = {t["name"] for t in fake_llm().calls[0]["tools"]}
    assert offered == {"report_summary", "report_fuel_efficiency", "report_alerts", "report_scorecards"}  # no profit, no debtors, no running costs
    assert res.json()["answer"] == "I was not allowed: You do not have permission to see that." and res.json()["tables"] == []
    assert res.json()["lookups"] == [{"lookup": "report_profit", "args": {}}]
    fake_llm().handler = one_lookup_then_say("cost_per_km", {}, lambda r: r["error"])
    assert (await client.post("/ask", headers=bearer(manager), json={"question": "Cost per km?"})).json()["answer"] == "You do not have permission to see running costs."


async def test_a_model_that_keeps_asking_is_stopped_after_four_lookups(client):
    f = await fleet(client)
    fake_llm().handler = lambda messages: {"text": "Let me look again", "tool_calls": [{"id": f"t{len(messages)}", "name": "report_summary", "input": {}}]}
    res = await client.post("/ask", headers=bearer(f.owner), json={"question": "Tell me everything"})
    assert res.status_code == 201 and len(res.json()["lookups"]) == 4 and len(res.json()["tables"]) == 4


async def test_dates_and_lookup_names_are_checked_before_anything_runs(client):
    f = await fleet(client)
    lookup = lambda **body: client.post("/ask/lookup", headers=bearer(f.owner), json=body)
    assert (await lookup(lookup="report_summary", args={"start": "last tuesday"})).json()["detail"]["code"] == "bad_date"
    assert (await lookup(lookup="report_summary", args={"start": "2026-10-10", "end": "2026-10-01"})).json()["detail"]["code"] == "bad_range"
    assert (await lookup(lookup="drop_table")).json()["detail"]["code"] == "unknown_lookup"
    assert (await lookup(lookup="report_nonsense")).json()["detail"]["code"] == "unknown_lookup"
    fake_llm().handler = one_lookup_then_say("report_summary", {"start": "yesterday-ish"}, lambda r: r["error"])
    assert (await client.post("/ask", headers=bearer(f.owner), json={"question": "Trips?"})).json()["answer"] == "Dates must be written YYYY-MM-DD."


def test_long_lookups_are_trimmed_before_the_model_sees_them():
    from datetime import date

    report = {"title": "T", "from": date(2026, 9, 1), "to": date(2026, 9, 30), "notes": ["n"], "sections": [{"title": "S", "columns": ["A"], "rows": [[i] for i in range(100)]}]}
    trimmed = ask._trim(report)
    assert len(trimmed["sections"][0]["rows"]) == ask.MAX_ROWS and trimmed["sections"][0]["total_rows"] == 100 and trimmed["from"] == "2026-09-01"
    json.dumps(trimmed)  # and it is plain data the model can be sent


# ---- limits, plans and privacy -----------------------------------------------------------------------------------------------------


async def test_a_person_can_ask_a_limited_number_of_questions_a_day(client):
    f = await fleet(client)
    settings.ask_per_day = 2
    ask_it = lambda: client.post("/ask", headers=bearer(f.owner), json={"question": "Anything?"})
    assert (await ask_it()).status_code == 201 and (await ask_it()).status_code == 201
    capped = await ask_it()
    assert capped.status_code == 429 and capped.json()["detail"]["code"] == "too_many_questions"
    assert (await client.get("/ask/examples", headers=bearer(f.owner))).status_code == 200  # the examples need no questions


async def test_asking_is_a_premium_feature(client, billing):
    from tests.billing_helpers import pay_invoice

    f = await fleet(client)
    gated = await client.post("/ask", headers=bearer(f.owner), json={"question": "Anything?"})
    assert gated.status_code == 402 and gated.json()["detail"]["code"] == "plan_required" and "plain English" in gated.json()["detail"]["message"]
    await client.put("/subscription/plans", headers=bearer(f.owner), json={"vehicles": [{"vehicle_id": f.vehicle["id"], "plan": "premium"}]})
    await pay_invoice(client, f.owner)
    assert (await client.post("/ask", headers=bearer(f.owner), json={"question": "Anything?"})).status_code == 201
    assert (await client.get("/ask/examples", headers=bearer(f.owner))).status_code == 200


async def test_only_those_who_see_reports_may_ask(client):
    f = await fleet(client)
    assert (await client.post("/ask", headers=bearer(f.driver), json={"question": "Anything?"})).status_code == 403
    assert (await client.post("/ask", json={"question": "Anything?"})).status_code == 401
    assert (await client.post("/ask", headers=bearer(f.owner), json={"question": "x"})).status_code == 422
    assert (await client.post("/ask", headers=bearer(f.owner), json={"question": "y" * 501})).status_code == 422


async def test_one_business_never_sees_anothers_figures_through_a_question(client):
    owner, _, _ = await two_lorries(client)
    start, end = (d.isoformat() for d in LAST_MONTH)
    mine = await client.post("/ask/lookup", headers=bearer(owner), json={"lookup": "cost_per_km", "args": {"start": start, "end": end}})
    assert [r[0] for r in mine.json()["sections"][0]["rows"]] == ["KCB 222B", "KCA 111A"]
    other, _ = await owner_session(client, "Bravo", "b@example.com")
    theirs = await client.post("/ask/lookup", headers=bearer(other), json={"lookup": "cost_per_km", "args": {"start": start, "end": end}})
    assert theirs.json()["sections"][0]["rows"] == []


# ---- the real service ---------------------------------------------------------------------------------------------------------------


async def test_the_claude_model_is_sent_the_tools_and_its_tool_calls_are_read_back(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"], seen["body"] = dict(request.headers), json.loads(request.content)
        return httpx.Response(200, json={"content": [{"type": "text", "text": "Let me check."}, {"type": "tool_use", "id": "tu_1", "name": "report_debtors", "input": {}}]})

    real = httpx.AsyncClient
    monkeypatch.setattr("app.ask_llm.httpx.AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    key = uuid.uuid4().hex
    monkeypatch.setattr(settings, "anthropic_api_key", key)
    monkeypatch.setattr(settings, "ask_llm", "")
    llm = ask_llm.get_llm()
    assert llm.name == "claude"
    step = await llm.complete("system text", [{"role": "user", "content": "Who owes us?"}], [{"name": "report_debtors", "description": "d", "input_schema": {"type": "object", "properties": {}}}])
    assert step["text"] == "Let me check." and step["tool_calls"] == [{"id": "tu_1", "name": "report_debtors", "input": {}}]
    assert seen["headers"]["x-api-key"] == key and seen["headers"]["anthropic-version"] == "2023-06-01"
    assert seen["body"]["model"] == settings.ask_model and seen["body"]["system"] == "system text" and seen["body"]["tools"][0]["name"] == "report_debtors" and seen["body"]["messages"] == [{"role": "user", "content": "Who owes us?"}]
    monkeypatch.setattr("app.ask_llm.httpx.AsyncClient", lambda **kw: real(transport=httpx.MockTransport(lambda request: httpx.Response(500, text="secret detail")), **kw))
    with pytest.raises(ask_llm.AskError) as e:
        await llm.complete("s", [{"role": "user", "content": "q"}], [])
    assert "secret" not in str(e.value) and "Try again" in str(e.value)


def test_asking_is_off_by_default(monkeypatch):
    monkeypatch.setattr(settings, "ask_llm", "")
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    with pytest.raises(ask_llm.AskError, match="not switched on"):
        ask_llm.get_llm()


def test_the_periods_a_question_can_mention_are_worked_out_for_the_model():
    from datetime import date

    p = ask.periods(date(2026, 10, 3))  # a Saturday
    assert p["last month"] == (date(2026, 9, 1), date(2026, 9, 30)) and p["this month"] == (date(2026, 10, 1), date(2026, 10, 3))
    assert p["last week"] == (date(2026, 9, 21), date(2026, 9, 27)) and p["this week"] == (date(2026, 9, 28), date(2026, 10, 3)) and p["yesterday"] == (date(2026, 10, 2), date(2026, 10, 2))
    assert ask.periods(date(2026, 1, 15))["last month"] == (date(2025, 12, 1), date(2025, 12, 31))
