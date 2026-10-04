"""Test harness: a dedicated database built from the real migrations, truncated between tests."""

import os
import secrets
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.config import settings

API_DIR = Path(__file__).resolve().parent.parent
TEST_DB = os.getenv("TEST_DB_NAME", "fleettms_test")  # a second session can use its own database and not clash

# Point the app at the test database before anything creates an engine.
_dev_url = make_url(settings.database_url)
settings.database_url = _dev_url.set(database=TEST_DB).render_as_string(hide_password=False)
settings.jwt_secret = secrets.token_urlsafe(32)  # generated per run, never stored


def _create_database_if_missing() -> None:
    admin = _dev_url.set(drivername="postgresql", database="postgres").render_as_string(hide_password=False)
    with psycopg.connect(admin, autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB,)).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{TEST_DB}"')


@pytest.fixture(scope="session", autouse=True)
def _database():
    assert settings.database_url, "DATABASE_URL must be set (see .env.example)"
    _create_database_if_missing()
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "migrations"))
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
async def _clean():
    from app.db import get_engine

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE businesses, users, otp_challenges CASCADE"))
    from app.sms import get_sms_sender

    get_sms_sender().outbox.clear()
    yield


@pytest.fixture(autouse=True)
def _rate_limits_off_by_default():
    """Tests sign in from one address hundreds of times; the ones about rate limits switch them on with `rate_limits`."""
    settings.rate_limits_enabled = False
    yield
    settings.rate_limits_enabled = True


@pytest.fixture
def rate_limits():
    """Rate limits on, with their counters cleared before and after so one test's hits never count against another's."""
    import redis

    def clear():
        r = redis.Redis.from_url(settings.redis_url)
        for key in r.scan_iter("rl:*"):
            r.delete(key)
        r.close()

    clear()
    settings.rate_limits_enabled = True
    yield
    clear()


@pytest.fixture(autouse=True)
def _billing_off_by_default():
    """Most tests are about something else, and a business that has just signed up is on a trial: plan limits and read-only mode are
    switched on only by the tests about them (the `billing` fixture)."""
    settings.enforce_plans, settings.enforce_billing = False, False
    yield
    settings.enforce_plans, settings.enforce_billing = True, True


@pytest.fixture
def billing():
    """Plan limits and read-only mode on, as they are in production."""
    settings.enforce_plans, settings.enforce_billing = True, True
    yield


@pytest.fixture(scope="session", autouse=True)
def _media_dir(tmp_path_factory):
    """Photos written by tests go to a temporary folder, never the real storage."""
    settings.media_dir = str(tmp_path_factory.mktemp("media"))


@pytest.fixture
async def client():
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
