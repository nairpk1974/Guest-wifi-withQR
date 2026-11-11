# 13. Bangalore FortiGate 60F – guest network configuration (FINAL DRAFT)

Built from the verified 60F backup (FortiOS 7.4.12) and the agreed design:

- The PoE switch with the 5 APs moves to 60F port **internal4**. It stays a member of the `internal` hard-switch, so **staff Wi-Fi is unchanged** (untagged, 192.168.0.x).
- Guest Wi-Fi uses **VLAN 50**, tagged by the APs, on the `internal` hard-switch (`virtual-switch-vlan` is already enabled).
- Guest network **10.50.10.0/24**, gateway 10.50.10.1.
- Guest portal and RADIUS: Docker-vm **192.168.0.10**, HTTPS **8444**, RADIUS UDP 1812/1813, CoA UDP 3799.

**Everything here is additive.** New objects are prefixed `BGW-`. While no AP sends VLAN 50 traffic, nobody is affected, so it can be applied during working hours.

Paste **one line at a time**. Watch that the prompt changes after each `config` / `edit`.

---

## 0. Read the RADIUS secret (Docker-vm)

```
cd /opt/bessel-guestwifi
grep '^RADIUS_SECRET_BLR=' .env
```

Use the value after `=` where `<RADIUS_SECRET_BLR>` appears below. **Don't paste it into chat or e-mail.**

---

## 1. Guest VLAN interface (no captive portal yet)

```
config system interface
edit "BGW-GUEST"
set vdom "root"
set interface "internal"
set vlanid 50
set ip 10.50.10.1 255.255.255.0
set allowaccess ping
set role lan
set device-identification enable
set alias "Guest Wi-Fi"
next
end
```

## 2. DHCP for guests

```
config system dhcp server
edit 0
set interface "BGW-GUEST"
set default-gateway 10.50.10.1
set netmask 255.255.255.0
set dns-service local
set lease-time 28800
set timezone-option specify
set timezone "Asia/Kolkata"
config ip-range
edit 1
set start-ip 10.50.10.20
set end-ip 10.50.10.250
next
end
next
end
```

`dns-service local` hands out the FortiGate guest interface (10.50.10.1) as the guests' DNS server.

## 3. DNS for guests (FortiGate answers, with a split entry for the portal)

```
config system dns-server
edit "BGW-GUEST"
set mode recursive
next
end
config system dns-database
edit "bgw-irfmw"
set domain "irfmw.com"
set authoritative disable
config dns-entry
edit 1
set hostname "guest"
set ip 192.168.0.10
next
end
next
end
```

`authoritative disable` means any other irfmw.com name a guest looks up is still resolved normally on the Internet. Only `guest.irfmw.com` is answered locally.

## 4. Addresses and service

```
config firewall address
edit "BGW-GUEST-NET-BLR"
set subnet 10.50.10.0 255.255.255.0
next
edit "BGW-PORTAL"
set subnet 192.168.0.10 255.255.255.255
next
end
config firewall service custom
edit "BGW-PORTAL-SVC"
set tcp-portrange 8444
next
end
```

## 5. RADIUS server and guest group

```
config user radius
edit "BGW-RADIUS"
set server "192.168.0.10"
set secret <RADIUS_SECRET_BLR>
set auth-type pap
set source-ip "192.168.0.1"
set radius-coa enable
set acct-interim-interval 300
config accounting-server
edit 1
set status enable
set server "192.168.0.10"
set secret <RADIUS_SECRET_BLR>
set source-ip "192.168.0.1"
next
end
next
end
config user group
edit "BGW-GUEST-GRP"
set member "BGW-RADIUS"
set authtimeout 720
config match
edit 1
set server-name "BGW-RADIUS"
set group-name "BESSEL-GUEST"
next
end
next
end
```

Test RADIUS from the 60F. A reject is the expected answer, because no guest pass exists yet. It proves the FortiGate, FreeRADIUS and the backend are all talking:

```
diagnose test authserver radius BGW-RADIUS pap testuser testpass
```

Expected: `authenticate 'testuser' against 'pap' failed`. The app dashboard's **RADIUS traffic** for Bangalore turns green.

If you see "no response" / timeout instead, stop and send me the output.

## 6. Exempt list (lets guests reach only the portal before login)

```
config user security-exempt-list
edit "BGW-EXEMPT"
config rule
edit 1
set srcaddr "BGW-GUEST-NET-BLR"
set dstaddr "BGW-PORTAL"
set service "BGW-PORTAL-SVC"
next
end
next
end
```

## 7. Firewall policies

```
config firewall policy
edit 0
set name "BGW-guest-to-portal"
set srcintf "BGW-GUEST"
set dstintf "internal"
set srcaddr "BGW-GUEST-NET-BLR"
set dstaddr "BGW-PORTAL"
set action accept
set schedule "always"
set service "BGW-PORTAL-SVC"
set captive-portal-exempt enable
set logtraffic all
next
edit 0
set name "BGW-guest-deny-internal"
set srcintf "BGW-GUEST"
set dstintf "internal" "dmz" "Blr-to-Hyd" "fortilink"
set srcaddr "BGW-GUEST-NET-BLR"
set dstaddr "all"
set action deny
set schedule "always"
set service "ALL"
set logtraffic all
next
edit 0
set name "BGW-guest-internet"
set srcintf "BGW-GUEST"
set dstintf "wan1"
set srcaddr "BGW-GUEST-NET-BLR"
set dstaddr "all"
set action accept
set schedule "always"
set service "ALL"
set nat enable
set logtraffic all
next
end
```

No other policy uses `BGW-GUEST` as its source interface, so these three cannot change how staff traffic is handled.

## 8. Turn on the captive portal on the guest VLAN

```
config system interface
edit "BGW-GUEST"
set security-mode captive-portal
set security-external-web "https://guest.irfmw.com:8444/portal"
set security-groups "BGW-GUEST-GRP"
set security-exempt-list "BGW-EXEMPT"
next
end
```

## 9. Application settings (admin console → Locations & firewalls → Bangalore)

- **Captive-portal post hosts:** `10.50.10.1:1000`
- **RADIUS CoA/Disconnect host:** `192.168.0.1`, port 3799
- **Monitor host:** `192.168.0.1` (already set)

---

## Verify (before any AP sends VLAN 50)

```
show system interface BGW-GUEST
show firewall policy | grep -f BGW
diagnose test authserver radius BGW-RADIUS pap testuser testpass
```

## Rollback (removes everything above, in reverse order)

```
config system interface
edit "BGW-GUEST"
set security-mode none
next
end
config firewall policy
```

Then `delete <id>` for each of the three `BGW-` policies (find the IDs with `show firewall policy | grep -f BGW`), then `end`. After that, delete the DHCP server entry, the dns-server and dns-database entries, the exempt list, the group, the RADIUS server, the addresses and the service, and finally `config system interface` → `delete "BGW-GUEST"`.

## Still to come

- **Omada:** a test SSID on one AP with VLAN 50, then the cable move (PoE switch → internal4: **unplug from the LAN switch first**).
- **Bandwidth limits:** a per-guest shaper, once the limits are decided.
- **Public certificate** for guest.irfmw.com before real guests use it.
