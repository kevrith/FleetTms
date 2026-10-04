"""Readiness (`/ready`) and the uptime checker: what makes the system report itself unwell, and when a person is told."""

import json
import os
import time
from datetime import UTC, datetime, timedelta

import pytest
from redis.asyncio import Redis

from app import readiness, uptime_check
from app.config import settings


async def worker_alive():
    await readiness.beat()


async def test_liveness_and_readiness_are_public_and_tell_nothing_about_customers(client):
    assert (await client.get("/health")).status_code == 200
    await worker_alive()
    res = await client.get("/ready")
    assert res.status_code == 200
    body = res.json()
    assert body["ready"] is True and body["failing"] == []
    assert set(body["checks"]) == {"database", "redis", "worker", "base_backup", "wal_archive"}
    assert body["checks"]["base_backup"] == {"ok": True, "state": "not configured"}
    assert "@" not in json.dumps(body) and "postgres" not in json.dumps(body).lower()  # no addresses, no connection strings


async def test_a_worker_that_has_not_reported_or_stopped_reporting_makes_the_system_not_ready(client):
    redis = Redis.from_url(settings.redis_url)
    await redis.delete(readiness.HEARTBEAT_KEY)
    res = await client.get("/ready")
    assert res.status_code == 503 and res.json()["failing"] == ["worker"]
    assert "not reported" in res.json()["checks"]["worker"]["reason"]
    await redis.set(readiness.HEARTBEAT_KEY, str(int(time.time()) - 600))
    stale = await client.get("/ready")
    assert stale.status_code == 503 and "last reported" in stale.json()["checks"]["worker"]["reason"]
    await readiness.beat()
    assert (await client.get("/ready")).status_code == 200
    await redis.aclose()


async def test_a_database_behind_on_migrations_or_unreachable_is_not_ready(client, monkeypatch):
    await worker_alive()
    monkeypatch.setattr(readiness, "head_revision", lambda: "9999")
    res = await client.get("/ready")
    assert res.status_code == 503 and "latest migration" in res.json()["checks"]["database"]["reason"]
    monkeypatch.undo()

    def broken():
        raise OSError("connection refused")

    monkeypatch.setattr(readiness, "get_sessionmaker", broken)
    res = await client.get("/ready")
    assert res.status_code == 503 and "cannot be reached" in res.json()["checks"]["database"]["reason"]
    assert "connection refused" not in res.text  # the reason says what, not how


async def test_redis_being_down_makes_the_system_not_ready(client, monkeypatch):
    monkeypatch.setattr(settings, "redis_url", "redis://127.0.0.1:1/0")
    res = await client.get("/ready")
    assert res.status_code == 503 and {"redis", "worker"} <= set(res.json()["failing"])


def test_the_base_backup_check_follows_the_newest_file(tmp_path, monkeypatch):
    assert readiness.check_base_backup() == {"ok": True, "state": "not configured"}
    monkeypatch.setattr(settings, "backup_dir", str(tmp_path))
    assert readiness.check_base_backup()["reason"] == "there is no base backup"
    base = tmp_path / "base"
    base.mkdir()
    old = base / "20260901T020000Z.tar.gz"
    old.write_bytes(b"x")
    os.utime(old, (time.time() - 40 * 3600, time.time() - 40 * 3600))
    assert "40 hours old" in readiness.check_base_backup()["reason"]
    fresh = base / "20261003T020000Z.tar.gz"
    fresh.write_bytes(b"x")
    ok = readiness.check_base_backup()
    assert ok["ok"] is True and ok["age_hours"] < 1


class FakeSession:
    def __init__(self, row):
        self.row = row

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, _statement):
        row = self.row

        class Result:
            def one(self):
                return row

        return Result()


@pytest.mark.parametrize(
    ("mode", "archived_minutes_ago", "failed_minutes_ago", "offset", "ok", "mentions"),
    [
        ("off", None, None, 5000, True, "not configured"),
        ("on", None, None, 5000, False, "nothing has been archived"),
        ("on", 3, None, 5000, True, '"unshipped": true'),
        ("on", 40, None, 5000, False, "minutes old and newer changes are waiting"),
        ("on", 540, None, 24, True, '"unshipped": false'),  # a quiet night: nothing to ship
        ("on", 3, 0, 5000, False, "failed"),
        ("on", 3, 2880, 5000, True, None),  # an old failure that has since succeeded
    ],
)
async def test_the_wal_archive_check_is_the_recovery_point_in_minutes(monkeypatch, mode, archived_minutes_ago, failed_minutes_ago, offset, ok, mentions):
    """The times are worked out inside the test: worked out when the tests are collected they would be an hour stale in a long run."""
    ago = lambda minutes: None if minutes is None else datetime.now(UTC) - timedelta(minutes=minutes)
    row = (mode, ago(archived_minutes_ago), ago(failed_minutes_ago), offset)
    monkeypatch.setattr(readiness, "get_sessionmaker", lambda: (lambda: FakeSession(row)))
    result = await readiness.check_wal_archive()
    assert result["ok"] is ok
    if mentions:
        assert mentions in json.dumps(result)


# ---- the uptime checker ------------------------------------------------------------------------------------------------


