"""Recurring work: a schedule puts each coming day's job (or contract trip) in the diary once, and says when it could not give it a lorry."""

import uuid
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select

from app import invoicing, recurrence, recurrence_rules
from app.jobs_service import sync_job
from app.models import Job, JobStatus, Trip, TripStatus
from app.reminders import nairobi_today
from app.sms import get_sms_sender
from tests.helpers import bearer, driver_session
from tests.leasing import in_db, set_phone
from tests.test_clients import add_client, add_route
from tests.test_jobs import dispatch, setup, when

TODAY = nairobi_today()
SIX = "06:00"


async def make_job(client, f, c, r, **extra):
    body = {"client_id": c["id"], "route_id": r["id"], "cargo_description": "Cement, 28 t", "weight_tonnes": "28", "trips": 1, **extra}
    res = await client.post("/jobs", headers=bearer(f.owner), json=body)
    assert res.status_code == 201, res.text
    return res.json()


async def schedule(client, f, job, **extra):
    body = {"template_job_id": job["id"], "cadence": "daily", "pickup_time": SIX, **extra}
    res = await client.post("/job-schedules", headers=bearer(f.owner), json=body)
    assert res.status_code == 201, res.text
    return res.json()


async def run(schedule_id, today=TODAY):
    """The early-morning job, for one schedule, as if it were `today`."""

    async def go(db):
        from app.models import JobSchedule

        s = (await db.execute(select(JobSchedule).where(JobSchedule.id == uuid.UUID(schedule_id)))).scalar_one()
        return [(r.occurrence_on, r.job_id, r.trip_id, r.note) for r in await recurrence.materialise(db, s, today)]

    return await in_db(go)


async def all_jobs(client, f):
    return (await client.get("/jobs", headers=bearer(f.owner))).json()


# ---- when work falls due -------------------------------------------------------------------------------------------------


def test_daily_weekly_and_monthly_dates_fall_where_they_should():
    d = date(2026, 10, 5)  # a Monday
    kw = {"starts_on": date(2026, 1, 1), "ends_on": None, "first": d, "last": d + timedelta(days=13)}
    assert recurrence_rules.due_dates("daily", weekdays=[], day_of_month=None, **kw) == [d + timedelta(days=i) for i in range(14)]
    assert recurrence_rules.due_dates("weekly", weekdays=[0, 3], day_of_month=None, **kw) == [date(2026, 10, 5), date(2026, 10, 8), date(2026, 10, 12), date(2026, 10, 15)]
    assert recurrence_rules.due_dates("monthly", weekdays=[], day_of_month=15, **kw) == [date(2026, 10, 15)]
    assert recurrence_rules.due_dates("monthly", weekdays=[], day_of_month=1, **{**kw, "first": date(2026, 10, 1), "last": date(2026, 12, 31)}) == [date(2026, 10, 1), date(2026, 11, 1), date(2026, 12, 1)]


def test_a_schedule_does_not_start_before_its_start_or_run_past_its_end():
    kw = {"weekdays": [], "day_of_month": None, "first": date(2026, 10, 1), "last": date(2026, 10, 10)}
    assert recurrence_rules.due_dates("daily", starts_on=date(2026, 10, 8), ends_on=None, **kw) == [date(2026, 10, 8), date(2026, 10, 9), date(2026, 10, 10)]
    assert recurrence_rules.due_dates("daily", starts_on=date(2026, 10, 1), ends_on=date(2026, 10, 3), **kw) == [date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3)]
    assert recurrence_rules.due_dates("daily", starts_on=date(2026, 11, 1), ends_on=None, **kw) == []


def test_the_pickup_clock_is_nairobi_time():
    moment = recurrence_rules.pickup_at(date(2026, 10, 5), time(6, 0))
    assert moment.astimezone(UTC) == datetime(2026, 10, 5, 3, 0, tzinfo=UTC)


# ---- repeating a job ----------------------------------------------------------------------------------------------------


