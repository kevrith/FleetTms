#!/usr/bin/env bash
# Restores a base backup plus the archived WAL into a NEW container, to the end of the archive or to one moment in time.
#
#   BACKUP_DIR=/srv/fleettms-backup ./scripts/dr/restore.sh base/20261003T020000Z.tar.gz latest
#   BACKUP_DIR=/srv/fleettms-backup ./scripts/dr/restore.sh base/20261003T020000Z.tar.gz "2026-10-03 14:05:00+00"
#
# It never touches the original database: it makes its own volume and container (RESTORE_CONTAINER, RESTORE_VOLUME, RESTORE_PORT),
# and refuses to reuse a volume that already holds data. When it prints "READY" the database is accepting connections and is no longer
# in recovery. Archiving stays off in the restored copy until you decide it is the new primary.
set -euo pipefail
BACKUP_DIR=${BACKUP_DIR:?set BACKUP_DIR}
BASE=${1:?base backup file, relative to BACKUP_DIR}
TARGET=${2:-latest}
IMAGE=${DB_IMAGE:-timescale/timescaledb-ha:pg16}
NAME=${RESTORE_CONTAINER:-fleettms-restore-db}
VOLUME=${RESTORE_VOLUME:-fleettms-restore-data}
PORT=${RESTORE_PORT:-5498}
DB_USER=${POSTGRES_USER:-fleettms}
DATA=/home/postgres/pgdata/data

[ -f "$BACKUP_DIR/$BASE" ] || { echo "No such backup: $BACKUP_DIR/$BASE" >&2; exit 1; }
if [ -f "$BACKUP_DIR/${BASE%.tar.gz}.sha256" ]; then (cd "$BACKUP_DIR/$(dirname "$BASE")" && sha256sum -c --quiet "$(basename "${BASE%.tar.gz}").sha256"); fi
if docker volume inspect "$VOLUME" >/dev/null 2>&1; then echo "Volume $VOLUME already exists; remove it first." >&2; exit 1; fi
started=$(date +%s)

docker volume create "$VOLUME" >/dev/null
# Unpack as the database's own user, then tell PostgreSQL it is recovering and where the WAL is.
docker run --rm -v "$VOLUME":$DATA -v "$BACKUP_DIR":/backup:ro --user 1000:1000 --entrypoint sh "$IMAGE" -c "
  set -e
  tar xzf /backup/$BASE -C $DATA
  chmod 700 $DATA
  touch $DATA/recovery.signal
  {
    echo \"restore_command = 'cp /backup/wal/%f %p'\"
    echo \"recovery_target_action = 'promote'\"
    [ '$TARGET' != latest ] && echo \"recovery_target_time = '$TARGET'\"
    true
  } >> $DATA/postgresql.auto.conf
"
unpacked=$(date +%s)
docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" -p "$PORT":5432 -v "$VOLUME":$DATA -v "$BACKUP_DIR":/backup:ro "$IMAGE" postgres -c archive_mode=off -c wal_level=replica -c max_wal_senders=4 >/dev/null

for _ in $(seq 1 7200); do
  if docker exec "$NAME" pg_isready -U "$DB_USER" -q 2>/dev/null && [ "$(docker exec "$NAME" psql -U "$DB_USER" -d postgres -tAc 'select pg_is_in_recovery()' 2>/dev/null)" = "f" ]; then
    now=$(date +%s)
    echo "READY container=$NAME port=$PORT unpack_s=$((unpacked - started)) recovery_s=$((now - unpacked)) total_s=$((now - started))"
    exit 0
  fi
  sleep 1
done
echo "The restored database did not come up; see: docker logs $NAME" >&2
exit 1
