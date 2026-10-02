from arq.worker import Worker

from app.queue import get_queue
from app.worker import WorkerSettings


async def test_enqueued_job_runs_on_worker():
    queue = await get_queue()
    job = await queue.enqueue_job("ping", "kbx-123a")
    worker = Worker(
        functions=WorkerSettings.functions,
        redis_settings=WorkerSettings.redis_settings,
        burst=True,
        poll_delay=0.1,
    )
    await worker.main()
    await worker.close()
    assert await job.result(timeout=5) == "pong:kbx-123a"
    await queue.aclose()
