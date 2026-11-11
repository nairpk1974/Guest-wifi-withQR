# 3. FortiGate configuration – 60F (Bangalore) and 30G (Hyderabad)

> **DRAFT – do not apply.** This is the configuration *plan*: which objects are needed and the FortiOS CLI structure, with every device-specific value as `<PLACEHOLDER>`. It becomes the device-wise final configuration only after:
> 1. the discovery outputs (`00-discovery-checklist.md`) have been reviewed;
> 2. every command has been checked against the **exact FortiOS version** on each unit (the 60F and 30G may run different builds, so syntax and defaults can differ);
> 3. a configuration backup has been taken and a change window approved.
>
> Apply BLR first, run the BLR tests in `09-testing-checklist.md`, then HYD.

Object names are prefixed `BGW-` so they never collide with existing objects.

## 3.1 Objects common to both sites (values per site)

| Object | Purpose |
|---|---|
| `BGW-GUEST-NET` (address) | Guest subnet of this site |
| `BGW-PORTAL` (address) | `APP_SERVER_IP/32` |
| `BGW-CORP-DENY` (address group) | All corporate, server, management, CCTV, AP-management and remote-site ranges. Built from discovery |
| `BGW-RADIUS` (user radius) | Points to the app server. PAP, accounting enabled, CoA enabled |
| `BGW-GUEST-GRP` (user group, firewall) | Member `BGW-RADIUS` and match `Fortinet-Group-Name = BESSEL-GUEST` |
| `BGW-EXEMPT` (security exempt list) | Lets unauthenticated guests reach `BGW-PORTAL` TCP <PORTAL_PORT> |
| `BGW-PORTAL-SVC` (custom service) | TCP `<PORTAL_PORT>` (8444 on Docker-vm), used by the exempt list and portal policies |
| `BGW-PER-DEVICE` (per-IP shaper) | Per-guest bandwidth limit (decision D4) |
| `BGW-GUEST-TOTAL` (shared shaper) | Total guest cap (decision D4) |

## 3.2 Bangalore – FortiGate 60F (draft CLI structure)

```
# --- 1. Guest VLAN interface --------------------------------------------------
config system interface
    edit "BGW-GUEST"
        set vdom "<VDOM_BLR>"                       # usually root, confirm
        set interface "<PARENT_IF_BLR>"             # AP-facing port/switch from discovery
        set vlanid <VLAN_BLR>
        set ip <GUEST_GW_BLR> <GUEST_MASK_BLR>
        set allowaccess ping                        # no https/ssh/http admin on guest IF
        set role lan
        set device-identification enable
        set security-mode captive-portal
        set security-external-web "https://<GUEST_HOST>:<PORTAL_PORT>/portal"
        set security-groups "BGW-GUEST-GRP"
        set security-exempt-list "BGW-EXEMPT"
        set alias "Guest Wi-Fi"
    next
end

# --- 2. DHCP / DNS for guests --------------------------------------------------
config system dhcp server
    edit <NEXT_FREE_DHCP_ID_BLR>
        set interface "BGW-GUEST"
        set default-gateway <GUEST_GW_BLR>
        set netmask <GUEST_MASK_BLR>
        set dns-service default                      # = FortiGate guest IP
        set lease-time 28800
        config ip-range
            edit 1
                set start-ip <DHCP_START_BLR>
                set end-ip <DHCP_END_BLR>
            next
        end
    next
end
config system dns-server
    edit "BGW-GUEST"
        set mode recursive                           # or forward-only, per decision D5
    next
end
# Split DNS so guests resolve the portal host to the server's internal IP (decision D5):
config system dns-database
    edit "bgw-portal"
        set domain "<GUEST_HOST_DOMAIN>"
        set authoritative disable
        config dns-entry
            edit 1
                set hostname "<GUEST_HOST_LABEL>"
                set ip <APP_SERVER_IP>
            next
        end
    next
end

# --- 3. Addresses / services ----------------------------------------------------
config firewall service custom
    edit "BGW-PORTAL-SVC"
        set tcp-portrange <PORTAL_PORT>             # 8444 (Docker-vm 192.168.0.10)
    next
end
config firewall address
    edit "BGW-GUEST-NET-BLR"
        set subnet <GUEST_NET_BLR> <GUEST_MASK_BLR>
    next
    edit "BGW-PORTAL"
        set subnet <APP_SERVER_IP> 255.255.255.255
    next
end
config firewall addrgrp
    edit "BGW-CORP-DENY"
        set member <list of existing corporate/mgmt/CCTV/server/VPN-remote address objects>
    next
end

# --- 4. RADIUS server (the Docker server) ---------------------------------------
config user radius
    edit "BGW-RADIUS"
        set server "<APP_SERVER_IP>"
        set secret <RADIUS_SECRET_BLR>               # from .env, entered manually
        set auth-type pap
        set source-ip <FGT_BLR_RADIUS_SOURCE_IP>     # if needed to pick the right interface
        set radius-coa enable                        # accept Disconnect-Request on UDP 3799
        set acct-interim-interval 300
        config accounting-server
            edit 1
                set status enable
                set server "<APP_SERVER_IP>"
                set secret <RADIUS_SECRET_BLR>
            next
        end
    next
end

config user group
    edit "BGW-GUEST-GRP"
        set member "BGW-RADIUS"
        set authtimeout 720                          # hard cap 12 h (verify unit/semantics on this build)
        config match
            edit 1
                set server-name "BGW-RADIUS"
                set group-name "BESSEL-GUEST"        # = RADIUS_GROUP_NAME in .env
            next
        end
    next
end

config user setting
    set auth-timeout-type hard-timeout               # expiry not extended by activity (verify on build)
end

config user security-exempt-list
    edit "BGW-EXEMPT"
        config rule
            edit 1
                set srcaddr "BGW-GUEST-NET-BLR"
                set dstaddr "BGW-PORTAL"
                set service "BGW-PORTAL-SVC"          # TCP <PORTAL_PORT>
            next
        end
    next
end

# --- 5. Shaping (values = decision D4) --------------------------------------------
config firewall shaper per-ip-shaper
    edit "BGW-PER-DEVICE"
        set max-bandwidth <KBPS_PER_DEVICE>
        set max-concurrent-session <MAX_SESSIONS>
    next
end
config firewall shaper traffic-shaper
    edit "BGW-GUEST-TOTAL"
        set maximum-bandwidth <KBPS_TOTAL>
        set per-policy enable
    next
end

# --- 6. Policies (insert in the position decided from discovery) ------------------
config firewall policy
    edit 0
        set name "BGW-guest-to-portal"
        set srcintf "BGW-GUEST"
        set dstintf "<SERVER_SIDE_IF_BLR>"
        set srcaddr "BGW-GUEST-NET-BLR"
        set dstaddr "BGW-PORTAL"
        set action accept
        set service "BGW-PORTAL-SVC"          # TCP <PORTAL_PORT>
        set schedule "always"
        set captive-portal-exempt enable
        set logtraffic all
    next
    edit 0
        set name "BGW-guest-deny-internal"
        set srcintf "BGW-GUEST"
        set dstintf "any"                            # or each internal + VPN IF; confirm 'any' use
        set srcaddr "BGW-GUEST-NET-BLR"
        set dstaddr "BGW-CORP-DENY"
        set action deny
        set service "ALL"
        set schedule "always"
        set logtraffic all
    next
    edit 0
        set name "BGW-guest-internet"
        set srcintf "BGW-GUEST"
        set dstintf "<WAN_IF_BLR>"
        set srcaddr "BGW-GUEST-NET-BLR"
        set dstaddr "all"
        set action accept
        set service "ALL"                            # or restricted service group
        set schedule "always"
        set nat enable
        set traffic-shaper "BGW-GUEST-TOTAL"
        set per-ip-shaper "BGW-PER-DEVICE"
        set utm-status enable                        # optional, licences (D9)
        set logtraffic all
    next
end
# For HYD guests (arriving over the VPN) reaching the portal on this site:
config firewall policy
    edit 0
        set name "BGW-HYD-guest-to-portal"
        set srcintf "<VPN_IF_BLR_TO_HYD>"
        set dstintf "<SERVER_SIDE_IF_BLR>"
        set srcaddr "BGW-GUEST-NET-HYD"
        set dstaddr "BGW-PORTAL"
        set action accept
        set service "BGW-PORTAL-SVC"          # TCP <PORTAL_PORT>
        set schedule "always"
        set logtraffic all
    next
    # plus: HYD FortiGate source IP -> BGW-PORTAL UDP 1812-1813, and BGW-PORTAL -> HYD CoA IP UDP 3799
end
```

