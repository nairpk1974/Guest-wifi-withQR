#!/usr/bin/env bash
# Upgrade to a new release: backup -> rebuild -> migrate (automatic on backend start) -> verify.
set -euo pipefail
cd "$(dirname "$0")/.."
./scripts/backup.sh
git pull --ff-only 2>/dev/null || echo "(not a git checkout - copy the new release files in place before running)"
docker compose build --pull
docker compose up -d
sleep 10
docker compose ps
docker compose exec -T backend alembic current
echo "Upgrade complete. Rollback: restore the backup taken above and redeploy the previous release."
