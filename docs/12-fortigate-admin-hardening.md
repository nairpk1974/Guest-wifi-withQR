# 12. FortiGate admin access hardening (WAN)

Goal: keep **emergency admin access from the Internet**, but only from trusted public IPs, and stop sending passwords over plain HTTP. LAN and VPN admin access are **not changed**.

Method: a **local-in policy** on the WAN interface only. Unlike per-admin trusted hosts, it cannot lock you out from the LAN.

Verified from the 2026-11-05 backups (FortiOS 7.4.12):

| | 60F Bangalore | 30G Hyderabad |
|---|---|---|
| WAN interface | `wan1`, 106.51.67.116 | `wan` (PPPoE), 49.206.192.47 |
| WAN allowaccess today | `ping https http` | `ping https http` |
| Admin HTTPS port | **4434** (`admin-sport`) | **443** (default) |
| Admin HTTP port | 8080 (`admin-port`) | 80 (default) |
| SSL-VPN | wan1 port 4433: **not touched** | not affected |
| Admin accounts | `admin`, `IT`, `it` (all super_admin, no trusted hosts) | `admin`, `Trustly` (super_admin) |
| Existing local-in policies | none | none |

Allowed sources:

- the other office's WAN IP, so each site can rescue the other when the IPsec tunnel is down;
- optionally, your own static public IP: `<ADMIN_PUBLIC_IP>`.

> The 49.206.192.47 entry assumes the Hyderabad PPPoE address is static. The Bangalore VPN config already depends on it. If your ISP changes it, update the address object.

---

## Step 0: Before you start (both units)

1. Back up the config: **System → Configuration → Backup**.
2. Do the work **from the LAN** of the site you're changing, e.g. `https://192.168.0.1:4434` for BLR. Keep that session open throughout.
3. Have a phone with **mobile data** (not office Wi-Fi) ready for testing.

---

## Step 1: Bangalore FortiGate 60F

Open **CLI Console** (top-right `>_`) and paste one block at a time.

```
config firewall address
    edit "MGMT-HYD-WAN"
        set subnet 49.206.192.47 255.255.255.255
        set comment "Hyderabad FortiGate WAN - emergency admin"
    next
end
```

Optional: only if you have a static public IP of your own. Skip this block otherwise.

```
config firewall address
    edit "MGMT-ADMIN-HOME"
        set subnet <ADMIN_PUBLIC_IP> 255.255.255.255
    next
end
```

Group the allowed sources. Add `"MGMT-ADMIN-HOME"` to the member list only if you created it.

```
config firewall addrgrp
    edit "MGMT-WAN-ALLOWED"
        set member "MGMT-HYD-WAN"
    next
end
```

Define the admin service:

```
config firewall service custom
    edit "FGT-ADMIN-4434"
        set tcp-portrange 4434
        set comment "FortiGate HTTPS admin (admin-sport)"
    next
end
```

Allow trusted sources first, then deny everyone else, on wan1 only:

```
config firewall local-in-policy
    edit 0
        set intf "wan1"
        set srcaddr "MGMT-WAN-ALLOWED"
        set dstaddr "all"
        set service "FGT-ADMIN-4434"
        set schedule "always"
        set action accept
        set comments "Emergency admin from trusted IPs"
    next
    edit 0
        set intf "wan1"
        set srcaddr "all"
        set dstaddr "all"
        set service "FGT-ADMIN-4434"
        set schedule "always"
        set action deny
        set comments "Block admin GUI from Internet"
    next
end
```

Then remove plain HTTP admin from the WAN. `set allowaccess` replaces the whole list, so type it exactly:

```
config system interface
    edit "wan1"
        set allowaccess ping https
    next
end
```

**Check:**

```
show firewall local-in-policy
show system interface wan1 | grep allowaccess
```

**Test:**

| Test | Expected |
|---|---|
| From the BLR LAN: `https://192.168.0.1:4434` | Works (unchanged) |
| Phone on mobile data: `https://106.51.67.116:4434` | Does **not** load |
| Phone on mobile data: `http://106.51.67.116:8080` | Does **not** load |
| SSL-VPN from outside (FortiClient to port 4433) | Still connects |
| From an allowed IP (your home IP, if added): `https://106.51.67.116:4434` | Login page loads |

Note: while the IPsec tunnel is **up**, traffic from Hyderabad to 106.51.67.116 goes through the tunnel (static route 8 on the 30G), not the Internet. So the HYD → BLR emergency path is only used when the tunnel is down, which is exactly when you need it. For everyday cross-site admin, use the LAN IP over the VPN.

**Rollback** (if anything misbehaves):

```
config firewall local-in-policy
    purge
end
```

`purge` deletes all local-in policies. There were none before this change.

---

## Step 2: Hyderabad FortiGate 30G (on a different day, from the HYD LAN)

```
config firewall address
    edit "MGMT-BLR-WAN"
        set subnet 106.51.67.116 255.255.255.255
        set comment "Bangalore FortiGate WAN - emergency admin"
    next
end
config firewall addrgrp
    edit "MGMT-WAN-ALLOWED"
        set member "MGMT-BLR-WAN"
    next
end
config firewall local-in-policy
    edit 0
        set intf "wan"
        set srcaddr "MGMT-WAN-ALLOWED"
        set dstaddr "all"
        set service "HTTPS"
        set schedule "always"
        set action accept
        set comments "Emergency admin from trusted IPs"
    next
    edit 0
        set intf "wan"
        set srcaddr "all"
        set dstaddr "all"
        set service "HTTPS"
        set schedule "always"
        set action deny
        set comments "Block admin GUI from Internet"
    next
end
config system interface
    edit "wan"
        set allowaccess ping https
    next
end
```

