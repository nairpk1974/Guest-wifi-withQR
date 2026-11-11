# 6. Production deployment manual (Ubuntu Docker server)

## 6.1 Prerequisites

- The existing Ubuntu server with Docker Engine 24+ and the Docker Compose v2 plugin. Check with `docker compose version`.
- Ports free on the host: TCP 80, 443 and UDP 1812, 1813. Remap them in `docker-compose.yml` if they are taken.
- Reachability:
  - both FortiGates → server UDP 1812/1813;
  - server → both FortiGates UDP 3799;
  - guest VLANs → server TCP 443 only;
  - corporate admin subnets → server TCP 443.
- Image sources: the build pulls `postgres`, `python`, `node`, `nginx`, `nginxinc/nginx-unprivileged` and `freeradius/freeradius-server` from Docker Hub, and Python/npm packages from PyPI and npm. If the server has no Internet access, build on another machine and `docker save` / `docker load`.
- DNS: the admin host (internal) and guest host point to the server IP. See §6.3 for the certificate.

## 6.2 Install

```bash
sudo mkdir -p /opt/bessel-guestwifi && sudo chown $USER /opt/bessel-guestwifi
# copy the project here (git clone or unzip), then:
cd /opt/bessel-guestwifi
cp .env.example .env && nano .env          # hostnames, FortiGate source IPs (from discovery), policy values
./scripts/gen-secrets.sh                   # fills all secrets; store .env in the password vault
cp deploy/nginx/admin-allow.conf.example deploy/nginx/admin-allow.conf && nano deploy/nginx/admin-allow.conf
# place TLS files: deploy/certs/fullchain.pem and deploy/certs/privkey.pem (§6.3)
./scripts/install.sh
docker compose exec backend python -m app.cli create-superadmin <username> "<Full Name>"
```

Then open `https://<ADMIN_HOST>` from a corporate PC and sign in with the temporary password. You will be asked to change the password and enrol MFA.

## 6.3 TLS certificates

- **Guest host:** guest phones only trust **publicly trusted** certificates, so the guest host needs a certificate from a public CA for a domain Bessel Systems owns, e.g. `guest.besselsystems.com`.
  - The public DNS record may point at the private server IP. Alternatively, use FortiGate split DNS (`03` §3.2).
  - Use the Let's Encrypt **DNS-01** challenge (no inbound Internet needed) or a commercial certificate.
  - Put both hostnames in one SAN certificate, or concatenate certificates. nginx uses `fullchain.pem` + `privkey.pem`.
- **Admin host:** may use the same certificate or the internal CA.
- **Renewal:** renew before expiry, copy the files into `deploy/certs/`, then run `docker compose exec nginx nginx -s reload`.
- **Lab only:** `./scripts/selfsigned-cert.sh`.

## 6.4 Configure the application (Super Administrator)

1. **Administrators.** Create the Reception/Admin accounts for BLR and HYD, and the Security/Audit accounts. Hand over each temporary password through a secure channel.
2. **Locations & firewalls**, for each site, using the values verified in discovery:
   - Captive-portal post hosts: the FortiGate guest gateway `IP:port`, e.g. `<GUEST_GW_BLR>:1000`. Until this is set, the portal refuses to send credentials anywhere.
   - CoA/Disconnect host: the FortiGate address that receives UDP 3799.
   - Monitor host: the FortiGate IP to ping for the dashboard.
3. **Portal terms & privacy.** Paste the wording approved by legal/compliance.
4. **FortiGate secrets.** On each FortiGate, enter `RADIUS_SECRET_BLR` / `RADIUS_SECRET_HYD` from `.env` in `config user radius`.

## 6.5 Operations

| Task | Command |
|---|---|
| Status / health | `docker compose ps` |
| Logs (follow) | `docker compose logs -f backend worker radius nginx` |
| RADIUS debug (temporary) | `docker compose stop radius && docker compose run --rm --service-ports radius -X` |
| Restart a component | `docker compose restart <service>` |
| Backup now | `./scripts/backup.sh` |
| Restore | `./scripts/restore.sh <dump>` (see `08`) |
| Upgrade | `./scripts/upgrade.sh` |
| Reset an admin's MFA (locked out) | `docker compose exec backend python -m app.cli reset-mfa <username>` |
| Database shell (read-only use) | `docker compose exec db psql -U guestwifi guestwifi` |

**Logging:** containers log to Docker's json-file driver (20 MB × 10 per container). Forward the logs to the company SIEM/syslog if one exists, for example with a Docker logging driver or a log shipper.

## 6.6 Upgrade procedure

1. Read the release notes.
2. Run `./scripts/upgrade.sh`. It backs up first, rebuilds, then restarts. Database migrations run automatically when the backend starts (`alembic upgrade head`).
3. Check `docker compose ps`, then sign in, open the dashboard, and run one test pass at BLR.
4. To roll back: redeploy the previous release files, then `./scripts/restore.sh <pre-upgrade dump>`.

## 6.7 Server hardening checklist

- [ ] Host firewall (ufw or upstream FortiGate): allow 443 from corporate and guest subnets; 1812/1813 UDP only from the two FortiGate source IPs; SSH only from the IT management subnet.
- [ ] `.env` is `chmod 600` and owned by root or the deploy user. It is never committed (see `.gitignore`).
- [ ] Unattended security updates enabled. Rebuild images monthly (`docker compose build --pull`).
- [ ] NTP synchronised (TOTP and log timestamps depend on it).
- [ ] Backups scheduled (cron) and a restore test done quarterly.
