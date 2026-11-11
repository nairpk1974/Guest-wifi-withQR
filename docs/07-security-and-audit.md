# 7. Security and audit

## 7.1 Control matrix (requirement §12)

| Requirement | Implementation |
|---|---|
| HTTPS throughout | nginx TLS 1.2/1.3, HSTS; HTTP → HTTPS redirect. Backend, DB and RADIUS-to-backend traffic stay on private Docker networks. |
| Secure password hashing | Argon2id (`argon2-cffi`). Policy: ≥12 characters and 3 character classes. Temporary passwords must be changed at first login. |
| MFA | TOTP (RFC 6238) for all administrators; enforced when `MFA_ENFORCED=true`. MFA secrets are encrypted at rest (Fernet). |
| RBAC | Super Administrator, Reception/Admin (pinned to one location), Security/Audit (read-only). Enforced server-side on every endpoint, including location scoping on lists, details, sessions and reports. |
| API authentication | Server-side sessions (random 256-bit token, stored as SHA-256), HttpOnly + Secure + SameSite=Strict cookie scoped to `/api`, 30-minute idle and 10-hour absolute timeout. Internal RADIUS API uses a shared key header and is not published by nginx. |
| Rate limiting | nginx `limit_req`: login/MFA 10/min per IP; guest pages 30/min; API 20 r/s. App-level: account lockout after 5 failures (15 min), max 5 TOTP attempts per login ticket, max 10 failed guest code/QR attempts per IP per 15 min. |
| CSRF | Per-session CSRF token required in the `X-CSRF-Token` header on every state-changing admin request. Guest forms use a double-submit token. SameSite cookies. |
| XSS | React escaping; Jinja2 autoescape; strict CSP (`script-src 'self'`, no inline scripts); `X-Content-Type-Options`, `X-Frame-Options: DENY`. |
| SQL injection | SQLAlchemy ORM / bound parameters only. Input validated with Pydantic. |
| Secure session management | Sessions revoked on password change, role change, disable, MFA reset. Logout deletes the server session. |
| QR token expiry | Redeem window (`QR_REDEEM_WINDOW_MINUTES`, bounded by the end of the visit day). Access clock starts at first FortiGate login. Expiry is enforced by RADIUS `Session-Timeout`, a worker Disconnect, and rejection at re-auth. |
| One-time redemption | GET never redeems (link previews are safe); POST claims the pass and binds it to one browser cookie and the first device MAC/IP. Replay from another device is rejected. Re-issue invalidates the old QR. |
| No reusable credentials | Open/OWE SSID. A per-guest random RADIUS password is created at redemption and never printed. The app holds no FortiGate admin credentials. |
| Unauthorised sharing | Device binding; location binding (BLR pass rejected at HYD); short redeem window; revocation. |
| Segmentation | Guest VLAN terminates on the FortiGate: explicit deny to corporate/management ranges, client isolation, only portal:443 reachable pre-auth. PostgreSQL is on an `internal: true` network with no host port. |
| Restricted management | Admin vhost only from `admin-allow.conf` subnets. Guest vhost serves only portal paths. FortiGate guest interface has no admin access. |
| Backups | `scripts/backup.sh` (pg_dump custom format, verified, optional GPG), retention `BACKUP_KEEP_DAYS`. |
| Audit logging | `audit_logs` table: every login/logout, lockout, MFA change, password change, user/location/settings change, registration, approval, rejection, revocation, re-issue, pass view/e-mail, session disconnect and report export, with user, IP, time and details. `auth_events` records every RADIUS and portal accept/reject. |

## 7.2 Privacy controls

- **Data minimisation.** Only the fields required by §4 are collected. E-mail is optional.
- **Notice and consent.** The guest must accept the terms and privacy notice before connecting. The acceptance time is stored (`guests.terms_accepted_at`).
- **Retention.** The worker anonymises guest PII (name, mobile, e-mail, purpose) after `GUEST_PII_RETENTION_DAYS` and deletes auth/audit/session logs after `LOG_RETENTION_DAYS`. Confirm both periods with legal (e.g. obligations under India's DPDP Act 2023 and any CERT-In log-retention directions that apply). This is not legal advice.
- **Access.** PII is visible only to authenticated staff, scoped by location. Exports are themselves audited.
- **CSV/Excel export** neutralises spreadsheet formula injection.

## 7.3 Secrets

All secrets live in `.env` (mode 600, excluded from source control):

- DB password;
- `DATA_ENCRYPTION_KEY`;
- `RADIUS_API_KEY`;
- RADIUS/CoA secrets per site.

Rotate the RADIUS secrets yearly or when staff change: update `.env` and the FortiGate together, then run `docker compose up -d`. If `DATA_ENCRYPTION_KEY` is rotated, existing passes and MFA enrolments can no longer be decrypted, so rotate it only with a planned MFA re-enrolment.

## 7.4 Audit review

Security/Audit staff should review weekly, under **Reports & audit**:

- *Security & authentication failures*: spikes in `bad_code`, `device_mismatch`, `wrong_location`, `unknown_nas`;
- *Administrative audit log*: user changes, exports, revocations;
- lockouts (`auth.locked`).
