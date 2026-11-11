# 14. Hyderabad FortiGate 30G – guest network configuration (READY TO APPLY)

Built from the verified 30G and 60F backups (FortiOS 7.4.12). **Design (agreed 2026-11-11): the same as Bangalore, with no new switch.**

- The **guest VLAN 50** is tagged by the HYD APs and passes through the existing unmanaged PoE switches into the 30G `lan` port. This is the same as BLR, where tags pass the unmanaged switch.
- On the 30G, `virtual-switch-vlan` is enabled. A new VLAN interface **`BGW-GUEST` (VLAN 50 on `lan`)** carries guest network **10.50.20.0/24**, gateway 10.50.20.1.
- Staff Wi-Fi and LAN are unchanged (untagged, 192.168.2.x). `dmz`/lan2 is not touched.
- Portal and RADIUS stay on Docker-vm **192.168.0.10** in Bangalore and are reached over the existing `Hyd-to-Blr` VPN:
  - the new phase-2 pair `10.50.20.0/24 ↔ 192.168.0.10/32` carries guest traffic to the portal;
  - the existing `192.168.2.0/24 ↔ 192.168.0.0/24` selector carries RADIUS, sent from 192.168.2.1.

**HYD Omada inventory:** controller **192.168.2.83**, AP1 **192.168.2.54**, AP2 **192.168.2.79**. DHCP reservations on the 30G are done (2026-11-11).

**What can change behaviour:**

- **Step H1** (`virtual-switch-vlan enable`) is a global setting. Do it at a quiet time and have the 30G GUI open. If the 30G refuses the command, stop. In that case we fall back to the managed-switch design, with guests on lan2.
- **Everything else is additive.** New objects are prefixed `BGW-`. Until the SSID exists in Omada, no traffic uses VLAN 50.

Paste **one line at a time**. Watch that the prompt changes after each `config` / `edit`.

---

## Part A – Docker-vm (Bangalore)

```
cd /opt/bessel-guestwifi
grep -E '^(RADIUS_SECRET_HYD|FGT_HYD_RADIUS_SOURCE_IP)=' .env
```

If `FGT_HYD_RADIUS_SOURCE_IP` still shows the placeholder `192.0.2.2`, fix it and recreate the RADIUS container:

```
sed -i 's/^FGT_HYD_RADIUS_SOURCE_IP=.*/FGT_HYD_RADIUS_SOURCE_IP=192.168.2.1/' .env
docker compose up -d --force-recreate radius
docker compose ps
```

Use the `RADIUS_SECRET_HYD` value where `<RADIUS_SECRET_HYD>` appears below. **Don't paste it into chat or e-mail.**

---

## Part B – FortiGate 60F (Bangalore): the VPN side for HYD guests

```
config firewall address
edit "BGW-GUEST-NET-HYD"
set subnet 10.50.20.0 255.255.255.0
next
end
config vpn ipsec phase2-interface
edit "Blr-to-Hyd-Guest"
set phase1name "Blr-to-Hyd"
set proposal aes128-sha1 aes256-sha1 aes128-sha256 aes256-sha256 aes128gcm aes256gcm chacha20poly1305
set auto-negotiate enable
set comments "BGW: HYD guest Wi-Fi -> portal only. Separate child SA."
set src-subnet 192.168.0.10 255.255.255.255
set dst-subnet 10.50.20.0 255.255.255.0
next
end
config router static
edit 0
set dst 10.50.20.0 255.255.255.0
set device "Blr-to-Hyd"
set comment "BGW: HYD guest network"
next
end
config firewall policy
edit 0
set name "BGW-hyd-guest-to-portal"
set srcintf "Blr-to-Hyd"
set dstintf "internal"
set srcaddr "BGW-GUEST-NET-HYD"
set dstaddr "BGW-PORTAL"
set action accept
set schedule "always"
set service "BGW-PORTAL-SVC"
set logtraffic all
next
end
```

RADIUS (from 192.168.2.1) and CoA (to 192.168.2.1) already pass through the existing VPN policies 15 and 16. Nothing changes there.

---

## Part C – FortiGate 30G (Hyderabad)

### H1. Allow VLANs on the switch ports (global – quiet time)

```
config system global
set virtual-switch-vlan enable
end
```

Afterwards, check that the staff LAN still works: you can still ping 192.168.2.83 and a PC still has internet. If the command is rejected, stop and send me the message.

### H2. Guest VLAN interface (no captive portal yet)

```
config system interface
edit "BGW-GUEST"
set vdom "root"
set interface "lan"
set vlanid 50
set ip 10.50.20.1 255.255.255.0
set allowaccess ping
set role lan
set device-identification enable
set alias "Guest Wi-Fi"
next
end
```

The `lan` interface already has its own captive portal ("Guest-group"). A VLAN interface does **not** inherit it, so `BGW-GUEST` uses only the portal set in H9.

### H3. DHCP for guests

```
config system dhcp server
edit 0
set interface "BGW-GUEST"
set default-gateway 10.50.20.1
set netmask 255.255.255.0
set dns-service local
set lease-time 28800
set timezone-option specify
set timezone "Asia/Kolkata"
config ip-range
edit 1
set start-ip 10.50.20.20
set end-ip 10.50.20.250
next
end
next
end
```

