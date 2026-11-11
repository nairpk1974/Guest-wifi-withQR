#!/usr/bin/env bash
# Fill empty secret values in .env with strong random values. Never overwrites an existing value.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || cp .env.example .env
chmod 600 .env
rand() { openssl rand -hex "${1:-24}"; }
fernet() { python3 -c 'import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())'; }
setvar() {  # setvar NAME VALUE  (only if currently empty)
  local name="$1" value="$2"
  if grep -qE "^${name}=\s*(#.*)?$" .env; then
    sed -i -E "s|^${name}=\s*(#.*)?$|${name}=${value}|" .env
    echo "generated ${name}"
  fi
}
setvar POSTGRES_PASSWORD "$(rand 24)"
setvar DATA_ENCRYPTION_KEY "$(fernet)"
setvar RADIUS_API_KEY "$(rand 32)"
setvar RADIUS_SECRET_BLR "$(rand 16)"
setvar RADIUS_SECRET_HYD "$(rand 16)"
setvar RADIUS_SECRET_LOCAL "$(rand 16)"
# CoA secret defaults to the RADIUS secret of the same FortiGate
blr=$(grep -E '^RADIUS_SECRET_BLR=' .env | cut -d= -f2 | awk '{print $1}')
hyd=$(grep -E '^RADIUS_SECRET_HYD=' .env | cut -d= -f2 | awk '{print $1}')
setvar COA_SECRET_BLR "$blr"
setvar COA_SECRET_HYD "$hyd"
echo "Done. Store a copy of .env in the company password vault (DATA_ENCRYPTION_KEY is needed to restore backups)."
