# 17. Show the MAC and device name on Wi-Fi requests (FortiGate read-only API)

A browser never reveals its MAC address, but the FortiGate knows it as soon as the phone gets an IP address. With a **read-only REST API account** on each FortiGate, the app asks the firewall which MAC and hostname belong to the requesting IP. It then shows both on the **Wi-Fi requests** card, before you approve.

This is optional. Without it, everything still works: the MAC appears after the guest is approved and logs in, in Sessions and in the device log.

## What the app reads

- `GET /api/v2/monitor/user/device/query`: the device inventory. Gives MAC, IPv4, **hostname**, OS and hardware vendor/model. It needs `device-identification enable` on the guest interface, which is already set on BGW-GUEST at both sites.
- `GET /api/v2/monitor/system/arp`: a fallback for the MAC if the inventory doesn't have the device yet.

The token is sent as `Authorization: Bearer …` straight to the firewall IP, never through a proxy. The firewall's management certificate is self-signed, so the app doesn't verify it for this internal call. The account can't change anything on the firewall.

## 1. FortiGate 60F (Bangalore)

Paste one line at a time:

```
config system accprofile
edit "bgw-readonly"
set secfabgrp read
set ftviewgrp read
set authgrp read
set sysgrp read
set netgrp read
set loggrp read
set fwgrp read
set vpngrp read
set utmgrp read
set wifi read
next
end
config system api-user
edit "bgw-api"
set comments "Guest Wi-Fi app: read-only device lookup"
set accprofile "bgw-readonly"
set vdom "root"
config trusthost
edit 1
set ipv4-trusthost 192.168.0.10 255.255.255.255
next
end
next
end
execute api-user generate-key bgw-api
```

The last command prints **New API key: …**. It is shown only once. Copy it straight into Docker-vm's `.env` (step 3), and **don't paste it into chat or e-mail.**

If one of the `set …grp read` lines gives `command parse error`, skip that line; that category doesn't exist on your model.

## 2. FortiGate 30G (Hyderabad)

Run the same commands. The trusted host stays **192.168.0.10**, because Docker-vm reaches the 30G over the VPN with its own address. Then copy the second key.

## 3. Docker-vm

```
cd /opt/bessel-guestwifi
nano .env
```

Add or fill these two lines, then save with Ctrl+O, Enter, Ctrl+X:

```
FGT_API_TOKEN_BLR=<key from the 60F>
FGT_API_TOKEN_HYD=<key from the 30G>
```

Apply the change:

```
docker compose up -d --force-recreate backend worker
```

## 4. Admin console → Locations & firewalls

- **Bangalore:** set FortiGate API URL to `https://192.168.0.1:4434` (the 60F admin HTTPS port is 4434). Save, then click **Test API**.
- **Hyderabad:** set FortiGate API URL to `https://192.168.2.1` (the 30G uses the default port 443). Save, then click **Test API**.

A good result reads: "Connected. The firewall reports N devices (N with MAC)."

| Test API says | Fix |
|---|---|
| `HTTP 401` | Wrong token in `.env`, or the backend wasn't recreated after editing `.env` |
| `HTTP 403` | The trusted host isn't 192.168.0.10, or the profile lacks a read permission |
| `cannot reach FortiGate API` | Wrong URL or port, or `https` isn't allowed on that interface. On the 30G the request arrives through the `Hyd-to-Blr` tunnel, which already allows `https`. |

## Result on the Wi-Fi requests card

```
Anita Rao
+91 98765 12345 · HYD
Android 14 · SM-S911B · Samsung Internet · “Galaxy-S23-Anita”
10.50.20.31 · a4:c3:f0:11:22:33
```

The hostname shows only if the phone sends one in DHCP; many phones do. As before, phones normally use a private (random) MAC for each SSID.

## Remove later

```
config system api-user
delete "bgw-api"
end
config system accprofile
delete "bgw-readonly"
end
```

Then clear the API URL in the console and remove the two lines from `.env`.