async def test_a_schedule_puts_each_coming_day_in_the_diary_as_a_new_job_once(client):
    f, c, r = await setup(client)
    template = await make_job(client, f, c, r)
    s = await schedule(client, f, template, lead_days=2)
    assert s["template"] == template["number"] and s["next"][0] == TODAY.isoformat() and s["is_active"] is True
    made = await run(s["id"])
    assert [m[0] for m in made] == [TODAY + timedelta(days=i) for i in range(3)]
    jobs = await all_jobs(client, f)
    assert len(jobs) == 4  # the template and three repeats
    repeats = sorted((j for j in jobs if j["id"] != template["id"]), key=lambda j: j["pickup_at"])
    assert all(j["client_name"] == c["name"] and j["billing_method"] == "per_tonne" for j in repeats)
    pickup = datetime.fromisoformat(repeats[0]["pickup_at"]).astimezone(UTC)
    assert pickup.hour == 3 and (datetime.fromisoformat(repeats[0]["deliver_by"]) - datetime.fromisoformat(repeats[0]["pickup_at"])) == timedelta(hours=24)
    assert await run(s["id"]) == []  # running again changes nothing
    assert len(await all_jobs(client, f)) == 4
    assert [m[0] for m in await run(s["id"], TODAY + timedelta(days=1))] == [TODAY + timedelta(days=3)]  # tomorrow's run adds only the new day


async def test_a_weekly_schedule_only_makes_the_chosen_weekdays(client):
    f, c, r = await setup(client)
    template = await make_job(client, f, c, r)
    monday = TODAY + timedelta(days=(7 - TODAY.weekday()) % 7)
    s = await schedule(client, f, template, cadence="weekly", weekdays=[0, 3], lead_days=7)
    made = await run(s["id"], monday)
    assert [d.weekday() for d, *_ in made] == [0, 3, 0]  # Monday, Thursday, and the next Monday: a week ahead including both ends
    assert [d for d, *_ in made] == [monday, monday + timedelta(days=3), monday + timedelta(days=7)]


async def test_a_monthly_schedule_makes_the_chosen_day_and_the_end_date_stops_it(client):
    f, c, r = await setup(client)
    template = await make_job(client, f, c, r)
    s = await schedule(client, f, template, cadence="monthly", day_of_month=15, lead_days=14, starts_on="2026-10-01", ends_on="2026-11-20")
    assert [d for d, *_ in await run(s["id"], date(2026, 10, 10))] == [date(2026, 10, 15)]
    assert [d for d, *_ in await run(s["id"], date(2026, 11, 10))] == [date(2026, 11, 15)]
    assert await run(s["id"], date(2026, 12, 10)) == []  # past the end date


async def test_a_paused_schedule_makes_nothing_and_resuming_carries_on(client):
    f, c, r = await setup(client)
    template = await make_job(client, f, c, r)
    s = await schedule(client, f, template, lead_days=0)
    paused = await client.put(f"/job-schedules/{s['id']}", headers=bearer(f.owner), json={"is_active": False})
    assert paused.json()["is_active"] is False and paused.json()["next"][0] == TODAY.isoformat()
    assert await run(s["id"]) == []
    await client.put(f"/job-schedules/{s['id']}", headers=bearer(f.owner), json={"is_active": True})
    assert len(await run(s["id"])) == 1


async def test_a_cancelled_template_makes_nothing_more(client):
    f, c, r = await setup(client)
    template = await make_job(client, f, c, r)
    s = await schedule(client, f, template, lead_days=0)
    assert (await client.post(f"/jobs/{template['id']}/cancel", headers=bearer(f.owner))).status_code == 200
    assert await run(s["id"]) == []
    assert (await client.post("/job-schedules", headers=bearer(f.owner), json={"template_job_id": template["id"], "cadence": "daily", "pickup_time": SIX})).status_code == 409


# ---- sending a lorry out ------------------------------------------------------------------------------------------------


async def test_a_schedule_with_a_lorry_also_assigns_it_and_its_crew_to_each_day(client):
    f, c, r = await setup(client)
    template = await make_job(client, f, c, r)
    s = await schedule(client, f, template, lead_days=1, vehicle_id=f.vehicle["id"])
    made = await run(s["id"])
    assert len(made) == 2 and all(trip_id and not note for _, _, trip_id, note in made)

    async def trips(db):
        rows = (await db.execute(select(Trip).where(Trip.job_id.in_([m[1] for m in made])))).scalars().all()
        return [(t.vehicle_id, t.driver_membership_id is not None, t.status, t.scheduled_for) for t in rows]

    got = await in_db(trips)
    assert len(got) == 2 and all(v == uuid.UUID(f.vehicle["id"]) and has_driver and st == TripStatus.SCHEDULED for v, has_driver, st, _ in got)
    assert min(w for *_, w in got).astimezone(UTC).hour == 3


