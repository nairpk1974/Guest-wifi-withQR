# 4. TP-Link Omada configuration

> **DRAFT.** Menu names follow the Omada Controller 5.x layout. Confirm them against the controller version found in discovery, because the OC200, OC300, software and cloud controllers, and their versions, differ in menus and features. Do not modify existing SSIDs.

## 4.1 Pre-checks

1. Back up the controller: **Settings → Maintenance → Backup** (or **Controller Settings → Backup & Restore**, depending on version).
2. Record AP models and firmware, and confirm they support VLAN tagging per SSID and SSID-level client isolation (all current EAP models do; verify for older ones).
3. Confirm the switch ports between APs and FortiGate will carry the new guest VLAN **tagged**:
   - Omada-managed switches: edit the port profile.
   - Other switches: on that switch, with its own change control.

## 4.2 Create the guest VLAN network (VLAN only, no Omada gateway)

1. **Settings → Wired Networks → LAN → Create New LAN.**
2. Name `BGW-GUEST-BLR` (or `-HYD` on the HYD site). Purpose **VLAN** (not "Interface", because the FortiGate is the gateway and DHCP server). VLAN ID `<VLAN_BLR>` / `<VLAN_HYD>`.
3. Add the VLAN to the AP uplink port profiles (tagged) and the FortiGate uplink port.

## 4.3 Create the guest SSID

1. **Settings → Wireless Networks → (site) → Create New Wireless Network.**
2. Network name `BESSEL-GUEST-BLR` or `BESSEL-GUEST-HYD`. Bands as agreed (2.4 + 5 GHz).
3. Security:
   - **OWE / Enhanced Open** if all APs and the controller support it (decision D6). This encrypts the air link without any shared password.
   - Otherwise **None**. Access is still controlled by the FortiGate captive portal.
   - Never use a shared WPA2 password: it would be reusable.
4. **VLAN**: enable, VLAN ID = guest VLAN.
5. **Client isolation / Guest Network** (decision after checking the version):
   - Omada's **Guest Network** toggle isolates clients **and blocks all private (RFC1918) destinations** at the AP. That also blocks the guest portal if `APP_SERVER_IP` is private. Use it only if the controller lets you permit the portal IP (for example an EAP/SSID ACL allow rule for `APP_SERVER_IP` TCP 443 above the guest block). Otherwise leave it off.
   - If Guest Network is left off, enable the SSID-level **client isolation** option where the version offers it, or add an EAP ACL that denies guest-subnet → guest-subnet. FortiGate policies still block all internal destinations.
6. Leave the Omada **Portal** (Omada's own captive portal) **disabled**. The FortiGate does the captive portal.
7. Optional:
   - Rate limit per client as a second layer (the primary limit is on the FortiGate).
   - Schedule the SSID to office hours.
   - Disable "Broadcast SSID" only if Bessel Systems wants it hidden (not recommended: it complicates the Wi-Fi QR).
8. Apply the SSID to the AP group at **that site only**.

## 4.4 Verification

- [ ] The SSID appears only at its own site.
- [ ] A test laptop gets an IP from the guest DHCP range, with gateway and DNS = FortiGate guest IP.
- [ ] Two test devices on the guest SSID cannot ping each other.
- [ ] The guest cannot reach the AP management IPs, the controller, switch management or any corporate IP (see `09-testing-checklist.md`).
- [ ] Corporate SSIDs are unchanged: compare with the pre-change screenshots.
