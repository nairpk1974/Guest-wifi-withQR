# 1. Infrastructure architecture

> Status: **design**. Device-specific values (interfaces, VLAN IDs, IPs, firmware) are placeholders written as `<LIKE_THIS>`. They will be replaced only after the Phase 1 discovery data has been reviewed (see `00-discovery-checklist.md`).

## 1.1 Overview

![Architecture](architecture.png)

```mermaid
flowchart LR
  subgraph BLR["Head Office – Bangalore"]
    direction TB
    APB["Omada APs<br/>SSID BESSEL-GUEST-BLR<br/>client isolation"] -- "guest VLAN &lt;VLAN_BLR&gt; (trunk)" --> FGB
    FGB["FortiGate 60F<br/>captive portal on guest VLAN if<br/>guest→LAN deny · NAT to WAN<br/>RADIUS client fgt-blr"]
    CORPB["Corporate LAN / AD / ERP /<br/>file · print · CCTV · mgmt"]
    FGB -. "DENY" .-x CORPB
    subgraph SRV["Ubuntu Docker server &lt;APP_SERVER_IP&gt;"]
      direction TB
      NGX["nginx :443<br/>guest host / admin host"] --> FE["frontend<br/>(React SPA)"]
      NGX --> API["backend<br/>(FastAPI)"]
      RAD["FreeRADIUS<br/>:1812/1813 udp"] -- "rlm_rest (internal net)" --> API
      WRK["worker<br/>expiry · CoA · monitoring"] --> DB[("PostgreSQL<br/>internal network only")]
      API --> DB
    end
    FGB -- "RADIUS auth/acct" --> RAD
    WRK -- "Disconnect/CoA udp 3799" --> FGB
    FGB -- "guest → portal 443 only (pre-auth exempt)" --> NGX
  end
  subgraph HYD["Branch Office – Hyderabad"]
    direction TB
    APH["Omada APs<br/>SSID BESSEL-GUEST-HYD"] -- "guest VLAN &lt;VLAN_HYD&gt;" --> FGH["FortiGate 30G<br/>captive portal · NAT<br/>RADIUS client fgt-hyd"]
    CORPH["Corporate LAN"]
    FGH -. "DENY" .-x CORPH
  end
  FGH == "site-to-site IPsec VPN<br/>(RADIUS, CoA, guest→portal 443 only)" ==> FGB
  FGB --> INET(("Internet"))
  FGH --> INET
  STAFF["Reception / Admin PCs<br/>(corporate LAN)"] -- "HTTPS admin host" --> NGX
```

## 1.2 Components

| Component | Where | Role |
|---|---|---|
| Omada APs | both sites | Broadcast `BESSEL-GUEST-BLR` / `BESSEL-GUEST-HYD`, tag guest VLAN, isolate wireless clients. No change to corporate SSIDs. |
| FortiGate 60F (BLR) / 30G (HYD) | each site | Guest VLAN gateway, DHCP/DNS, **captive portal enforcement**, guest→LAN deny, NAT, shaping, session expiry from RADIUS `Session-Timeout`, accepts RADIUS Disconnect (CoA) for revocation. |
| nginx | Docker server | TLS termination. Two virtual hosts: **guest host** (only `/q/*`, `/portal*`, `/static/guest/*`) reachable from guest VLANs; **admin host** restricted to corporate subnets. `/internal/*` never published. |
| frontend | Docker | React admin / reception console (static files). |
| backend | Docker | FastAPI: RBAC, MFA, guest registration & approval, QR/code issue, guest portal pages, RADIUS decision API, reports, audit. |
| FreeRADIUS | Docker | Receives FortiGate RADIUS (PAP) and accounting; forwards every decision to the backend via `rlm_rest`. |
| worker | Docker | Expires passes, sends/retries RADIUS Disconnect-Requests, closes stale sessions, pings firewalls, applies retention. |
| PostgreSQL | Docker | System of record. On an `internal: true` Docker network: no host port, no route to guests. |

## 1.3 Authentication option evaluation (requirement §7)

| Option | Security | Maintainability | Firmware dependence | Verdict |
|---|---|---|---|---|
| **External captive portal + RADIUS** (FortiGate enforces, app decides via RADIUS) | App never holds firewall admin credentials; one-time per-guest credentials; expiry enforced by FortiGate (`Session-Timeout`) + CoA | Standard RADIUS; same design both sites | RADIUS + external portal are long-standing FortiOS features; CoA support verified per firmware in Phase 8 | **Selected** |
| FortiGate REST API (create/delete users or authorise sessions) | Needs an API token with write rights on each firewall | API paths and objects differ between firmware versions | High; 30G and 60F may run different builds | Rejected as primary; may be used read-only for monitoring later |
| FortiGate local guest accounts (guest management) | Credentials live on firewall; app must create them via API | Two places to manage users | Medium | Rejected |
| Plain RADIUS with FortiGate built-in portal (no external page) | Guest would have to type generated username/password | Poor UX, no QR | Low | Kept as **fallback** (same RADIUS backend) if external portal behaves unexpectedly on a firmware |

## 1.4 Guest connection flow

```mermaid
sequenceDiagram
  autonumber
  participant R as Reception (admin host)
  participant A as Backend
  participant G as Guest phone
  participant F as FortiGate
  participant RS as FreeRADIUS
  R->>A: Register visitor → Approve
  A-->>R: Pass: Wi-Fi QR + access QR (256-bit token) + 8-char code
  G->>F: Join open guest SSID (DHCP/DNS from FortiGate)
  G->>A: Scan QR → GET /q/<token> (pre-auth exempt, HTTPS)
  A-->>G: Terms/privacy page (GET never redeems)
  G->>A: POST accept → pass claimed, device cookie set, one-time RADIUS creds created
  G->>F: Browser sent to plain-HTTP trigger URL → intercepted
  F-->>G: 302 to https://guest-host/portal?post=http://<fgt>:1000/fgtauth&magic=…
  G->>A: GET /portal (cookie) → auto-submit form
  G->>F: POST username/password/magic to FortiGate
  F->>RS: Access-Request (PAP)
  RS->>A: rlm_rest authenticate
  A-->>RS: Accept: Session-Timeout = remaining s, Fortinet-Group-Name
  RS-->>F: Access-Accept
  F-->>G: Internet allowed until Session-Timeout
  F->>RS: Accounting Start / Interim / Stop → usage reports
  Note over A,F: Revoke/expiry → worker sends Disconnect-Request (UDP 3799) to FortiGate
```

Fallback without camera: the captive popup shows the code entry page; the guest types the 8-character code, which follows the same path from step 6.

## 1.5 Security properties

- **Unpredictable, single-use passes.** QR tokens are 256-bit random, stored as SHA-256 (and Fernet-encrypted so reception can re-print). Redemption binds the pass to one browser (HttpOnly cookie) and to the first device MAC/IP seen by RADIUS. A second device gets "already used".
- **No reusable secrets on the pass.** The SSID is open (or OWE where APs support it). The per-guest RADIUS password is generated at redemption and never printed.
- **Expiry enforced by the firewall.** `Session-Timeout` is set to the remaining access time. The worker sends a RADIUS Disconnect at expiry as a backstop. Revocation is immediate via Disconnect.
- **Location binding.** A BLR pass is rejected by the HYD FortiGate (RADIUS client shortname check), and the portal refuses to post credentials to any host not configured for that site.
- **Least privilege.** The application holds no FortiGate admin credentials. Its only firewall interactions are RADIUS (FortiGate → server) and RADIUS Disconnect (server → FortiGate UDP 3799 with a shared secret).
