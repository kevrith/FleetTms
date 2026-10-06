#!/bin/sh
# Start command for Render's free web service, which has no separate worker service and no pre-deploy step:
# migrate, run the background jobs beside the API in the same instance, then serve.
set -e
alembic upgrade head
arq app.worker.WorkerSettings &
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1