async def test_a_day_that_cannot_be_given_a_lorry_is_still_made_and_the_managers_are_told(client):
    f, c, r = await setup(client)
    await set_phone("owner@example.com", "+254711000111")
    other = await make_job(client, f, c, r)
    booked = await dispatch(client, f, other, scheduled_for=when(days=1, hour=3))  # the lorry is already out at 06:00 Nairobi tomorrow
    assert booked.status_code == 201, booked.text
    template = await make_job(client, f, c, r)
    s = await schedule(client, f, template, lead_days=1, vehicle_id=f.vehicle["id"])
    get_sms_sender().outbox.clear()
    made = await run(s["id"])
    free, clash = sorted(made, key=lambda m: m[0])
    assert free[2] is not None and free[3] is None  # today: a lorry was free
    assert clash[1] is not None and clash[2] is None and clash[3]  # tomorrow: the job is in the diary, with the reason it has no lorry
    texts = [t for phone, t in get_sms_sender().outbox if phone == "+254711000111"]
    assert len(texts) == 1 and "has no lorry" in texts[0] and c["name"] in texts[0]
    assert len(await all_jobs(client, f)) == 4  # the job that took the lorry, the template, and the two made


# ---- monthly contracts ----------------------------------------------------------------------------------------------------


async def contract(client, f):
    c = await add_client(client, f.owner, billing_method="monthly_contract", rate_cents=50_000_000, name="Nakuru Cement Ltd")
    r = await add_route(client, f.owner, c["id"], name="Mombasa to Nakuru")
    return await make_job(client, f, c, r, billing_method="monthly_contract", rate_cents=50_000_000, trips=1)


async def test_a_monthly_contract_schedule_needs_a_lorry_and_sends_trips_not_new_jobs(client):
    f, _, _ = await setup(client)
    job = await contract(client, f)
    refused = await client.post("/job-schedules", headers=bearer(f.owner), json={"template_job_id": job["id"], "cadence": "daily", "pickup_time": SIX})
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "lorry_needed"
    s = await schedule(client, f, job, lead_days=2, vehicle_id=f.vehicle["id"])
    assert s["contract"] is True
    made = await run(s["id"])
    assert len(made) == 3 and {m[1] for m in made} == {uuid.UUID(job["id"])} and all(m[2] for m in made)  # three trips under the one contract job

    async def state(db):
        job_row = (await db.execute(select(Job).where(Job.id == uuid.UUID(job["id"])))).scalar_one()
        count = len((await db.execute(select(Trip).where(Trip.job_id == job_row.id))).scalars().all())
        return job_row.trips_planned, count, len((await db.execute(select(Job))).scalars().all())

    planned, trips, jobs = await in_db(state)
    assert planned >= 3 and trips == 3 and jobs == 1  # no extra job, so no extra monthly fee


async def test_the_contract_is_not_marked_finished_while_its_schedule_is_running_and_still_bills_once_a_month(client):
    f, _, _ = await setup(client)
    job = await contract(client, f)
    s = await schedule(client, f, job, lead_days=0, vehicle_id=f.vehicle["id"])
    [(_, _, trip_id, _)] = await run(s["id"])
    job_id = uuid.UUID(job["id"])

    async def finish_the_trip(db):
        trip = (await db.execute(select(Trip).where(Trip.id == trip_id))).scalar_one()
        trip.status = TripStatus.COMPLETED
        await sync_job(db, job_id)
        return (await db.execute(select(Job.status, Job.completed_at).where(Job.id == job_id))).one()

    status, completed_at = await in_db(finish_the_trip)
    assert status != JobStatus.COMPLETED and completed_at is None  # more work is coming

    await client.put(f"/job-schedules/{s['id']}", headers=bearer(f.owner), json={"is_active": False})

    async def sync_again(db):
        await sync_job(db, job_id)
        return (await db.execute(select(Job.status).where(Job.id == job_id))).scalar_one()

    assert await in_db(sync_again) == JobStatus.COMPLETED  # with no schedule left, the finished work finishes the job

    async def invoices(db):
        await db.execute(Job.__table__.update().where(Job.id == job_id).values(status=JobStatus.DISPATCHED, completed_at=None))
        first = await invoicing.contract_invoices(db, nairobi_today())
        second = await invoicing.contract_invoices(db, nairobi_today())
        return len(first), len(second)

    assert await in_db(invoices) == (1, 0)  # one invoice for the month however many trips ran


