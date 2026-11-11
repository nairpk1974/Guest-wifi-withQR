"""End-to-end lab test: API + guest portal + FreeRADIUS (rlm_rest) + fake FortiGate CoA listener.

Simulates both FortiGates by sending RADIUS from 127.0.0.2 (fgt-blr) and 127.0.0.3 (fgt-hyd).
Run against a lab stack only:  python tests/e2e_lab.py <superadmin-username> <temp-password>
Env: API (default http://127.0.0.1:8000), RADIUS_HOST (127.0.0.1), RADIUS_SECRET_BLR, RADIUS_SECRET_HYD
"""
import os
import re
import socket
import sys
import uuid
from datetime import date

import httpx
import pyotp
from pyrad import packet
from pyrad.dictionary import Dictionary

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
API = os.environ.get("API", "http://127.0.0.1:8000")
RAD_HOST = os.environ.get("RADIUS_HOST", "127.0.0.1")
SECRETS = {"127.0.0.2": os.environ.get("RADIUS_SECRET_BLR", "blr-secret").encode(),
           "127.0.0.3": os.environ.get("RADIUS_SECRET_HYD", "hyd-secret").encode()}
DICT = Dictionary(os.path.join(os.path.dirname(__file__), "lab_dictionary"))
BLR_SRC, HYD_SRC = "127.0.0.2", "127.0.0.3"
POST_URL = "http://10.99.0.1:1000/fgtauth"
NEW_PW = "Lab-Passw0rd!2026"
results = []


def check(name, cond, info=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info and not cond else ""))


def radius(src, code, port, **attrs):
    secret = SECRETS[src]
    if code == packet.AccessRequest:
        req = packet.AuthPacket(code=code, secret=secret, dict=DICT)
    else:
        req = packet.AcctPacket(code=code, secret=secret, dict=DICT)
    for k, v in attrs.items():
        k = k.replace("_", "-")
        req[k] = req.PwCrypt(v) if k == "User-Password" else v
    if code == packet.AccessRequest:
        req.add_message_authenticator()
    raw = req.RequestPacket()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind((src, 0))
    s.settimeout(5)
    s.sendto(raw, (RAD_HOST, port))
    data, _ = s.recvfrom(4096)
    s.close()
    rep = packet.Packet(packet=data, secret=secret, dict=DICT)
    return rep


def auth(src, user, pw, mac):
    return radius(src, packet.AccessRequest, 1812, User_Name=user, User_Password=pw, Calling_Station_Id=mac,
                  Framed_IP_Address="10.50.0.21")


def acct(src, user, status, sid, **extra):
    return radius(src, packet.AccountingRequest, 1813, User_Name=user, Acct_Status_Type=status, Acct_Session_Id=sid,
                  Framed_IP_Address="10.50.0.21", Calling_Station_Id="aa:bb:cc:00:11:22", **extra)


class Admin:
    def __init__(self, username, password):
        self.c = httpx.Client(base_url=API, timeout=20)
        self.csrf = ""
        r = self.c.post("/api/auth/login", json={"username": username, "password": password})
        r.raise_for_status()
        data = r.json()
        self.csrf = data.get("csrf_token", "")
        self.stage = data.get("stage")
        self.needs = data.get("needs", [])
        self.username = username

    def req(self, method, url, **kw):
        h = kw.pop("headers", {})
        h["X-CSRF-Token"] = self.csrf
        return self.c.request(method, url, headers=h, **kw)

    def complete_setup(self, current_pw):
        if "password" in self.needs:
            r = self.req("POST", "/api/auth/password", json={"current_password": current_pw, "new_password": NEW_PW})
            check(f"{self.username}: password change", r.status_code == 200, r.text)
        if "mfa" in self.needs:
            secret = self.req("POST", "/api/auth/mfa/setup").json()["secret"]
            r = self.req("POST", "/api/auth/mfa/confirm", json={"code": pyotp.TOTP(secret).now()})
            check(f"{self.username}: MFA enrolment -> full session", r.json().get("stage") == "full", r.text)
            self.totp = secret