The 30G admin GUI uses the default port 443, so the built-in `HTTPS` service is correct. No VIPs or other services on the 30G WAN use TCP 443.

**Test:** the same table as Step 1, with `https://192.168.2.1` (LAN) and `https://49.206.192.47` (WAN).

---

## Step 3: Recommended follow-ups (optional)

- **Two-factor login for admins.** Enable FortiToken Mobile, or e-mail tokens, on the `admin`, `IT`, `it` and `Trustly` accounts.
- **Fewer admin accounts.** The 60F has both `IT` and `it`. Remove one if it's a duplicate, and rename `admin` to something less guessable.
- **Emergency path without the Internet.** Keep a USB console cable or FortiExplorer, or register both units in FortiGate Cloud.
- **Patching.** Stay on the latest 7.4.x patch release.

---

## Step 4: Trusted hosts per admin account (management only from known devices)

Verified 2026-11-05:

- IT laptop: Wi-Fi MAC `ac:74:b1:07:8d:34`, already **DHCP-reserved on the 30G as 192.168.2.86** (dhcp server 1, reserved-address 1).
- AD servers: 192.168.0.2 (BLR) and 192.168.2.2 (HYD).

| Trusted host | 60F (BLR) | 30G (HYD) | Reaches the FortiGate via |
|---|---|---|---|
| IT laptop 192.168.2.86 | ✔ | ✔ | HYD LAN / IPsec tunnel |
| AD server 192.168.0.2 | ✔ | ✔ | BLR LAN / IPsec tunnel |
| AD server 192.168.2.2 | ✔ | ✔ | HYD LAN / IPsec tunnel |
| Windows management host 192.168.0.8 | ✔ | ✔ | BLR LAN / IPsec tunnel |
| Other office WAN (emergency, tunnel down) | 49.206.192.47 | 106.51.67.116 | Internet |

Rules:

- Set the **same list on every admin account**. One account without trusted hosts reopens access from anywhere.
- Apply it **from a trusted device** (the laptop at 192.168.2.86).
- Keep a second CLI/GUI session open until you have tested a fresh login.

### 30G (Hyderabad)

Repeat the `edit` block for `"Trustly"`.

```
config system admin
    edit "admin"
        set trusthost1 192.168.2.86 255.255.255.255
        set trusthost2 192.168.2.2 255.255.255.255
        set trusthost3 192.168.0.2 255.255.255.255
        set trusthost4 106.51.67.116 255.255.255.255
        set trusthost5 192.168.0.8 255.255.255.255
    next
end
```

### 60F (Bangalore)

Repeat the `edit` block for `"IT"` and `"it"`.

```
config system admin
    edit "admin"
        set trusthost1 192.168.2.86 255.255.255.255
        set trusthost2 192.168.0.2 255.255.255.255
        set trusthost3 192.168.2.2 255.255.255.255
        set trusthost4 49.206.192.47 255.255.255.255
        set trusthost5 192.168.0.8 255.255.255.255
    next
end
```

### Test

1. From the laptop: open a fresh login. It should work.
2. From any other PC on the LAN: the login page refuses or does not load.

### Rollback

From a trusted device, or the console cable, unset the trusted hosts on every account:

```
config system admin
    edit "admin"
        unset trusthost1
        unset trusthost2
        unset trusthost3
        unset trusthost4
        unset trusthost5
    next
end
```

Repeat for each admin account.

### Step 4b: Manage the 60F from the Hyderabad laptop over the VPN

`https://192.168.0.1:4434` does not load from 192.168.2.86 today. The admin GUI is not enabled on the IPsec tunnel interface where that traffic arrives.

Apply on the 60F **from 192.168.0.8**, after Step 4:

```
config system interface
    edit "Blr-to-Hyd"
        set allowaccess ping https
    next
end
```

Trusted hosts still limit who can log in. Only the listed IPs (laptop, AD servers, .8, emergency WAN) are accepted.

**Test:** from the laptop, `https://192.168.0.1:4434` loads and login works.

**Rollback:** `set allowaccess` with nothing after it on `Blr-to-Hyd` (the interface had no admin access before).

---

## Status: applied (2026-11-05 to 2026-11-09)

Trusted hosts are set on **every** admin account. 60F: `admin`, `IT`, `it`. 30G: `admin`, `Trustly`.

| # | Trusted host | Device | Fixed by |
|---|---|---|---|
| 1 | 192.168.2.86 | Nair laptop (HYD Wi-Fi) | 30G DHCP reservation (MAC ac:74:b1:07:8d:34) |
| 2 | 192.168.0.200 | Nair laptop (BLR Wi-Fi) | 60F DHCP reservation 2 (same MAC) |
| 3 | 192.168.0.8 | Windows management host | Static IP |
| 4 | 192.168.0.2 | AD server BLR | Static IP |
| 5 | 192.168.2.2 | AD server HYD | Static IP |
| 6 | 49.206.192.47 (on 60F) / 106.51.67.116 (on 30G) | Other office WAN, emergency only | Static WAN IPs |
| 7 | 192.168.0.57 | NaniReddy PC | 60F DHCP reservation (MAC bc:38:98:62:7e:56) |
| 8 | 192.168.0.68 | Dayananda-PC | 60F DHCP reservation (MAC 4c:0f:3e:c4:55:63) |

Fresh logins were tested from the trusted devices.

Remaining:

- Remove `http` from WAN `allowaccess` on both units.
- The WAN local-in policy (Steps 1–2) is now optional defence in depth.
