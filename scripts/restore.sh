#!/usr/bin/env bash
# Restore a database dump made by backup.sh.  Usage: scripts/restore.sh /path/guestwifi-db-YYYYmmdd-HHMMSS.dump
# The .env DATA_ENCRYPTION_KEY must be the one in use when the dump was taken (restore config tarball first).
set -euo pipefail
cd "$(dirname "$0")/.."
DUMP="${1:?usage: restore.sh <dump file>}"
[ -f "$DUMP" ] || { echo "not found: $DUMP"; exit 1; }
read -r -p "This REPLACES the current guest Wi-Fi database. Type RESTORE to continue: " ok
[ "$ok" = "RESTORE" ] || exit 1
docker compose stop backend worker radius nginx
docker compose up -d db
sleep 5
docker compose exec -T db psql -U guestwifi -d postgres -c "DROP DATABASE IF EXISTS guestwifi WITH (FORCE);"
docker compose exec -T db psql -U guestwifi -d postgres -c "CREATE DATABASE guestwifi OWNER guestwifi;"
docker compose exec -T db pg_restore -U guestwifi -d guestwifi --no-owner < "$DUMP"
docker compose up -d
echo "Restore complete. Check: docker compose ps ; then sign in and review the dashboard."
