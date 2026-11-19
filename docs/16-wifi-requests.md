# 16. Self-service Wi-Fi requests (approve remotely, no code)

A guest without a code can ask for access from the Wi-Fi sign-in page. Reception sees the request live in the console and approves it with one click. The guest's device then connects by itself, with no code to type.

## Guest side

1. The guest joins the guest SSID. The sign-in page opens, either automatically or when they open any website.
2. They tap **No code? Request access**, enter their **name** and **mobile number**, accept the terms, and tap **Request access**.
3. A waiting page opens and checks every 5 seconds.
   - **Approved:** the page shows "Connecting…", sends the browser through the firewall, and the device is signed in automatically.
   - **Declined:** "Not approved" plus the reason.
   - **Not answered within 30 minutes:** "Request expired". The guest can send a new request.

Each device can have one open request. Sending the form again updates that same request.

## Reception side

- **Wi-Fi requests** in the menu (super admin and reception). A red badge shows how many people are waiting; it refreshes every 10 seconds, and the page itself every 5 seconds.
- Each card shows:
  - name, mobile and office;
  - the **device** (from the browser: OS, model where the phone reveals it, browser) and its IP address;
  - how long the guest has been waiting.
- Pick **1 / 4 / 8 / 12 h** (4 h is preselected), then **Approve**. Or **Decline**, with a reason the guest will see.
- Reception only sees requests for their own office. The office is taken from the firewall the guest came through.

## Disconnecting later

- **Active sessions → Disconnect** ends the current session. The guest can sign in again while the pass is still valid.
- **Visitors & approvals → open the visitor → Revoke access now** ends the session and blocks the pass for good.

Approved requests appear in Visitors & approvals like any other visitor, marked "Requested from: Wi-Fi sign-in page · device · IP". After login, the device MAC appears in Sessions and in Reports → Guest device log.

## Device name and model: what is possible

The device line comes from the browser's User-Agent. For example:

| Phone / PC | Shows as |
|---|---|
| Samsung with Samsung Internet | `Android 14 · SM-S911B · Samsung Internet` |
| Many Android phones with Chrome | `Android 10 · Chrome`. Chrome hides the model. |
| iPhone | `iPhone · iOS 17.5`. Apple never reveals the exact model. |
| Windows laptop | `Windows PC · Edge` |

The device's **hostname** (for example "Anita-iPhone") is not visible to a web page. The FortiGate learns it from DHCP and shows it under **Dashboard → Assets / Device inventory**, or with `diagnose user device list` in the CLI.

## Abuse limits

- One open request per device (IP address) per office.
- At most 30 open requests per office at a time.
- Unanswered requests are cancelled after 30 minutes.
- The usual failed-attempt lockout per IP applies.

## Deploy

Database migration `0004_self_requests` adds `guests.source`, `request_claim_hash`, `request_ip`, `request_device` and `request_user_agent`. It runs automatically when the backend starts.