def guest_payload(location_id, name="Lab Visitor", hours=1):
    return {"full_name": name, "company": "Acme Ltd", "mobile": "+91 98450 12345", "email": "visitor@example.com",
            "host_person": "Ravi Kumar", "department": "IT", "location_id": location_id, "purpose": "Vendor meeting",
            "visit_date": date.today().isoformat(), "duration_hours": hours}


def portal_claim(token):
    g = httpx.Client(base_url=API, timeout=20)
    r = g.get(f"/q/{token}")
    m = re.search(r'name="csrf" value="([^"]+)"', r.text)
    if not m:
        return g, r
    r = g.post(f"/q/{token}", data={"csrf": m.group(1), "accept": "yes"})
    return g, r


def creds(html):
    u = re.search(r'name="username" value="([^"]+)"', html)
    p = re.search(r'name="password" value="([^"]+)"', html)
    return (u.group(1), p.group(1)) if u and p else (None, None)


def main():
    su_user, su_pw = sys.argv[1], sys.argv[2]
    su = Admin(su_user, su_pw)
    check("superadmin login requires setup", su.stage == "setup" and "mfa" in su.needs)
    r = su.c.get("/api/meta")
    check("setup-stage session cannot use API", r.status_code == 403)
    su.complete_setup(su_pw)

    # MFA login path
    su2 = httpx.Client(base_url=API)
    r = su2.post("/api/auth/login", json={"username": su_user, "password": NEW_PW}).json()
    check("login with MFA returns ticket", r.get("mfa_required") is True)
    r2 = su2.post("/api/auth/mfa", json={"ticket": r["ticket"], "code": "000000"})
    check("wrong TOTP rejected", r2.status_code == 401)
    r3 = su2.post("/api/auth/mfa", json={"ticket": r["ticket"], "code": pyotp.TOTP(su.totp).now()})
    check("correct TOTP accepted", r3.status_code == 200 and r3.json()["stage"] == "full")

    r = su.c.post("/api/admin/locations/1", json={})
    check("CSRF token required on mutation", r.status_code in (403, 405))

    locs = {l["code"]: l for l in su.req("GET", "/api/admin/locations").json()}
    blr, hyd = locs["BLR"]["id"], locs["HYD"]["id"]
    r = su.req("PATCH", f"/api/admin/locations/{blr}", json={"portal_post_hosts": ["10.99.0.1:1000"],
                                                            "coa_host": "127.0.0.1", "monitor_host": "127.0.0.1"})
    check("configure BLR integration", r.status_code == 200, r.text)
    su.req("PATCH", f"/api/admin/locations/{hyd}", json={"portal_post_hosts": ["10.98.0.1:1000"]})

    # staff accounts
    def mk(username, role, loc=None):
        r = su.req("POST", "/api/admin/users", json={"username": username, "full_name": username.title(),
                                                     "role": role, "location_id": loc})
        if r.status_code == 409:
            return None
        return r.json()["temporary_password"]

    sfx = uuid.uuid4().hex[:4]
    hyd_pw = mk(f"rec-hyd-{sfx}", "reception", hyd)
    aud_pw = mk(f"audit-{sfx}", "auditor")
    r = su.req("POST", "/api/admin/users", json={"username": f"bad-{sfx}", "full_name": "Bad", "role": "reception"})
    check("reception user without location rejected", r.status_code == 400)

    # ---- guest lifecycle at BLR ----
    g = su.req("POST", "/api/guests", json=guest_payload(blr, "Asha Verma", 1)).json()
    check("guest registered as pending", g.get("status") == "pending", g)
    r = su.req("POST", "/api/guests", json={**guest_payload(blr), "duration_hours": 3})
    check("non-allowed duration rejected", r.status_code == 400)
    p = su.req("POST", f"/api/guests/{g['id']}/approve").json()
    check("approval returns QR + code", p.get("qr_svg", "").startswith("data:image/svg") and len(p["access_code"]) == 9)
    token = p["access_url"].rsplit("/", 1)[1]

    r = httpx.get(f"{API}/q/thisisnotarealtoken")
    check("invalid QR rejected", r.status_code == 403 and "not valid" in r.text)

    guest, r = portal_claim(token)
    check("QR claim -> connecting page", r.status_code == 200 and "Connecting" in r.text, r.text[:300])
    check("claim cookie set", "bgw_claim" in guest.cookies)
    _, r = portal_claim(token)
    check("duplicate QR redemption on other device blocked", r.status_code == 403 and "already been used" in r.text)

    r = guest.get("/portal", params={"post": "http://evil.example:1000/fgtauth", "magic": "m1"})
    check("credential post to unknown host refused", "not opened from" in r.text)
    r = guest.get("/portal", params={"post": "http://10.98.0.1:1000/fgtauth", "magic": "m1"})
    check("BLR pass refused at HYD portal", r.status_code == 403)
    r = guest.get("/portal", params={"post": POST_URL, "magic": "m123"})
    user, pw = creds(r.text)
    check("FortiGate redirect -> auto-submit credentials", user and 'value="m123"' in r.text and POST_URL in r.text)
    check("CSP allows form post to FortiGate only", "form-action 'self' http://10.99.0.1:1000" in
          r.headers.get("content-security-policy", ""))

    # ---- RADIUS ----
    rep = auth(BLR_SRC, user, "wrong-password", "aa:bb:cc:00:11:22")
    check("RADIUS wrong password -> Reject", rep.code == packet.AccessReject)
    rep = auth(HYD_SRC, user, pw, "aa:bb:cc:00:11:22")
    check("RADIUS BLR pass from HYD FortiGate -> Reject", rep.code == packet.AccessReject)
    rep = auth(BLR_SRC, user, pw, "aa:bb:cc:00:11:22")
    st = rep.get("Session-Timeout", [0])[0] if rep.code == packet.AccessAccept else 0
    check("RADIUS valid -> Accept with Session-Timeout ~1h", rep.code == packet.AccessAccept and 3500 < st <= 3600, st)
    check("RADIUS reply carries Fortinet-Group-Name",
          rep.code == packet.AccessAccept and rep.get("Fortinet-Group-Name", [""])[0] == "BESSEL-GUEST")
    rep = auth(BLR_SRC, user, pw, "aa:bb:cc:99:99:99")
    check("same credentials on another device -> Reject", rep.code == packet.AccessReject)
    rep = auth(BLR_SRC, user, pw, "AA-BB-CC-00-11-22")
    check("re-auth same device (MAC format variant) -> Accept", rep.code == packet.AccessAccept)

    rep = acct(BLR_SRC, user, "Start", "sess-1")
    check("accounting Start -> Response", rep.code == packet.AccountingResponse)
    acct(BLR_SRC, user, "Interim-Update", "sess-1", Acct_Input_Octets=5_000_000, Acct_Output_Octets=80_000_000,
         Acct_Session_Time=600)
    s = su.req("GET", "/api/sessions", params={"active": "true"}).json()
    mine = [x for x in s["items"] if x["username"] == user]
    check("active session visible with usage", mine and mine[0]["output_octets"] == 80_000_000, s)
    d = su.req("GET", "/api/dashboard").json()
    check("dashboard shows BLR active session", d["active_sessions_by_location"].get("BLR", 0) >= 1, d)
    gd = su.req("GET", f"/api/guests/{g['id']}").json()
    check("guest status active with expiry", gd["status"] == "active" and gd["access_expires_at"])
    st = guest.get("/portal/status")
    check("guest status page shows connected", "online" in st.text)

    # ---- RBAC ----
    rh = Admin(f"rec-hyd-{sfx}", hyd_pw)
    rh.complete_setup(hyd_pw)
    r = rh.req("GET", f"/api/guests/{g['id']}")
    check("HYD reception cannot open BLR guest", r.status_code == 403)
    r = rh.req("POST", "/api/guests", json=guest_payload(blr))
    check("HYD reception cannot register at BLR", r.status_code == 403)
    lst = rh.req("GET", "/api/guests").json()
    check("HYD reception list scoped to HYD", all(x["location_code"] == "HYD" for x in lst["items"]))
    r = rh.req("GET", "/api/admin/users")
    check("reception cannot manage users", r.status_code == 403)
    au = Admin(f"audit-{sfx}", aud_pw)
    au.complete_setup(aud_pw)
    r = au.req("POST", "/api/guests", json=guest_payload(blr))
    check("auditor cannot register guests", r.status_code == 403)
    r = au.req("GET", "/api/reports/audit", params={"format": "json"})
    check("auditor can read audit log", r.status_code == 200 and len(r.json()["rows"]) > 0)
    r = rh.req("GET", "/api/reports/audit")
    check("reception cannot read audit log", r.status_code == 403)

    # ---- revocation ----
    r = su.req("POST", f"/api/guests/{g['id']}/revoke", json={"reason": "Visit ended early"}).json()
    check("revoke sends Disconnect-Request (ACK)", r.get("status") == "revoked" and "ack" in r.get("disconnect_results", []), r)
    coa_log = open("/tmp/coa.log").read() if os.path.exists("/tmp/coa.log") else ""
    check("CoA listener received User-Name + Acct-Session-Id", user in coa_log and "sess-1" in coa_log)
    rep = auth(BLR_SRC, user, pw, "aa:bb:cc:00:11:22")
    check("RADIUS after revoke -> Reject", rep.code == packet.AccessReject)
    acct(BLR_SRC, user, "Stop", "sess-1", Acct_Input_Octets=6_000_000, Acct_Output_Octets=90_000_000,
         Acct_Session_Time=700, Acct_Terminate_Cause="User-Request")
    r = guest.get("/portal/status")
    check("guest status page shows revoked", "revoked" in r.text)

    # ---- access-code flow + duration expiry ----
    g2 = su.req("POST", "/api/guests", json=guest_payload(blr, "Code Flow Guest", 4)).json()
    p2 = su.req("POST", f"/api/guests/{g2['id']}/approve").json()
    gc = httpx.Client(base_url=API)
    r = gc.get("/portal", params={"post": POST_URL, "magic": "m9"})
    csrf = re.search(r'name="csrf" value="([^"]+)"', r.text).group(1)
    r = gc.post("/portal/code", data={"csrf": csrf, "code": "ZZZZ-ZZZZ", "post": POST_URL, "magic": "m9", "accept": "yes"})
    check("wrong access code rejected", "not valid" in r.text)
    csrf = re.search(r'name="csrf" value="([^"]+)"', r.text).group(1)
    r = gc.post("/portal/code", data={"csrf": csrf, "code": p2["access_code"].lower(), "post": POST_URL, "magic": "m9",
                                      "accept": "yes"})
    u2, pw2 = creds(r.text)
    check("access code (case-insensitive) -> credentials", bool(u2))
    rep = auth(BLR_SRC, u2, pw2, "aa:bb:cc:00:22:33")
    st = rep.get("Session-Timeout", [0])[0] if rep.code == packet.AccessAccept else 0
    check("4 h pass -> Session-Timeout ~4h", 14300 < st <= 14400, st)
    acct(BLR_SRC, u2, "Start", "sess-2")
    print("  (simulating 4 h elapsed and running one worker cycle)")
    os.system(f"psql -q -h 127.0.0.1 -p 5433 -U postgres -d guestwifi -c \"UPDATE access_passes SET "
              f"access_expires_at = now() - interval '1 minute' WHERE radius_username = '{u2}'\"")
    from app.worker import run_once  # noqa: E402
    run_once(1)
    gd = su.req("GET", f"/api/guests/{g2['id']}").json()
    check("worker expires guest after duration", gd["status"] == "expired")
    check("expiry triggered Disconnect-Request", "sess-2" in open("/tmp/coa.log").read())
    live = su.req("GET", "/api/sessions", params={"active": "true"}).json()["items"]
    check("disconnected session closed on ACK", not any(x["username"] == u2 for x in live))
    rep = auth(BLR_SRC, u2, pw2, "aa:bb:cc:00:22:33")
    check("RADIUS after expiry -> Reject", rep.code == packet.AccessReject)

    # ---- expired (unused) QR ----
    g3 = su.req("POST", "/api/guests", json=guest_payload(blr, "Late Guest", 8)).json()
    p3 = su.req("POST", f"/api/guests/{g3['id']}/approve").json()
    os.system("psql -q -h 127.0.0.1 -p 5433 -U postgres -d guestwifi -c \"UPDATE access_passes SET redeem_before = "
              f"now() - interval '1 minute' WHERE guest_id = '{g3['id']}'\"")
    r = httpx.get(p3["access_url"].replace("https://guest.test", API))
    check("expired QR rejected", r.status_code == 403 and "expired" in r.text)

    # ---- reject + reissue ----
    g4 = su.req("POST", "/api/guests", json=guest_payload(blr, "Rejected Guest", 12)).json()
    r = su.req("POST", f"/api/guests/{g4['id']}/reject", json={"reason": "Host unavailable"}).json()
    check("reject request", r["status"] == "rejected")
    g5 = su.req("POST", "/api/guests", json=guest_payload(blr, "=HYPERLINK(\"x\")", 12)).json()
    p5 = su.req("POST", f"/api/guests/{g5['id']}/approve").json()
    p5b = su.req("POST", f"/api/guests/{g5['id']}/reissue").json()
    r = httpx.get(p5["access_url"].replace("https://guest.test", API))
    check("re-issue invalidates old QR", r.status_code == 403)
    r = httpx.get(p5b["access_url"].replace("https://guest.test", API))
    check("re-issued QR works", r.status_code == 200)

    # ---- quick pass: name + mobile only, registered and approved in one call ----
    r = su.req("POST", "/api/guests?approve=true", json={"full_name": "Quick Visitor", "mobile": "9845012345"})
    qp = r.json() if r.status_code == 201 else {}
    check("quick pass (name+mobile only) returns QR", r.status_code == 201 and qp.get("status") == "approved"
          and qp.get("pass", {}).get("qr_svg", "").startswith("data:image/svg"), r.text[:300])
    check("quick pass defaults", qp.get("duration_hours") == 4 and qp.get("company") == "-" and qp.get("location_code") == "BLR")
    r = rh.req("POST", "/api/guests?approve=true", json={"full_name": "HYD Quick", "mobile": "9845012346"})
    check("quick pass by HYD reception lands at HYD", r.status_code == 201 and r.json().get("location_code") == "HYD", r.text[:200])

    # ---- reports ----
    for kind in ["visitors", "logins", "sessions", "locations", "usage", "expired-revoked", "approvals",
                 "auth-failures", "audit"]:
        r = su.req("GET", f"/api/reports/{kind}", params={"format": "json"})
        check(f"report {kind}", r.status_code == 200, r.text[:200])
    r = su.req("GET", "/api/reports/visitors", params={"format": "csv"})
    check("CSV export neutralises formula injection", "'=HYPERLINK" in r.text and r.status_code == 200)
    r = su.req("GET", "/api/reports/sessions", params={"format": "xlsx"})
    check("XLSX export", r.status_code == 200 and r.content[:2] == b"PK")

    # ---- lockout ----
    for _ in range(5):
        httpx.post(f"{API}/api/auth/login", json={"username": f"audit-{sfx}", "password": "nope"})
    r = httpx.post(f"{API}/api/auth/login", json={"username": f"audit-{sfx}", "password": NEW_PW})
    check("account locks after 5 failures", r.status_code == 423)

    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("FAILED:", *failed, sep="\n  ")
        sys.exit(1)


if __name__ == "__main__":
    main()
