#!/usr/bin/env bash
# Daily backup: PostgreSQL dump (custom format) + config. Schedule with cron, e.g.
#   15 1 * * * /opt/bessel-guestwifi/scripts/backup.sh >> /var/log/guestwifi-backup.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
DIR="${BACKUP_DIR:-/srv/backups/guestwifi}"
KEEP="${BACKUP_KEEP_DAYS:-30}"
STAMP=$(date +%Y%m%d-%H%M%S)
mkdir -p "$DIR"; chmod 700 "$DIR"
docker compose exec -T db pg_dump -U guestwifi -d guestwifi -Fc > "$DIR/guestwifi-db-$STAMP.dump"
# config (contains secrets) - encrypt at rest if BACKUP_GPG_RECIPIENT is set
tar -czf "$DIR/guestwifi-config-$STAMP.tgz" .env deploy/nginx/admin-allow.conf deploy/certs 2>/dev/null || true
if [ -n "${BACKUP_GPG_RECIPIENT:-}" ]; then
  for f in "$DIR"/guestwifi-*-"$STAMP".*; do gpg --batch --yes -e -r "$BACKUP_GPG_RECIPIENT" "$f" && rm -f "$f"; done
fi
chmod 600 "$DIR"/guestwifi-*-"$STAMP"* 
# verify the dump is readable
LATEST=$(ls -1t "$DIR"/guestwifi-db-"$STAMP".dump* | head -1)
case "$LATEST" in *.gpg) echo "encrypted dump: $LATEST";; *) docker compose exec -T db pg_restore -l < "$LATEST" >/dev/null && echo "dump verified: $LATEST";; esac
find "$DIR" -name 'guestwifi-*' -mtime +"$KEEP" -delete
echo "backup complete $STAMP"
