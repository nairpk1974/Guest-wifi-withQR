# 15. Permanent Wi-Fi codes

A **permanent code** is a guest Wi-Fi code that a Super Administrator assigns to a named person, such as a contractor, a long-term vendor or staff who use the guest network. It is managed from the admin console under **Permanent codes**.

## How it differs from a visitor pass

| | Visitor pass | Permanent code |
|---|---|---|
| Created by | Reception or Super Admin | **Super Admin only** |
| Valid | 1 / 4 / 8 / 12 h from first sign-in | **Until revoked**, or until an optional end date (inclusive) |
| Devices | One (locked to the first device) | **Any number** of the person's devices |
| Must be used within | 2 h of approval | No limit |
| Re-entering the code | n/a | Each device enters it **once**. The portal remembers the device for a year and signs it in again automatically when the firewall asks. |
| Firewall session limit | RADIUS Session-Timeout = remaining pass time | **None** without an end date. With an end date, the limit is the time until the end date. |
| Revoke | Visitor detail → Revoke | Permanent codes → open → **Revoke code now**. Every device is disconnected at once (CoA). |
| Change code | Re-issue QR, before first use only | **Change code**: the new code is issued, the old one stops working immediately, and all its devices are disconnected |
| Who can see or print the code | Reception and Super Admin | **Super Admin only**. Reception can see the record and revoke it. |
| Office | One office | One office: a HYD code is refused at BLR and vice versa |

All logins are logged as for visitors: Sessions, Reports → Guest login history, and **Guest device log (MAC & mobile)**. The code's detail page lists every device that entered the code (first and last use, IP address).

## Create a code

1. Admin console → **Permanent codes** → **+ New permanent code**.
2. Enter the name and mobile (required), the office, and optionally an end date, company, e-mail, department and a note.
3. **Create code**. Print the card, or open the code later and use **E-mail code**.
4. The person joins the guest SSID, opens any website, enters the code, ticks the terms box and taps **Connect**.

## Firewall setting (once per FortiGate)

Without an end date, the app sends no Session-Timeout. The FortiGate then keeps a signed-in device online until it has been **idle** for the user group's `authtimeout`, which is 720 min (12 h) today. To keep permanent-code devices signed in longer, raise the group timeout on both units:

```
config user group
edit "BGW-GUEST-GRP"
set authtimeout 43200
next
end
```

43200 minutes is 30 days. If the FortiGate rejects that value, use the highest value its error message allows.

**Visitors are not affected.** Their access is still cut at the pass end by the RADIUS Session-Timeout. The FortiGate default `radius-ses-timeout-act hard-timeout` makes that a hard limit; check it with `show full-configuration user radius BGW-RADIUS | grep ses-timeout`.

When a device does have to sign in again (idle longer than the timeout, a new IP address, or a firewall reboot), the portal page opens. A browser that has used the code before is signed in automatically. Phone captive-portal pop-up windows sometimes forget cookies; then the person simply enters the code again.

## Deploy (Docker-vm)

```
cd /opt/bessel-guestwifi
tar -xzf ~/bgw-permanent-codes-update.tar.gz
docker compose up -d --build backend worker frontend
docker compose restart nginx
docker compose ps
```

The backend applies database migration `0003_permanent_codes` automatically on start. It adds two columns to `guests` and the new table `pass_devices`; no existing data is changed.
