# 2. Network and VLAN design

> All addresses, IDs and interface names below are **placeholders** until discovery is reviewed. Fill in the worksheet in §2.4 and get it approved before Phase 3.

## 2.0 Verified facts (discovery, 2026-11-05)

| Item | Value | Source |
|---|---|---|
| Proxmox host | `192.168.0.3` (pve), 62 GiB RAM, heavily overcommitted (host swap ~99 % used) | `free -h`, `qm list` on pve |
| Application server | **Docker-vm (VMID 104)**, `docker-irfmw`, **`192.168.0.10/24`** on `ens18`; ~7.7 GiB RAM available, so no RAM change is needed | `ip -br addr`, `free -h` |
| Ports already in use on Docker-vm | TCP 80/443 (`docker-nginx-1`), 514, 8001, 8081, 8085, 8443, 8445, 9443; localhost 5173/8000/5432/6379 | `docker ps`, `ss -tulpn` |
| Free for this project | TCP **8444** (HTTPS: guest portal + admin), TCP **8088** (HTTP redirect), UDP **1812/1813** (RADIUS) | `ss -tulpn` |
| Docker bridge subnets in use | 172.17–172.23.0.0/16. Guest VLAN subnets **must not** use 172.16.0.0/12 (replies would be routed into a Docker bridge) | `ip -br addr` |
| Other interfaces | `wg0` 10.100.0.1/24 (WireGuard). Avoid 10.100.0.0/24 for guest VLANs | `ip -br addr` |

Resulting values: `APP_SERVER_IP = 192.168.0.10`, `<PORTAL_PORT> = 8444`. Guest URLs look like `https://<GUEST_HOST>:8444/…`.

## 2.1 Design rules

1. One dedicated guest VLAN per office. It is trunked from the FortiGate to the Omada APs and terminates **only** on the FortiGate (no SVI on any switch).
2. The FortiGate is the guest default gateway, DHCP server and DNS forwarder. No other device routes the guest subnet.
3. Guest traffic may reach only:
   - the Internet (NAT on the WAN interface) after captive-portal authentication;
   - the guest portal `APP_SERVER_IP:<PORTAL_PORT>` (pre-authentication exempt). Nothing else on the server is reachable from guests;
   - FortiGate DHCP, DNS and captive-portal ports on its own guest interface.
4. Explicit **deny + log** from guest to every RFC1918 corporate range, the AP/switch management VLAN, the FortiGate management interfaces, and the remote site over VPN (except the single portal rule).
5. Wireless client isolation on the guest SSID. Guest-to-guest L2 traffic is not possible on the AP.
6. Corporate SSIDs, VLANs, DHCP scopes and policies are **not modified**. New objects are added only.

## 2.2 Logical design

| Item | Bangalore (FortiGate 60F) | Hyderabad (FortiGate 30G) |
|---|---|---|
| SSID | `BESSEL-GUEST-BLR` | `BESSEL-GUEST-HYD` |
| Guest VLAN ID | `<VLAN_BLR>` | `<VLAN_HYD>` |
| Parent interface (towards APs) | `<PARENT_IF_BLR>` | `<PARENT_IF_HYD>` |
| VLAN interface name | `GUEST-BLR` | `GUEST-HYD` |
| Guest subnet / gateway | `<GUEST_NET_BLR>/<len>`, `.1` | `<GUEST_NET_HYD>/<len>`, `.1` |
| DHCP range / lease | `<range>`, 8 h | `<range>`, 8 h |
| DNS to clients | FortiGate guest IP (DNS forwarder, split entry for portal host) | same |
| RADIUS client source IP | `<FGT_BLR_RADIUS_SOURCE_IP>` | `<FGT_HYD_RADIUS_SOURCE_IP>` (inside VPN phase-2) |
| Captive portal post host | `<GUEST_GW_BLR>:1000` | `<GUEST_GW_HYD>:1000` |
| CoA listener | `<FGT_BLR_COA_IP>` UDP 3799 | `<FGT_HYD_COA_IP>` UDP 3799 via VPN |
| Path to portal | guest IF → server interface | guest IF → VPN tunnel → BLR → server |

Size the subnet for peak visitors plus 50 %. A /24 (≈250 leases) is usually enough. Use a range that does not overlap any existing site or VPN subnet.

## 2.3 Flows that must be permitted

| # | Source | Destination | Port | Where enforced | Purpose |
|---|---|---|---|---|---|
| F1 | Guest subnet (BLR) | APP_SERVER_IP | TCP <PORTAL_PORT> | FGT-BLR policy + exempt list | Guest portal before auth |
| F2 | Guest subnet (HYD) | APP_SERVER_IP | TCP <PORTAL_PORT> | FGT-HYD policy + exempt list, VPN selectors, FGT-BLR VPN→server policy | Guest portal before auth |
| F3 | Guest subnets | Internet | any (or web-only) | Guest internet policy, NAT, shaping, auth required | Internet after auth |
| F4 | FGT-BLR source IP | APP_SERVER_IP | UDP 1812, 1813 | FGT-BLR local-out (no policy needed), server firewall | RADIUS auth/acct |
| F5 | FGT-HYD source IP | APP_SERVER_IP | UDP 1812, 1813 | VPN selectors + FGT-BLR VPN→server policy | RADIUS auth/acct |
| F6 | APP_SERVER_IP | FGT-BLR CoA IP | UDP 3799 | FGT-BLR local-in (trusted RADIUS server) | Revocation |
| F7 | APP_SERVER_IP | FGT-HYD CoA IP | UDP 3799 | FGT-BLR server→VPN policy, VPN selectors | Revocation |
| F8 | Corporate admin subnets | APP_SERVER_IP | TCP <PORTAL_PORT> (admin host) | nginx allow-list + existing policies | Admin console |
| F9 | APP_SERVER_IP | FGT IPs | ICMP | optional | Dashboard reachability tile |

Everything else from the guest subnets toward internal ranges is **denied and logged**.

## 2.4 Worksheet (fill from discovery, then approve)

| Parameter | BLR value | HYD value | Verified by / date |
|---|---|---|---|
| FortiOS version/build | | | |
| AP-facing interface | | | |
| Guest VLAN ID | | | |
| Guest subnet | | | |
| Guest gateway IP | | | |
| DHCP range | | | |
| DNS servers to guests | | | |
| WAN interface(s) | | | |
| VPN tunnel interface name | | | |
| FortiGate → server source IP | | | |
| Corporate subnets (deny group) | | | |
| Management subnets (deny group) | | | |
| Per-device bandwidth limit | | | |
| Total guest bandwidth cap | | | |
| APP_SERVER_IP | | | |
| Guest portal hostname | | | |
| Admin hostname | | | |
