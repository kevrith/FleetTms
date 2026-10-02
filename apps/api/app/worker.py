from typing import ClassVar

from arq import cron
from arq.connections import RedisSettings

from app.config import settings
from app.invoicing import contract_invoices_job
from app.reminders import NAIROBI, document_reminders_job
from app.report_schedules import scheduled_reports_job
from app.service_reminders import service_reminders_job


async def ping(ctx: dict, value: str) -> str:
    """Smoke-test task proving the queue and worker are wired up."""
    return f"pong:{value}"


class WorkerSettings:
    functions: ClassVar[list] = [ping, document_reminders_job, service_reminders_job, scheduled_reports_job, contract_invoices_job]
    cron_jobs: ClassVar[list] = [
        cron(document_reminders_job, hour=7, minute=0),
        cron(service_reminders_job, hour=7, minute=5),
        cron(scheduled_reports_job, hour=6, minute=30),
        cron(contract_invoices_job, day=1, hour=6, minute=45),
    ]
    timezone = NAIROBI
    redis_settings: ClassVar[RedisSettings] = RedisSettings.from_dsn(settings.redis_url)
