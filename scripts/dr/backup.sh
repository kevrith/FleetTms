#!/usr/bin/env bash
# Takes a base backup of the running database and stores it beside the WAL archive. Run it every day (cron or a systemd timer).
#
#   DB_CONTAINER=fleettms-db-1 BACKUP_DIR=/srv/fleettms-backup ./scripts/dr/backup.sh
#
# BACKUP_DIR holds base/ (one .tar.gz per backup, with a sha256 file) and wal/ (what archive_command writes; see deploy/postgres/dr.conf).
# The database container must see the same BACKUP_DIR as /backup. Nothing here contains a password: the container trusts local sockets.
set -euo pipefail
CONTAINER=${DB_CONTAINER:-fleettms-db-1}
BACKUP_DIR=${BACKUP_DIR:?set BACKUP_DIR to the folder that holds base/ and wal/}
DB_USER=${POSTGRES_USER:-fleettms}
KEEP=${BACKUP_KEEP:-7}
stamp=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$BACKUP_DIR/base"
started=$(date +%s)
docker exec "$CONTAINER" pg_basebackup -U "$DB_USER" -D - -Ft -X fetch -z -c fast -l "fleettms-$stamp" > "$BACKUP_DIR/base/$stamp.tar.gz.partial"
tar tzf "$BACKUP_DIR/base/$stamp.tar.gz.partial" backup_label PG_VERSION >/dev/null  # a backup that cannot be listed is not a backup
mv "$BACKUP_DIR/base/$stamp.tar.gz.partial" "$BACKUP_DIR/base/$stamp.tar.gz"
(cd "$BACKUP_DIR/base" && sha256sum "$stamp.tar.gz" > "$stamp.sha256")
echo "backup $stamp: $(du -h "$BACKUP_DIR/base/$stamp.tar.gz" | cut -f1) in $(( $(date +%s) - started )) s"

# Keep the newest $KEEP base backups, and only the WAL the oldest kept one needs.
mapfile -t old < <(ls -1 "$BACKUP_DIR"/base/*.tar.gz | sort | head -n -"$KEEP" 2>/dev/null || true)
for f in "${old[@]:-}"; do [ -n "$f" ] && rm -f "$f" "${f%.tar.gz}.sha256"; done
oldest=$(ls -1 "$BACKUP_DIR"/base/*.tar.gz | sort | head -n 1)
first_wal=$(tar xzf "$oldest" -O backup_label | sed -n 's/^START WAL LOCATION: .*(file \(.*\))$/\1/p')
[ -n "$first_wal" ] && docker exec "$CONTAINER" pg_archivecleanup /backup/wal "$first_wal" || true
