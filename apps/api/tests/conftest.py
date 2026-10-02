"""Test harness: a dedicated database built from the real migrations, truncated between tests."""

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
TEST_DB = "fleettms_test"

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


@pytest.fixture
async def client():
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
