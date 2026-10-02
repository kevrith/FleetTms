from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.config import settings


async def get_queue() -> ArqRedis:
    return await create_pool(RedisSettings.from_dsn(settings.redis_url))
