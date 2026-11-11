#!/usr/bin/env bash
# First-time installation on the existing Ubuntu Docker server.
set -euo pipefail
cd "$(dirname "$0")/.."
command -v docker >/dev/null || { echo "Docker is not installed"; exit 1; }
docker compose version >/dev/null || { echo "Docker Compose v2 plugin is required"; exit 1; }

[ -f .env ] || { cp .env.example .env; echo "Created .env from template - edit hostnames and discovery values, then re-run."; }
./scripts/gen-secrets.sh
set -a; . ./.env; set +a

[ -f deploy/nginx/admin-allow.conf ] || { cp deploy/nginx/admin-allow.conf.example deploy/nginx/admin-allow.conf;
  echo "!! Edit deploy/nginx/admin-allow.conf with the corporate subnets (currently deny all)"; }
if [ ! -f deploy/certs/fullchain.pem ] || [ ! -f deploy/certs/privkey.pem ]; then
  echo "!! TLS certificate missing: place fullchain.pem and privkey.pem in deploy/certs/"
  echo "   (lab only: ./scripts/selfsigned-cert.sh)"; exit 1
fi
case "$FGT_BLR_RADIUS_SOURCE_IP$FGT_HYD_RADIUS_SOURCE_IP" in
  *192.0.2.*) echo "!! WARNING: FortiGate RADIUS source IPs are still TEST-NET placeholders - RADIUS will reject them." ;;
esac

docker compose build
docker compose up -d
echo "Waiting for services to become healthy..."
for i in $(seq 1 60); do
  if docker compose ps --format json | grep -q '"Health":"healthy"' && \
     [ "$(docker compose ps backend --format '{{.Health}}')" = "healthy" ]; then break; fi
  sleep 5
done
docker compose ps
echo
echo "Next: create the first Super Administrator:"
echo "  docker compose exec backend python -m app.cli create-superadmin <username> \"<Full Name>\""