### H4. DNS for guests (split entry for the portal)

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

### H5. Addresses, service and VPN selector

```
config firewall address
edit "BGW-GUEST-NET-HYD"
set subnet 10.50.20.0 255.255.255.0
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
config vpn ipsec phase2-interface
edit "Hyd-to-Blr-Guest"
set phase1name "Hyd-to-Blr"
set proposal aes128-sha1 aes256-sha1 aes128-sha256 aes256-sha256 aes128gcm aes256gcm chacha20poly1305
set auto-negotiate enable
set comments "BGW: HYD guest Wi-Fi -> portal only. Separate child SA."
set src-subnet 10.50.20.0 255.255.255.0
set dst-subnet 192.168.0.10 255.255.255.255
next
end
```

The existing route `192.168.0.0/24 → Hyd-to-Blr` already covers 192.168.0.10.

Check that the new child SA comes up (look for a line with `10.50.20.0` ↔ `192.168.0.10`):

```
diagnose vpn tunnel list name Hyd-to-Blr
```

### H6. RADIUS server and guest group

```
config user radius
edit "BGW-RADIUS"
set server "192.168.0.10"
set secret <RADIUS_SECRET_HYD>
set auth-type pap
set source-ip "192.168.2.1"
set radius-coa enable
set acct-interim-interval 300
config accounting-server
edit 1
set status enable
set server "192.168.0.10"
set secret <RADIUS_SECRET_HYD>
set source-ip "192.168.2.1"
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

Test:

```
diagnose test authserver radius BGW-RADIUS pap testuser testpass
```

The expected result is `authenticate 'testuser' against 'pap' failed`, and the dashboard's RADIUS traffic for Hyderabad turns green. If you get no response or a timeout, stop and send me the output.

### H7. Exempt list

```
config user security-exempt-list
edit "BGW-EXEMPT"
config rule
edit 1
set srcaddr "BGW-GUEST-NET-HYD"
set dstaddr "BGW-PORTAL"
set service "BGW-PORTAL-SVC"
next
end
next
end
```

### H8. Firewall policies

```
config firewall policy
edit 0
set name "BGW-guest-to-portal"
set srcintf "BGW-GUEST"
set dstintf "Hyd-to-Blr"
set srcaddr "BGW-GUEST-NET-HYD"
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
set dstintf "lan" "dmz" "Hyd-to-Blr" "gre-to-blr" "fortilink"
set srcaddr "BGW-GUEST-NET-HYD"
set dstaddr "all"
set action deny
set schedule "always"
set service "ALL"
set logtraffic all
next
edit 0
set name "BGW-guest-internet"
set srcintf "BGW-GUEST"
set dstintf "wan"
set srcaddr "BGW-GUEST-NET-HYD"
set dstaddr "all"
set action accept
set schedule "always"
set service "ALL"
set nat enable
set logtraffic all
next
end
```

No other policy uses `BGW-GUEST` as its source, so these three can't change staff traffic.

### H9. Turn on the captive portal on the guest VLAN

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

### H10. App settings (admin console → Locations & firewalls → Hyderabad)

- **Captive-portal post hosts:** `10.50.20.1:1000`
- **RADIUS CoA/Disconnect host:** `192.168.2.1`, port 3799
- **Monitor host:** `192.168.2.1`
- **SSID:** `BESSEL-GUEST-HYD`
- **Enabled:** on

---

## 11. Omada (HYD controller 192.168.2.83)

Create the SSID on the **HYD controller**, not the BLR one. Use the same settings as BLR:

- Name `BESSEL-GUEST-HYD`
- Security: **open**
- **VLAN 50**
- Guest Network: **off**
- Apply to **one AP first** for testing, then to both APs once the test passes.

Test from a phone:

1. Join the SSID. The phone should get a **10.50.20.x** address.
2. Open `http://neverssl.com`. The guest sign-in page should load.
3. Use a pass created for **Hyderabad**. A BLR pass is refused with "valid at Bangalore only".

If the phone gets **no IP**, the HYD unmanaged switches are dropping tagged frames. Tell me which switch models are in the path.

## Verify

```
get system global | grep virtual-switch-vlan
show system interface BGW-GUEST
show firewall policy | grep -f BGW
diagnose test authserver radius BGW-RADIUS pap testuser testpass
diagnose vpn tunnel list name Hyd-to-Blr
```

## Rollback (30G, in reverse order)

1. `BGW-GUEST`: `set security-mode none`.
2. Delete the three `BGW-` policies (find the IDs with `show firewall policy | grep -f BGW`).
3. Delete the exempt list, the group and `BGW-RADIUS`.
4. Delete phase-2 `Hyd-to-Blr-Guest`, the dns-database and dns-server entries, the DHCP server on BGW-GUEST, and the addresses and service.
5. Delete interface `BGW-GUEST`.
6. Optionally, `set virtual-switch-vlan disable`.

On the 60F: delete policy `BGW-hyd-guest-to-portal`, the 10.50.20.0/24 static route, phase-2 `Blr-to-Hyd-Guest`, and address `BGW-GUEST-NET-HYD`.
