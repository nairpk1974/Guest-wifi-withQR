# 11. Discovery findings: FortiGate 60F and 30G

Source: configuration backups taken 2026-11-05 at 16:11 and 16:12 (FortiOS **7.4.12 build 2902** on both units, no VDOMs). Analysis was read-only. No secrets are reproduced here.

## 11.1 Verified facts

| Item | Bangalore – FortiGate 60F | Hyderabad – FortiGate 30G |
|---|---|---|
| Firmware | 7.4.12 build 2902 | 7.4.12 build 2902 |
| WAN | `wan1` static (ACT), `wan2` DHCP (unused) | `wan` PPPoE |
| Corporate LAN interface | `internal`: hard-switch of `internal1`–`internal5`, **192.168.0.1/24** | `lan`: hard-switch of `lan1`, **192.168.2.1/24** |
| Other LAN-side interfaces | `dmz` 10.10.10.1/24; `fortilink` (a+b) 10.255.1.1/24 (no managed FortiSwitch configured) | `dmz` (port `lan2`) 192.168.3.1/24 with a `dmz → wan` policy; `fortilink` (a) 10.255.1.1/24 |
| VLAN interfaces today | **none** | **none** |
| VLAN on hard-switch allowed | `virtual-switch-vlan enable` ✔ | **not enabled** (needs a global setting, see 11.3) |
| Corporate DHCP | 192.168.0.51–200, DNS 192.168.0.2 (AD), 8.8.8.8 | 192.168.2.50–200, DNS 192.168.2.2, 8.8.8.8 |
| FortiGate DNS | DoT to FortiGuard (96.45.45.45/46.46) | same |
| Site-to-site VPN | `Blr-to-Hyd` (wan1 ↔ 49.206.192.47), phase-2: 192.168.0.0/24 ↔ 192.168.2.0/24, plus GRE and 10.100.0.0/24 overlay | `Hyd-to-Blr` (mirror) |
| Route to WireGuard 10.100.0.0/24 | via 192.168.0.10 (Docker-vm) | via VPN |
| Existing RADIUS servers | none | none |
| Existing captive portal | none on interfaces; internet policies use group "Internet User Group" (member: local user `guest`) | **on the corporate `lan` interface**, group "Guest-group" (local users `guest`, `nair`), exempt list by MAC |
| Global firewall auth timeout | `auth-timeout 1` (1 minute) | default |
| Syslog | 192.168.0.10 (Docker-vm) | 192.168.0.10 |
| Name clashes with planned `BGW-*` objects | none | none |

Both units run the same firmware, so the external captive portal (`security-external-web`), RADIUS accounting and `radius-coa` can be validated once and reused. They will still be tested on each unit.

## 11.2 Proposed values (please confirm)

| Parameter | Bangalore | Hyderabad | Why |
|---|---|---|---|
| Guest VLAN ID | **50** | **50** | No VLANs exist on either FortiGate. Confirm 50 is unused on Omada and the switches |
| Guest VLAN interface | `BGW-GUEST` on parent `internal` | `BGW-GUEST` on parent `lan` *(or on `dmz`/lan2, see 11.3)* | APs are presumed to hang off the corporate LAN ports. Confirm in the Omada/switch step |
| Guest subnet / gateway | **10.50.10.0/24**, 10.50.10.1 | **10.50.20.0/24**, 10.50.20.1 | Avoids 192.168.0–3.x, 192.168.5.x, 10.10.10.0/24, 10.100.0.0/24, 10.255.x, 10.212.134.x, and 172.16.0.0/12 (Docker bridges) |
| Guest DHCP | .20–.250, lease 8 h, DNS = 10.50.x.1 | same | FortiGate DNS with a split entry for the portal host |
| Portal / RADIUS server | 192.168.0.10, TCP 8444, UDP 1812/1813 | same, over the VPN | Docker-vm |
| RADIUS source IP | 192.168.0.1 (`internal`) | **192.168.2.1** (`lan`), so the traffic matches the existing VPN selectors | No VPN change needed for RADIUS/CoA |
| HYD guest → portal path | n/a | **new phase-2 pair** `10.50.20.0/24 ↔ 192.168.0.10/32` on both units (additive) | Keeps the existing selectors untouched |
| `FGT_BLR_RADIUS_SOURCE_IP` / `FGT_HYD_RADIUS_SOURCE_IP` in `.env` | 192.168.0.1 | 192.168.2.1 | |
| Portal post host | 10.50.10.1:1000 | 10.50.20.1:1000 | FortiGate default auth port (`auth-http-port` not changed) |
| CoA host | 192.168.0.1 | 192.168.2.1 | |

## 11.3 Points needing a decision

1. **Hyderabad VLAN on the `lan` hard-switch.** The 30G lacks `virtual-switch-vlan enable`. Two options:
   - **(a)** Enable it (`config system global` → `set virtual-switch-vlan enable`). This is a global setting: schedule it in a change window and confirm the 30G accepts it on 7.4.12.
   - **(b)** Use the spare `dmz` port (`lan2`, 192.168.3.0/24) for guest traffic. Connect it to the switch/AP uplink carrying the guest VLAN, or make it the guest VLAN parent. First confirm nothing uses 192.168.3.0/24 today.
2. **Which LAN port and switch carry the APs at each site.** Needed to tag VLAN 50 end to end (Omada step).
3. **Existing shared `guest` account.** Today visitors share the local user `guest`: on the corporate LAN in HYD, and via "Internet User Group" in BLR. After go-live, plan to disable that account so visitors stop landing on the corporate LAN. This is a separate, later change, coordinated with staff who might use it.

## 11.4 Security observations (outside this project's scope, recommended)

| # | Observation | Recommendation |
|---|---|---|
| S1 | Admin GUI (HTTP+HTTPS) is enabled on the Internet-facing interfaces: 60F `wan1` (ports 8080/4434) and 30G `wan` | Remove `http`/`https` from WAN `allowaccess`, or restrict administrators with trusted hosts. Manage via LAN/VPN only |
| S2 | The configuration backups contain encrypted secrets (`ENC …`) | Keep the backup files only in a restricted location. Don't email them |
| S3 | Visitors currently share one local account on the corporate LAN | Resolved by this project; disable afterwards (11.3 point 3) |
