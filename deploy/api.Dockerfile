# The API and the background worker run from this one image (the worker is `arq app.worker.WorkerSettings`).
# Build from the repository root:  docker build -f deploy/api.Dockerfile -t fleettms-api apps/api
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt constraints.txt ./
# A slow or flaky network must not make a build fail: more patience and more retries than pip's defaults.
RUN pip install --retries 10 --timeout 120 -r requirements.txt -c constraints.txt

COPY alembic.ini pyproject.toml ./
COPY migrations ./migrations
COPY app ./app

# Not root. Photos and data copies go to /data/media, which the compose file mounts as a volume that is backed up.
RUN useradd --system --uid 10001 --home /app fleettms && mkdir -p /data/media && chown fleettms /data/media
USER fleettms
ENV MEDIA_DIR=/data/media

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

# Several processes: the heavy reports are CPU-bound and one process would make everything else wait behind them (docs/performance.md).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
