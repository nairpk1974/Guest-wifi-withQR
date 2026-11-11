# 0. Phase 1 – Infrastructure discovery checklist

No production change is made until every item below is collected, reviewed and recorded in `02-network-vlan-design.md`. All commands are **read-only**.

Put the output in `C:\Guest wifi\discovery\` (or the project share). **Redact** passwords, pre-shared keys, RADIUS secrets and certificates before sharing.

## 0.1 FortiGate 60F (Bangalore) and FortiGate 30G (Hyderabad), one set per device

Back up the configuration first: **System → Configuration → Backup** (unencrypted copy for review with secrets redacted, plus an encrypted copy kept in the vault).

```
get system status
get system performance status
show system global
show system settings
show system interface
get system interface physical
show system switch-interface
show system virtual-switch          # 30G/60F hardware switch ports
show system dhcp server
show system dns
show system dns-server
show firewall address
show firewall addrgrp
show firewall policy
show firewall vip
show firewall shaper traffic-shaper
show firewall shaper per-ip-shaper
show firewall shaping-policy
show router static
show vpn ipsec phase1-interface     # redact psksecret
show vpn ipsec phase2-interface
show user radius                    # redact secret
show user group
show user setting
show user security-exempt-list
show system replacemsg-group
show system admin                   # redact; check trusted hosts
show log setting
show log syslogd setting
get system ha status
```

Answer these:

- [ ] Exact FortiOS version and build on each unit (60F and 30G may differ).
- [ ] Which physical or switch port faces the Omada APs or access switch, and whether it is in a hardware switch (`lan`, `internal`).
- [ ] Existing VLAN interfaces, IDs and subnets, so the new guest VLAN ID and subnet do not overlap.
- [ ] Existing DHCP scopes and DNS servers.
- [ ] Existing policy order: where the guest deny and allow policies must be inserted.
- [ ] VPN phase-2 selectors between HYD and BLR, and whether they can carry `HYD-guest-subnet ↔ APP_SERVER/32`.
- [ ] Which interface and IP each FortiGate will use to reach the app server (this becomes `FGT_*_RADIUS_SOURCE_IP`).
- [ ] Captive-portal ports (`show system global`: `auth-http-port`, `auth-https-port`) and whether `auth-secure-http` is used.
- [ ] Existing RADIUS servers and user groups, to avoid name clashes.
- [ ] Licensing and feature availability on the 30G (traffic shaping, captive portal on VLAN interfaces, RADIUS CoA).

## 0.2 TP-Link Omada

- [ ] Controller type: software (version), OC200, OC300 or Omada Cloud. **Settings → Controller / About**.
- [ ] Sites: one site per office, or one site for both?
- [ ] AP models, hardware versions and firmware (Devices list export).
- [ ] Current SSIDs: security, VLAN, rate limits, band steering, captive/portal settings. Screenshot **Settings → Wireless Networks**.
- [ ] Current LAN networks and VLANs. Screenshot **Settings → Wired Networks → LAN**.
- [ ] Switches between APs and FortiGate: model, managed by Omada or not, port profiles. Must trunk the new guest VLAN to every AP port and to the FortiGate uplink.
- [ ] AP management VLAN (must stay unreachable from guests).
- [ ] Whether the SSID "Guest Network" option, SSID-level client isolation, OWE (Enhanced Open) or WPA3 are offered for these AP models.

## 0.3 Ubuntu Docker server

Run `scripts/discover-server.sh <fgt-blr-ip> <fgt-hyd-ip>` on the server and share the output file. It records:

- [ ] Ubuntu version, CPU/RAM/disk, Docker Engine and Compose versions.
- [ ] IP addresses, routes and DNS. Which VLAN/subnet the server is on.
- [ ] Ports already in use (80/443/1812/1813 must be free or remapped).
- [ ] Existing containers and Docker networks (avoid subnet overlaps).
- [ ] Host firewall (ufw/iptables) and time sync (needed for TOTP and logs).
- [ ] Reachability to both FortiGates (and HYD over the VPN).

## 0.4 Decisions needed from Bessel Systems

| # | Decision | Default proposed |
|---|---|---|
| D1 | Guest portal hostname and public domain for a trusted TLS certificate | `guest.<company-domain>` with a Let's Encrypt DNS-01 or commercial certificate |
| D2 | Admin console hostname | `wifi-admin.<company-domain>` (internal DNS) |
| D3 | Guest VLAN IDs and subnets per site | proposed after discovery, must not overlap |
| D4 | Guest bandwidth: per-device limit and total guest cap per site | e.g. per-device 10/5 Mbps, total ≤ 30 % of WAN (to confirm) |
| D5 | Guest DNS: FortiGate DNS (with split entry for portal host) or public resolvers | FortiGate DNS with local entry |
| D6 | Open SSID vs OWE (if APs support it) | OWE transition mode if supported, else open + captive portal |
| D7 | Data retention for guest PII and logs | 180 days PII / 365 days logs (legal to confirm) |
| D8 | Must approval be done by a different person than the registrar? | No (configurable) |
| D9 | Content filtering (FortiGuard web filter) on guest policy | Optional, depends on licences |
