#!/usr/bin/env bash
# Backs up the files that are not in the database: photos and data copies in the media folder (MEDIA_DIR). Run it daily, after backup.sh.
#
#   MEDIA_DIR=/srv/fleettms/media BACKUP_DIR=/srv/fleettms-backup ./scripts/dr/backup-files.sh
#
# Each run makes a dated snapshot folder under BACKUP_DIR/files/. Unchanged files are hard links to the previous snapshot, so a snapshot
# costs only what changed, yet each one is a complete copy that can be restored on its own. Keeps the newest BACKUP_KEEP (default 7).
# Photos are never edited, only added (and removed by the retention job), so this is cheap. If photos live in a bucket instead of a folder,
# turn on that bucket's versioning and cross-region copy and do not use this script.
set -euo pipefail
MEDIA_DIR=${MEDIA_DIR:?set MEDIA_DIR to the folder photos are stored in}
BACKUP_DIR=${BACKUP_DIR:?set BACKUP_DIR}
KEEP=${BACKUP_KEEP:-7}
stamp=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$BACKUP_DIR/files"
previous=$(ls -1d "$BACKUP_DIR"/files/*/ 2>/dev/null | sort | tail -n 1 || true)
link=()
[ -n "$previous" ] && link=(--link-dest="$previous")
rsync -a "${link[@]}" "$MEDIA_DIR"/ "$BACKUP_DIR/files/$stamp.partial/"
mv "$BACKUP_DIR/files/$stamp.partial" "$BACKUP_DIR/files/$stamp"
echo "files snapshot $stamp: $(find "$BACKUP_DIR/files/$stamp" -type f | wc -l) files, $(du -sh "$BACKUP_DIR/files/$stamp" | cut -f1) (shared files cost nothing)"
mapfile -t old < <(ls -1d "$BACKUP_DIR"/files/*/ | sort | head -n -"$KEEP" 2>/dev/null || true)
for d in "${old[@]:-}"; do [ -n "$d" ] && rm -rf "$d"; done
