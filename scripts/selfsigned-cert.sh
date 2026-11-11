#!/usr/bin/env bash
# LAB ONLY: create a self-signed certificate for ADMIN_HOST and GUEST_HOST.
# Production must use a publicly trusted certificate for GUEST_HOST (guest phones will not trust a
# private CA) - see docs/06-deployment-manual.md section "TLS certificates".
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
mkdir -p deploy/certs
openssl req -x509 -newkey rsa:2048 -nodes -days 90 -subj "/CN=${GUEST_HOST}" \
  -addext "subjectAltName=DNS:${GUEST_HOST},DNS:${ADMIN_HOST}" \
  -keyout deploy/certs/privkey.pem -out deploy/certs/fullchain.pem
chmod 600 deploy/certs/privkey.pem
echo "Self-signed certificate written to deploy/certs/ (lab use only)."
