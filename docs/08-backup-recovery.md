# 8. Backup and recovery

## 8.1 What is backed up

| Item | How | Frequency |
|---|---|---|
| PostgreSQL database (all guests, sessions, audit) | `scripts/backup.sh` → `pg_dump -Fc`, verified with `pg_restore -l` | Daily (cron) + before every upgrade |
| `.env`, nginx allow-list, TLS certificates | Same script → `guestwifi-config-*.tgz` | Daily |
| FortiGate configurations | FortiGate GUI/CLI backup, or FortiManager if present | Before every change + monthly |
| Omada controller | Controller backup | Before every change + monthly |
| Application source | Git repository / release archive | Each release |

**`DATA_ENCRYPTION_KEY` is mandatory for restore.** Without it, stored QR tokens and MFA secrets cannot be decrypted. Keep `.env` in the company password vault.

Set `BACKUP_GPG_RECIPIENT` in `.env` to encrypt backup files. Copy `BACKUP_DIR` off the server, e.g. with an rsync job to the backup NAS.

## 8.2 Schedule

```
# crontab -e (root or deploy user)
15 1 * * * /opt/bessel-guestwifi/scripts/backup.sh >> /var/log/guestwifi-backup.log 2>&1
```

## 8.3 Restore the database

```bash
cd /opt/bessel-guestwifi
./scripts/restore.sh /srv/backups/guestwifi/guestwifi-db-YYYYmmdd-HHMMSS.dump
docker compose ps
```

After a restore:

- Passes approved after the dump time no longer exist, so re-register those visitors.
- Active guests keep their FortiGate sessions until `Session-Timeout`.

## 8.4 Full server loss (rebuild)

1. Install Docker on a new Ubuntu host with the same IP. If the IP changes, update the FortiGate `config user radius` server and both DNS records.
2. Restore the application files and the config tarball (`.env`, certs, allow-list).
3. `./scripts/install.sh`, then `./scripts/restore.sh <latest dump>`.
4. Test one guest at each site.

**Target:** service restored within 2 hours of hardware being available. Worst-case data loss is 24 hours (the daily backup interval).

## 8.5 Behaviour during an outage

| Failure | Effect | Mitigation |
|---|---|---|
| App server down | New guests cannot sign in. Already-authenticated guests stay online until their `Session-Timeout` (enforced by FortiGate). | Restore service; optional emergency local guest group on FortiGate (disabled by default). |
| Database down | Same as above. The dashboard shows "database down". | `docker compose restart db`; restore from backup if corrupted. |
| VPN BLR–HYD down | HYD guests cannot reach the portal or RADIUS. Existing HYD sessions continue. | Restore the VPN; the HYD emergency option above. |
| FortiGate unreachable from server | Revocations queue and are retried for ~10 minutes. The dashboard shows ping/RADIUS status. | Fix connectivity; revoked guests are also rejected at any re-auth. |

## 8.6 Restore test (quarterly)

1. Restore the latest dump into a scratch stack on a test VM.
2. Sign in, open five random visitors, run the *Visitor registration history* report.
3. Record the result in the change log.
