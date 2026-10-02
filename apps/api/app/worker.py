from typing import ClassVar

from arq import cron
from arq.connections import RedisSettings

from app.config import settings
from app.reminders import NAIROBI, document_reminders_job


async def ping(ctx: dict, value: str) -> str:
    """Smoke-test task proving the queue and worker are wired up."""
    return f"pong:{value}"


class WorkerSettings:
    functions: ClassVar[list] = [ping, document_reminders_job]
    cron_jobs: ClassVar[list] = [cron(document_reminders_job, hour=7, minute=0)]
    timezone = NAIROBI
    redis_settings: ClassVar[RedisSettings] = RedisSettings.from_dsn(settings.redis_url)
