# 9. Testing checklist

Run every test at **Bangalore first**, then repeat at **Hyderabad**. Record pass/fail, tester, date and evidence (screenshot, log line).

Automated lab coverage: `backend/tests/e2e_lab.py` (70 checks, application layer). The tests below cover the real network and firmware.

| # | Test | Steps | Expected | BLR | HYD |
|---|---|---|---|---|---|
| T1 | Successful QR authentication | Register → approve → join SSID with phone → scan access QR → accept → Connect | Internet works; dashboard shows active session; guest status page shows expiry | | |
| T2 | Code authentication (captive popup) | Join SSID, wait for the captive popup, enter the 8-character code | Internet works | | |
| T3 | Invalid QR | Open `/q/<random>` | "not valid" page; auth failure logged | | |
| T4 | Expired QR | Approve, wait past `QR_REDEEM_WINDOW_MINUTES` (or test with 5 min), scan | "QR code has expired" | | |
| T5 | Duplicate redemption | Redeem on phone A, then scan the same QR on phone B | B gets "already been used"; B has no internet | | |
| T6 | Credential replay on another device | Copy the FortiGate login POST from A and replay it from B | RADIUS reject `device_mismatch` (verify FortiGate sends Calling-Station-Id/Framed-IP; record which) | | |
| T7 | Duration enforcement | 1-hour pass; note login time | Internet stops ~60 min after first login (FortiGate `diagnose firewall auth list` shows timeout); guest status "expired" | | |
| T8 | Manual revocation | Revoke an active guest from the console | Disconnect ACK shown; internet stops within seconds; re-login rejected | | |
| T9 | Location binding | Use a BLR pass at HYD | Rejected ("valid at Head Office – Bangalore only") | | |
| T10 | Session-Timeout honoured | After T1, run `diagnose firewall auth list` on the FortiGate | Remaining time ≈ approved duration | | |
| T11 | Accounting / usage | Browse ~50 MB, wait 5 min | Session usage updates in console and reports | | |
| T12 | Reports & export | Export each report as CSV and Excel | Files open; filters respected; export audited | | |
| T13 | Internet-only access | From an authenticated guest: ping/curl corporate IPs, AD DCs, file servers, ERP, printers, CCTV NVR, FortiGate admin IP, Omada controller, AP and switch management, the server's other ports (22, 5432, 1812) | All blocked; FortiGate logs deny for `BGW-guest-deny-internal` | | |
| T14 | Pre-auth restriction | Before login: try any site and any internal IP | Only the portal host:443 works; everything else redirects/blocks | | |
| T15 | Guest-to-guest isolation | Two guests: ping, SMB, ARP scan between them | No reachability | | |
| T16 | Remote-site isolation | HYD guest → BLR corporate ranges via VPN | Blocked | | |
| T17 | Admin console exposure | From the guest SSID, open `https://<ADMIN_HOST>` | Refused (nginx 403 / no route) | | |
| T18 | RBAC | Reception HYD tries a BLR visitor; Auditor tries to register; Reception opens the audit log | 403 in all cases | | |
| T19 | MFA & lockout | Wrong TOTP; 5 wrong passwords | Rejected; account locked 15 min; audit entries | | |
| T20 | TLS | Test the guest host from iPhone and Android, plus an SSL test | Trusted certificate, TLS 1.2+, no warnings | | |
| T21 | Firewall connectivity failure | Block UDP 3799 from server, revoke a guest | Revocation queued and retried; dashboard flags it; guest rejected at next re-auth | | |
| T22 | Central server failure | `docker compose stop backend` | New logins fail gracefully; existing guests stay online until expiry; dashboard/alerts show outage; recovery after start | | |
| T23 | Database backup & restore | Run `backup.sh`; restore to a test VM | Data intact; app works with the same `.env` | | |
| T24 | Device compatibility | Android, iPhone, Windows, macOS laptop | Captive popup + QR flow work without installing an app | | |
| T25 | Corporate network regression | Corporate SSIDs, VLANs, VPN, printing | Unchanged | | |

## Lab test command

```bash
# on a lab copy of the stack (never production data)
python backend/tests/e2e_lab.py <superadmin> <temporary-password>
```