# ---- checks and permissions -----------------------------------------------------------------------------------------------


async def test_a_schedule_must_make_sense_and_names_only_real_things(client):
    f, c, r = await setup(client)
    template = await make_job(client, f, c, r)
    bad = {"template_job_id": template["id"], "pickup_time": SIX}
    post = lambda **kw: client.post("/job-schedules", headers=bearer(f.owner), json={**bad, **kw})
    assert (await post(cadence="weekly")).status_code == 422  # which days?
    assert (await post(cadence="weekly", weekdays=[7])).status_code == 422
    assert (await post(cadence="monthly")).status_code == 422  # which day?
    assert (await post(cadence="monthly", day_of_month=31)).status_code == 422  # every month has a 28th, not always a 31st
    assert (await post(cadence="daily", starts_on="2026-10-05", ends_on="2026-10-01")).status_code == 422
    assert (await post(cadence="daily", vehicle_id=str(uuid.uuid4()))).status_code == 404
    assert (await post(cadence="daily", template_job_id=str(uuid.uuid4()))).status_code == 404
    daily = (await post(cadence="daily")).json()
    assert (await client.put(f"/job-schedules/{daily['id']}", headers=bearer(f.owner), json={"weekdays": [1]})).status_code == 422  # weekdays are for a weekly schedule


async def test_only_people_who_manage_jobs_can_use_schedules_and_no_other_business_can_see_them(client):
    f, c, r = await setup(client)
    template = await make_job(client, f, c, r)
    s = await schedule(client, f, template)
    driver = await driver_session(client, f.owner, "0733333333")
    for method, path in (("GET", "/job-schedules"), ("GET", f"/job-schedules/{s['id']}"), ("POST", f"/job-schedules/{s['id']}/run")):
        assert (await client.request(method, path, headers=bearer(driver))).status_code == 403, path
    from tests.helpers import owner_session

    other, _ = await owner_session(client, "Bravo Transporters", "b@example.com")
    assert (await client.get("/job-schedules", headers=bearer(other))).json() == []
    assert (await client.get(f"/job-schedules/{s['id']}", headers=bearer(other))).status_code == 404
    assert (await client.put(f"/job-schedules/{s['id']}", headers=bearer(other), json={"is_active": False})).status_code == 404


async def test_what_the_schedule_does_is_written_in_the_audit_trail_and_the_runs_are_listed(client):
    f, c, r = await setup(client)
    template = await make_job(client, f, c, r)
    s = await schedule(client, f, template, lead_days=1)
    await run(s["id"])
    actions = [a["action"] for a in (await client.get("/audit", headers=bearer(f.owner))).json()]
    assert actions.count("job.scheduled") == 2 and "job_schedule.created" in actions
    seen = (await client.get(f"/job-schedules/{s['id']}", headers=bearer(f.owner))).json()
    assert [r["day"] for r in seen["runs"]] == [(TODAY + timedelta(days=1)).isoformat(), TODAY.isoformat()]


async def test_the_morning_run_goes_through_every_business_and_one_broken_schedule_does_not_stop_the_rest(client):
    f, c, r = await setup(client)
    good = await make_job(client, f, c, r)
    broken = await make_job(client, f, c, r)
    await schedule(client, f, good, lead_days=0)
    s2 = await schedule(client, f, broken, lead_days=0)
    await client.post(f"/jobs/{broken['id']}/cancel", headers=bearer(f.owner))
    assert s2["is_active"]
    assert await recurrence.run_all(TODAY) == 1  # the live schedule; the one whose job was cancelled makes nothing
    assert await recurrence.run_all(TODAY) == 0  # and a second run the same morning makes nothing
    from app.worker import WorkerSettings

    assert any(job.coroutine is recurrence.recurring_jobs_job for job in WorkerSettings.cron_jobs)
