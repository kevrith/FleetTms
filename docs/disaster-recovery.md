# Disaster recovery

Targets (masterplan Section 10): **lose no more than 15 minutes of data** and **be back online within 4 hours**, tested at least twice a year.

## How it works

PostgreSQL writes every change to a write-ahead log (WAL). With archiving on (`deploy/postgres/dr.conf`), each finished WAL segment is copied to a separate place, and once a day a base backup (a consistent copy of the whole database) is taken. To restore, unpack the newest base backup and replay the archived WAL up to the moment wanted, or to the end.

| What | Where | Run |
|---|---|---|
| WAL archive | `BACKUP_DIR/wal/` (the `archive_command` in `deploy/postgres/dr.conf`) | continuously; a quiet database still ships at least every `archive_timeout` (300 s) |
| Base backup | `BACKUP_DIR/base/*.tar.gz` + checksum | `scripts/dr/backup.sh`, daily; keeps 7, and trims the WAL older than the oldest kept (the trimming ran in the drill with one backup; pruning several has not been exercised) |
| Photos and data copies | `BACKUP_DIR/files/<time>/` | `scripts/dr/backup-files.sh`, daily; hard-linked snapshots so each costs only what changed |
| Photos and data copies, when `STORAGE_BACKEND=s3` | the bucket | the provider keeps them durable; turn on **versioning** (and, if the provider offers it, replication to a second region) so a deleted or overwritten file can be got back. `backup-files.sh` only covers the media folder, so it has nothing to copy once everything is in the bucket. The bucket and its keys are not recreated by the restore script: the new machine only needs the same `S3_*` settings |
| Restore | a new container and volume | `scripts/dr/restore.sh <base backup> <latest or a time>` |
| The test of all of it | | `scripts/dr/drill.sh` |

The **recovery point** is what is in the WAL segment that has not been shipped yet when the machine dies. `archive_timeout` bounds it: at 300 seconds, at most about five minutes of writes, a third of the target. A restore never overwrites the damaged database; it makes its own.

## The drill, run on 2026-10-03

`scripts/dr/drill.sh` against a scratch PostgreSQL 16 with TimescaleDB and PostGIS (the same image as development), holding a simulated large customer: **300 vehicles, 12,000 trips, 24,000 fuel entries, 36,000 expenses, 2,005,996 GPS points, 971 MB**.

1. Took a base backup of the running database: **26 seconds, 230 MB** compressed.
2. Wrote 1,000 marker rows (A), noted the time, wrote 1,000 more (B) and 500 more (C), and closed and shipped the WAL segment holding them. Then wrote 300 more (D) that had **not** been shipped.
3. **Destroyed the database container and its volume.** Only the backup folder survived.
4. Restored to the noted moment: **7 seconds** to a database accepting connections and out of recovery. It held A = 1,000 and B = 0 (point in time is exact), and every table count matched the count before the backup.
5. Restored to the end of the archive: **8 seconds**. A = 1,000, B = 1,000, C = 500, **D = 0**: what had not been shipped is gone, which is the recovery point working as described.

Result: **PASS**, with the data loss in this run being 4 seconds of writes (the time between the last shipped segment and the disaster) and the restore taking about 8 seconds against a 4 hour target.

## What this does and does not prove

- It proves the method: base backup plus WAL gives an exact point-in-time restore of a database of this shape, including the TimescaleDB hypertable of GPS points.
- Everything ran on one machine, from a local disk. **Not tested:** restoring from storage in another place over a network; a database ten or a hundred times larger (restore time grows with size: 971 MB took 4 seconds to unpack, so 100 GB is in the order of 7 to 10 minutes of unpacking from fast disk, plus replay, plus whatever the network adds, far inside four hours, but that is arithmetic, not a measurement); the 4 hours as a whole (provisioning a new server, pointing the API, worker and tracker forwarder at it, re-registering anything bound to the old address).
- The restored database was checked with SQL. The API was not started against it in the drill, so "the system is back" is shown for the database, not yet end to end.
- The archive in the drill was a folder on the same disk. Production must ship it somewhere else (another region or provider): see the last lines of `deploy/postgres/dr.conf`.
- WAL archiving was switched on only in the drill container. The development database and the compose file are unchanged; turning it on in production is a deployment step (Sprint 17).
- Backups hold deleted data until they expire (about a week). See `docs/legal/retention-schedule.md`.

## Runbook: the database is lost

1. **Stop the writers** (API and worker) so nothing writes to a half-restored database.
2. Find the newest base backup in `BACKUP_DIR/base/` and decide the target: `latest`, or a time just before the damage (for a mistake rather than a crash).
3. `BACKUP_DIR=... ./scripts/dr/restore.sh base/<file>.tar.gz latest` (on the new server, with the backup folder mounted). Wait for `READY`.
4. Check: `select count(*)` of a few big tables against what you expect, and `alembic current` matches the application's head.
5. Restore the files: copy the newest `files/<time>/` back into the media folder (or point `MEDIA_DIR` at it).
6. Point `DATABASE_URL` at the restored database, start the API and worker, and open `/ready`: every check must be green. The retention job will run again at 03:50; that is expected.
7. Turn archiving back on in the restored database (`deploy/postgres/dr.conf`) and take a new base backup straight away, because the restored database begins a new timeline.
8. Write it up: what was lost (compare the newest record with the time of the disaster), how long it took, what to change. If personal data was involved, start the breach plan (`docs/legal/breach-response-plan.md`).

## Monitoring

- `GET /health` (alive) and `GET /ready` (able to work): database reachable and on the latest migration, Redis, the worker's heartbeat (written every minute), a base backup under 30 hours old (`BACKUP_DIR` set), and the newest shipped WAL segment under 15 minutes old **when there is unshipped WAL** (a quiet database ships nothing and is not a failure). `/ready` answers 503 with short reasons and no customer data.
- `python -m app.uptime_check --url https://api.../ready --url https://app.../` runs from cron on a **different machine**, alerts after two failures in a row (not every minute), reminds every six hours, says when it is back, and tells you by email (`ALERT_EMAILS` and the SMTP settings) and by a chat webhook (`ALERT_WEBHOOK_URL`). The decisions are tested; the delivery was tested against fakes only, not against a real mail server or chat.

## Cadence

Run `scripts/dr/drill.sh` against a copy of production data (or a load-test database) every six months and after any change to backups, and write the result in the progress log. The 15-minute and 4-hour targets are only claims until that has been done on the real hosting.