def test_one_failure_is_not_an_alert_two_in_a_row_is_and_then_it_is_quiet_until_the_reminder():
    entry, said = uptime_check.decide(None, False, "answered 503", 0)
    assert said is None and entry["failures"] == 1
    entry, said = uptime_check.decide(entry, False, "answered 503", 60)
    assert said == "DOWN: answered 503. It has failed 2 checks in a row."
    for minute in (2, 3, 100, 300):
        entry, said = uptime_check.decide(entry, False, "answered 503", minute * 60)
        assert said is None
    entry, said = uptime_check.decide(entry, False, "answered 503", 7 * 3600)
    assert said == "STILL DOWN for 7.0 hours: answered 503."
    entry, said = uptime_check.decide(entry, True, "", 8 * 3600)
    assert said == "Back up after 480 minutes." and entry == {"failures": 0, "alerted_at": None, "since": None}
    assert uptime_check.decide(entry, True, "", 9 * 3600)[1] is None


def test_a_blip_that_recovers_before_the_threshold_says_nothing():
    entry, _ = uptime_check.decide(None, False, "x", 0, fail_after=3)
    entry, said = uptime_check.decide(entry, False, "x", 60, fail_after=3)
    assert said is None
    entry, said = uptime_check.decide(entry, True, "", 120, fail_after=3)
    assert said is None and entry["failures"] == 0


def test_a_ready_answer_is_judged_by_its_body_and_its_reasons_are_passed_on():
    ready = json.dumps({"ready": True, "checks": {}})
    assert uptime_check.judge(200, ready, "https://api.example.com/ready") == (True, "")
    assert uptime_check.judge(200, json.dumps({"ready": False}), "https://api.example.com/ready") == (False, "answered 200 but not ready")
    assert uptime_check.judge(200, "<html>", "https://api.example.com/ready")[0] is False
    down = json.dumps({"ready": False, "checks": {"database": {"ok": False, "reason": "the database cannot be reached"}, "redis": {"ok": True}}})
    ok, why = uptime_check.judge(503, down, "https://api.example.com/ready")
    assert not ok and "database: the database cannot be reached" in why and "redis" not in why
    assert uptime_check.judge(200, "anything", "https://app.example.com/") == (True, "")
    assert uptime_check.judge(502, "", "https://app.example.com/") == (False, "answered 502")


def test_a_run_remembers_between_runs_alerts_once_and_exits_nonzero_while_down(tmp_path):
    state, sent = tmp_path / "state.json", []
    answers = {"https://api.example.com/ready": (False, "answered 503"), "https://app.example.com/": (True, "")}
    kw = {"fail_after": 2, "repeat_hours": 6, "fetch": lambda url: answers[url], "notify": lambda subject, text: sent.append((subject, text))}
    assert uptime_check.run(list(answers), state, now=0, **kw) == 1 and sent == []
    assert uptime_check.run(list(answers), state, now=60, **kw) == 1
    assert sent == [("FleetTms: https://api.example.com/ready", "DOWN: answered 503. It has failed 2 checks in a row.")]
    assert uptime_check.run(list(answers), state, now=120, **kw) == 1 and len(sent) == 1
    answers["https://api.example.com/ready"] = (True, "")
    assert uptime_check.run(list(answers), state, now=180, **kw) == 0
    assert sent[-1][1] == "Back up after 3 minutes."
    assert json.loads(state.read_text())["https://api.example.com/ready"]["failures"] == 0


def test_alerts_go_to_the_webhook_and_by_email_and_a_broken_channel_does_not_stop_the_other(monkeypatch):
    posted, mails = [], []

    class FakeSmtp:
        def __init__(self, host, port, timeout):
            mails.append({"host": host})

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self):
            pass

        def login(self, user, password):
            pass

        def send_message(self, message):
            mails[-1].update(to=message["To"], subject=message["Subject"], body=message.get_content())

    class Response:
        def raise_for_status(self):
            pass

    monkeypatch.setattr(uptime_check.httpx, "post", lambda url, json, timeout: posted.append((url, json)) or Response())
    monkeypatch.setattr(uptime_check.smtplib, "SMTP", FakeSmtp)
    monkeypatch.setattr(settings, "alert_webhook_url", "https://chat.example.com/hook")
    monkeypatch.setattr(settings, "alert_emails", "a@example.com, b@example.com")
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_from", "alerts@example.com")
    assert uptime_check.send_alert("FleetTms: api", "DOWN: x") == ["webhook", "email"]
    assert posted == [("https://chat.example.com/hook", {"text": "FleetTms: api\nDOWN: x"})]
    assert mails[0]["to"] == "a@example.com, b@example.com" and mails[0]["subject"] == "FleetTms: api" and mails[0]["body"].strip() == "DOWN: x"

    def refuse(url, json, timeout):
        raise uptime_check.httpx.ConnectError("no route")

    monkeypatch.setattr(uptime_check.httpx, "post", refuse)
    assert uptime_check.send_alert("s", "t") == ["email"]


def test_with_no_channel_configured_nothing_is_sent_and_nothing_breaks(monkeypatch):
    for name in ("alert_webhook_url", "alert_emails", "smtp_host"):
        monkeypatch.setattr(settings, name, "")
    assert uptime_check.send_alert("s", "t") == []
