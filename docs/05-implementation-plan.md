# 5. Implementation plan

| Phase | Work | Output / exit criteria | Production impact |
|---|---|---|---|
| 1 Discovery | Collect everything in `00-discovery-checklist.md`; config backups of both FortiGates and the Omada controller | Completed worksheet (`02` §2.4); decisions D1–D9 signed off | None (read-only) |
| 2 Network & VLAN design | Choose VLAN IDs and subnets, deny groups, VPN selector changes, shaping values | Approved design; change request raised | None |
| 3 FortiGate 60F | Apply `03` §3.2 with verified values in a change window | Guest VLAN up, DHCP works, policies in place, RADIUS test OK (`diagnose test authserver`) | Low: new objects only |
| 4 FortiGate 30G | Apply `03` §3.3 after BLR passes its tests | Same as phase 3, plus VPN path to portal and RADIUS verified | Low; VPN selector change needs a window |
| 5 Omada SSIDs | `04`: guest LAN/VLAN, SSID, isolation, per site | SSID visible at the right site only; isolation tested | Low: new SSID only |
| 6 Docker deployment | `06-deployment-manual.md`: install, certificates, `.env`, first Super Admin, users, locations | All containers healthy; admin console reachable from corporate LAN only | None to network |
| 7 QR & approval workflow | Configure portal texts and durations; train reception | Reception can register, approve, print and revoke | None |
| 8 Firewall authentication integration | Enter post hosts, CoA host and monitor host per location; end-to-end tests at BLR, then HYD | `09` tests T1–T12 pass at BLR, then HYD | Guest SSID only |
| 9 Security testing | `09` T13–T25: isolation, RBAC, replay, rate limits, TLS, backups | Signed test report | None |
| 10 Production rollout & docs | Go-live per site, hand-over, backup schedule, monitoring | Hand-over sign-off; runbooks in place | Guest SSID live |

## Order and safety

- **One site at a time.** Bangalore first, with 2–3 days of pilot use, then Hyderabad.
- Every network change is **additive**: new VLAN, new SSID, new policies and objects prefixed `BGW-`. The rollback for each phase is in `03` §3.5 and `04`.
- Make no change to corporate SSIDs, VLANs, DHCP scopes or existing policy order beyond inserting the new `BGW-` policies at the agreed position.

## Lab verification already done (application layer)

The application stack has been verified end-to-end in a lab with real FreeRADIUS 3.2 (rlm_rest), PostgreSQL 16, nginx and two simulated FortiGate RADIUS clients plus a simulated CoA listener: `backend/tests/e2e_lab.py`, 70 automated checks covering QR redemption, replay, location binding, Session-Timeout, device binding, accounting, revoke and expiry Disconnect, RBAC, reports and lockout.

Behaviour that depends on **real FortiGate firmware** is verified in Phases 3/4/8 using `09-testing-checklist.md`:

- the external-portal redirect parameters;
- honouring of `Session-Timeout`;
- Disconnect-Request handling;
- the attributes FortiGate sends (Calling-Station-Id, Framed-IP).
