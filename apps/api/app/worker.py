from typing import ClassVar

from arq.connections import RedisSettings

from app.config import settings


async def ping(ctx: dict, value: str) -> str:
    """Smoke-test task proving the queue and worker are wired up."""
    return f"pong:{value}"


class WorkerSettings:
    functions: ClassVar[list] = [ping]
    redis_settings: ClassVar[RedisSettings] = RedisSettings.from_dsn(settings.redis_url)