> Whether shaper fields sit on the firewall policy or in a separate `firewall shaping-policy` depends on the FortiOS version. Confirm against the build and use the method it supports.

## 3.3 Hyderabad – FortiGate 30G

Same structure as §3.2 with HYD values. Differences to confirm against the 30G's firmware and hardware:

- **Interfaces.** The 30G has fewer ports and a default hardware switch. The guest VLAN must sit on the AP-facing switch interface found in discovery.
- **Portal path.** `dstintf` for `BGW-guest-to-portal` is the **VPN tunnel interface** to BLR.
- **VPN.** Add `BGW-GUEST-NET-HYD ↔ BGW-PORTAL/32` to both sides' phase-2 selectors, or confirm the existing selectors already cover it. The RADIUS `source-ip` must be an address inside the phase-2 selectors so RADIUS and CoA ride the tunnel.
- **Deny group.** Includes the BLR corporate ranges reachable over the VPN.
- **Feature check.** Confirm captive portal on a VLAN interface, `radius-coa` and shaping are available on this model and build. If a feature is missing, record it and use the fallbacks in `10-troubleshooting.md` §4.
- **Resilience.** If the VPN is down, HYD guests cannot authenticate. Optionally keep a small emergency local guest group on the 30G, disabled by default (decision for Bessel Systems).

## 3.4 Monitoring commands (read-only, both sites)

```
diagnose firewall auth list                 # authenticated guest sessions
diagnose test authserver radius BGW-RADIUS pap <user> <password>   # lab test with a test pass
diagnose debug application fnbamd -1        # RADIUS debug (enable briefly, then 'diagnose debug disable')
diagnose sniffer packet any 'udp port 1812 or udp port 1813 or udp port 3799' 4
get system performance status
```

## 3.5 Rollback

Each object is new and prefixed `BGW-`. To roll back:

1. Remove the `BGW-*` policies.
2. Set `security-mode none` on `BGW-GUEST`.
3. Disable the guest SSID on Omada.
4. Delete the remaining `BGW-*` objects if required.

Restoring the pre-change backup also rolls back, but it reverts every other change too.
