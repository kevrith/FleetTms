from typing import ClassVar

from arq import cron
from arq.connections import RedisSettings

from app.config import settings
from app.etims_service import etims_job
from app.invoicing import contract_invoices_job
from app.lease_notices import lease_charges_job, lease_notices_job
from app.payment_reminders import payment_reminders_job
from app.reminders import NAIROBI, document_reminders_job
from app.report_schedules import scheduled_reports_job
from app.service_reminders import service_reminders_job
from app.tracking_jobs import fraud_sweep_job, fuel_price_job, going_dark_job, gps_retention_job


async def ping(ctx: dict, value: str) -> str:
    """Smoke-test task proving the queue and worker are wired up."""
    return f"pong:{value}"


class WorkerSettings:
    functions: ClassVar[list] = [ping, document_reminders_job, service_reminders_job, scheduled_reports_job, contract_invoices_job, payment_reminders_job, etims_job, lease_charges_job, lease_notices_job, going_dark_job, gps_retention_job, fraud_sweep_job, fuel_price_job]
    cron_jobs: ClassVar[list] = [
        cron(document_reminders_job, hour=7, minute=0),
        cron(service_reminders_job, hour=7, minute=5),
        cron(scheduled_reports_job, hour=6, minute=30),
        cron(contract_invoices_job, day=1, hour=6, minute=45),
        cron(payment_reminders_job, hour=8, minute=0),
        cron(lease_charges_job, day=1, hour=6, minute=50),
        cron(lease_notices_job, hour=8, minute=10),
        cron(going_dark_job, minute=set(range(0, 60, 5))),  # every five minutes
        cron(gps_retention_job, hour=3, minute=30),
        cron(fraud_sweep_job, minute={2, 17, 32, 47}),  # every fifteen minutes
        cron(fuel_price_job, hour=6, minute=15),  # fetch the month's EPRA prices when a feed is set and they are missing
        cron(etims_job, minute=set(range(0, 60, 5))),  # every five minutes: send what is due, retry what failed
    ]
    timezone = NAIROBI
    redis_settings: ClassVar[RedisSettings] = RedisSettings.from_dsn(settings.redis_url)
