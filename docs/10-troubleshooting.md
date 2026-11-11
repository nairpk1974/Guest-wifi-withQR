# 10. Troubleshooting guide

## 10.1 Quick triage

1. **Dashboard → Application server and Firewall connectivity** tiles.
2. `docker compose ps`: all services up and healthy?
3. `docker compose logs --tail 200 backend radius worker`.
4. **Reports → Security & authentication failures**: the `reason` column usually tells you the cause.

## 10.2 Guest problems

| Symptom | Likely cause | Check / fix |
|---|---|---|
| No captive popup / no redirect | FortiGate interface not in captive-portal mode, or the device already uses cellular data | `show system interface BGW-GUEST`; ask the guest to turn off mobile data; open `http://neverssl.com` |
| Portal page doesn't load before login | Exempt list or portal policy missing; DNS for guest host wrong; Omada "Guest Network" blocking RFC1918 | `diagnose sniffer packet any 'host <APP_SERVER_IP> and port 443'`; `nslookup <GUEST_HOST>` from guest; see `04` §4.3 |
| Certificate warning on phone | Guest host certificate is not publicly trusted or has expired | Install a public CA certificate (`06` §6.3) |
| "This sign-in page was not opened from the Bessel Systems guest network" | `post` host not in the location's *Captive-portal post hosts* | Add the exact `IP:port` seen in the redirect URL (browser address bar) under Locations |
| "already been used on another device" | QR scanned on another phone or browser first; or the iOS captive mini-browser and Safari have separate cookies | Use the same browser that scanned, or re-issue (approved status) / revoke and re-register |
| Stuck on "Connecting…" | Trigger URL not intercepted (already online or HTTPS-only) | Set `CAPTIVE_TRIGGER_URL` to any plain-HTTP site the FortiGate intercepts; guest can tap Continue |
| Login posts but FortiGate says auth failed | RADIUS reject | Auth failures report: `unknown_nas` (client IP/shortname mismatch, see 10.3), `wrong_location`, `device_mismatch`, `expired`, `revoked` |
| Access ends earlier or later than expected | FortiGate not honouring Session-Timeout, or group `authtimeout` / `auth-timeout-type` differs | `diagnose firewall auth list`; check `03` §3.2 settings on that build; the worker's Disconnect at expiry is the backstop |

## 10.3 RADIUS

| Symptom | Check |
|---|---|
| No packets arrive | `sudo tcpdump -ni any udp port 1812` on the server; FortiGate `diagnose sniffer packet any 'udp port 1812' 4`; firewall/VPN selectors |
| FreeRADIUS logs "unknown client" | The FortiGate's source IP ≠ `FGT_*_RADIUS_SOURCE_IP`. Docker preserves the source IP for published UDP ports (iptables DNAT). If a host proxy/NAT rewrites it, run radius with `network_mode: host`. |
| Shared secret mismatch ("Message-Authenticator invalid") | Same secret in `.env` and FortiGate `config user radius`; restart radius after an `.env` change |
| Everything rejected with reason `unknown_nas` | `nas_shortname` in Locations must be `fgt-blr` / `fgt-hyd` (matches `clients.conf`) |
| Backend unreachable from RADIUS | `docker compose logs radius` shows rlm_rest connect errors → `docker compose ps backend`. Check that `RADIUS_API_KEY` is identical for both containers (same `.env`). |
| Verbose debug | `docker compose stop radius && docker compose run --rm --service-ports radius -X`, reproduce, Ctrl-C, `docker compose up -d radius` |

## 10.4 Revocation / CoA

- The revoke result in the console shows `ack`, `timeout` or `nak`:
  - `timeout`: UDP 3799 is not reaching the FortiGate (policy, VPN, wrong CoA host) or `radius-coa` is disabled.
  - `nak`: the FortiGate did not match the session. Verify which attributes your build requires (User-Name / Framed-IP-Address / Acct-Session-Id) with `diagnose debug application fnbamd -1`.
- Queued disconnects are retried by the worker every 30 s (up to 20 attempts). Even if the Disconnect fails, the guest is rejected at the next authentication and is cut off by `Session-Timeout`.
- **Fallback if this firmware lacks CoA for firewall auth:** set the guest user group `authtimeout` to a short re-authentication interval (e.g. 15 min). FortiGate then re-authenticates via RADIUS and revoked guests are rejected within that interval. Record this decision.

## 10.5 Admin console

| Symptom | Fix |
|---|---|
| 403 at the admin host | Your subnet is not in `deploy/nginx/admin-allow.conf`; edit, then `docker compose restart nginx` |
| Locked out (password) | Another Super Admin: Administrators → Unlock / Reset password |
| Lost authenticator | `docker compose exec backend python -m app.cli reset-mfa <user>` (audited) |
| "Session expired" frequently | Increase `SESSION_IDLE_MINUTES` (default 30) |
| Worker shows not running | `docker compose logs worker`; `docker compose restart worker` |

## 10.6 Database & disk

- **Disk full:**
  - `df -h`;
  - `docker system df`;
  - prune old images with `docker image prune`;
  - check `BACKUP_DIR` retention.
- **Slow reports over long ranges:** narrow the date range. Exports are capped at 100,000 rows.
- **Migration failed on upgrade:**
  1. `docker compose logs backend` shows the alembic error;
  2. restore the pre-upgrade dump and redeploy the previous release;
  3. report the error.
