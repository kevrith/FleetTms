#!/usr/bin/env bash
# A restore drill: the disaster-recovery acceptance test (sprint plan 16: "a full restore from backup succeeds within the target").
#
# It takes a real base backup of a running database container that has WAL archiving on (deploy/postgres/dr.conf), writes marker rows
# before and after a chosen moment, destroys the database and its volume, then restores from the backup and the archive alone, twice:
#   1. to the chosen moment (point in time): the rows written before it are there, the rows after it are not;
#   2. to the end of the archive: everything that was archived is there, and what was not yet archived is lost. That last part is the
#      measured data-loss window (the "recovery point").
# It prints the time each step took (the "recovery time") and PASS or FAIL against the targets: 15 minutes of data, 4 hours back online.
#
#   DB_CONTAINER=fleettms-drill-db DB_NAME=fleettms_drill DB_VOLUME=fleettms-drill-data BACKUP_DIR=/path/to/drill ./scripts/dr/drill.sh
#
# Only ever point it at a scratch database: it DESTROYS DB_CONTAINER and DB_VOLUME. It refuses names that do not contain "drill".
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
C=${DB_CONTAINER:?}; DB=${DB_NAME:?}; VOL=${DB_VOLUME:?}; DIR=${BACKUP_DIR:?}
DB_USER=${POSTGRES_USER:-fleettms}
case "$C$VOL$DB" in *drill*) ;; *) echo "Refusing: container, volume and database names must contain 'drill'." >&2; exit 2;; esac
RPO_TARGET_S=900; RTO_TARGET_S=14400
sql() { docker exec "$1" psql -U "$DB_USER" -d "$DB" -At -c "$2"; }
now() { date +%s; }
TABLES="vehicles trips fuel_entries expenses location_points memberships"
counts() { for t in $TABLES; do printf '%s=%s ' "$t" "$(sql "$1" "select count(*) from $t")"; done; }

echo "== 1. state before the backup"
BEFORE=$(counts "$C"); echo "$BEFORE"
SIZE=$(sql "$C" "select pg_size_pretty(pg_database_size('$DB'))"); echo "database size: $SIZE"

echo "== 2. base backup"
t0=$(now); BACKUP_DIR="$DIR" DB_CONTAINER="$C" "$HERE/backup.sh"; BACKUP_S=$(( $(now) - t0 ))
BASE=base/$(ls -1 "$DIR"/base/*.tar.gz | sort | tail -n 1 | xargs -n1 basename)
echo "backup file: $BASE (${BACKUP_S}s)"

echo "== 3. work after the backup: markers A, then the chosen moment, then B and C"
sql "$C" "create table if not exists dr_markers (id serial primary key, batch text, at timestamptz default clock_timestamp())" >/dev/null
sql "$C" "insert into dr_markers (batch) select 'A' from generate_series(1,1000)" >/dev/null
sleep 3
TARGET=$(sql "$C" "select to_char(clock_timestamp(), 'YYYY-MM-DD HH24:MI:SS.USOF')")
sleep 3
sql "$C" "insert into dr_markers (batch) select 'B' from generate_series(1,1000)" >/dev/null
sql "$C" "insert into dr_markers (batch) select 'C' from generate_series(1,500)" >/dev/null
echo "chosen moment: $TARGET"
echo "closing and archiving the WAL segment that holds A, B and C"
LAST=$(sql "$C" "select last_archived_wal from pg_stat_archiver")
sql "$C" "select pg_switch_wal()" >/dev/null
for _ in $(seq 1 120); do [ "$(sql "$C" 'select last_archived_wal from pg_stat_archiver')" != "$LAST" ] && break; sleep 1; done
ARCHIVED_AT=$(sql "$C" "select extract(epoch from last_archived_time)::bigint from pg_stat_archiver")
sleep 5
sql "$C" "insert into dr_markers (batch) select 'D' from generate_series(1,300)" >/dev/null  # in a WAL segment that has not been shipped
D_AT=$(date +%s)

echo "== 4. DISASTER: the database and its volume are destroyed"
docker kill "$C" >/dev/null; docker rm -f "$C" >/dev/null; docker volume rm "$VOL" >/dev/null
DISASTER_AT=$(now)
echo "gone. Only $DIR (base backups and the WAL archive) survives."

echo "== 5. restore to the chosen moment"
export BACKUP_DIR="$DIR" RESTORE_CONTAINER=fleettms-drill-restore-1 RESTORE_VOLUME=fleettms-drill-restore-1-data RESTORE_PORT=5498
R1=$("$HERE/restore.sh" "$BASE" "$TARGET" | tail -1); echo "$R1"
RTO1=$(echo "$R1" | sed -n 's/.*total_s=\([0-9]*\).*/\1/p')
A1=$(sql fleettms-drill-restore-1 "select count(*) from dr_markers where batch='A'"); B1=$(sql fleettms-drill-restore-1 "select count(*) from dr_markers where batch='B'")
AFTER1=$(counts fleettms-drill-restore-1)
echo "markers at the chosen moment: A=$A1 (want 1000), B=$B1 (want 0)"
echo "tables: $AFTER1"
docker rm -f fleettms-drill-restore-1 >/dev/null; docker volume rm fleettms-drill-restore-1-data >/dev/null

echo "== 6. restore to the end of the archive"
export RESTORE_CONTAINER=fleettms-drill-restore-2 RESTORE_VOLUME=fleettms-drill-restore-2-data RESTORE_PORT=5497
R2=$("$HERE/restore.sh" "$BASE" latest | tail -1); echo "$R2"
RTO2=$(echo "$R2" | sed -n 's/.*total_s=\([0-9]*\).*/\1/p')
count() { sql fleettms-drill-restore-2 "select count(*) from dr_markers where batch='$1'"; }
A2=$(count A); B2=$(count B); C2=$(count C); D2=$(count D)
echo "markers at the end of the archive: A=$A2 B=$B2 C=$C2 D=$D2 (D was never shipped, so it is lost)"
LOSS_S=$(( D_AT - ARCHIVED_AT ))
docker rm -f fleettms-drill-restore-2 >/dev/null; docker volume rm fleettms-drill-restore-2-data >/dev/null

echo "== result"
echo "database size            : $SIZE"
echo "base backup              : ${BACKUP_S}s"
echo "restore to a moment      : ${RTO1}s   (target ${RTO_TARGET_S}s)"
echo "restore to end of archive: ${RTO2}s"
echo "unshipped data window    : ${LOSS_S}s of writing after the last shipped WAL segment (archive_timeout bounds this; target ${RPO_TARGET_S}s)"
pass=1
[ "$A1" = 1000 ] && [ "$B1" = 0 ] || { echo "FAIL: point-in-time restore is wrong"; pass=0; }
[ "$A2" = 1000 ] && [ "$B2" = 1000 ] && [ "$C2" = 500 ] && [ "$D2" = 0 ] || { echo "FAIL: restore to the end of the archive is wrong"; pass=0; }
[ "${AFTER1}" = "${BEFORE}" ] || { echo "FAIL: tables differ from before the backup"; echo " before: $BEFORE"; echo " after : $AFTER1"; pass=0; }
[ "$RTO1" -le "$RTO_TARGET_S" ] && [ "$RTO2" -le "$RTO_TARGET_S" ] || { echo "FAIL: restore slower than the target"; pass=0; }
[ "$pass" = 1 ] && echo "PASS" || exit 1
