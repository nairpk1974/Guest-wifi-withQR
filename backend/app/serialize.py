import segno
from segno import helpers

from .access import current_pass, pass_secrets
from .config import get_settings
from .models import AccessPass, Guest, GuestStatus, Location, RadiusSession, User


def iso(dt):
    return dt.isoformat() if dt else None


def location_out(loc: Location, full: bool = False) -> dict:
    d = {"id": loc.id, "code": loc.code, "name": loc.name, "ssid": loc.ssid, "enabled": loc.enabled}
    if full:
        d.update(nas_shortname=loc.nas_shortname, coa_host=loc.coa_host, coa_port=loc.coa_port,
                 portal_post_hosts=loc.portal_post_hosts or [], monitor_host=loc.monitor_host,
                 last_radius_seen_at=iso(loc.last_radius_seen_at), last_ping_ok_at=iso(loc.last_ping_ok_at),
                 last_ping_checked_at=iso(loc.last_ping_checked_at),
                 coa_secret_configured=bool(get_settings().coa_secret_for(loc.code)))
    return d


def user_out(u: User) -> dict:
    return {"id": u.id, "username": u.username, "full_name": u.full_name, "email": u.email, "role": u.role.value,
            "location_id": u.location_id, "location_code": u.location.code if u.location else None,
            "is_active": u.is_active, "mfa_enabled": u.mfa_enabled, "must_change_password": u.must_change_password,
            "locked_until": iso(u.locked_until), "last_login_at": iso(u.last_login_at), "created_at": iso(u.created_at)}


def _name(u: User | None) -> str | None:
    return u.full_name if u else None


def guest_out(g: Guest) -> dict:
    ap = g.passes[-1] if g.passes else None  # latest pass, even if revoked/expired, for history
    expires = ap.access_expires_at if ap else None
    return {"id": str(g.id), "full_name": g.full_name, "company": g.company, "mobile": g.mobile, "email": g.email,
            "host_person": g.host_person, "department": g.department, "location_id": g.location_id,
            "location_code": g.location.code, "purpose": g.purpose, "visit_date": g.visit_date.isoformat(),
            "duration_hours": g.duration_hours, "status": g.status.value, "created_at": iso(g.created_at),
            "created_by": _name(g.created_by), "decided_by": _name(g.decided_by), "decided_at": iso(g.decided_at),
            "rejection_reason": g.rejection_reason, "revoked_by": _name(g.revoked_by), "revoked_at": iso(g.revoked_at),
            "revoke_reason": g.revoke_reason, "access_started_at": iso(ap.access_started_at) if ap else None,
            "access_expires_at": iso(expires), "redeem_before": iso(ap.redeem_before) if ap else None,
            "redeemed_at": iso(ap.redeemed_at) if ap else None, "anonymized": g.anonymized}


def session_out(rs: RadiusSession, g: Guest | None, loc_code: str | None) -> dict:
    return {"id": rs.id, "guest_id": str(rs.guest_id) if rs.guest_id else None,
            "guest_name": g.full_name if g else None, "mobile": g.mobile if g else None,
            "company": g.company if g else None,
            "location_code": loc_code, "username": rs.username, "client_ip": rs.client_ip,
            "client_mac": rs.client_mac, "started_at": iso(rs.started_at), "last_update_at": iso(rs.last_update_at),
            "stopped_at": iso(rs.stopped_at), "input_octets": rs.input_octets, "output_octets": rs.output_octets,
            "session_time": rs.session_time, "terminate_cause": rs.terminate_cause}


def _qr(data: str) -> str:
    return segno.make(data, error="m").svg_data_uri(scale=6, border=2)


def pass_payload(g: Guest, ap: AccessPass) -> dict:
    token, code = pass_secrets(ap)
    url = f"{get_settings().guest_base_url.rstrip('/')}/q/{token}"
    wifi = helpers.make_wifi(ssid=g.location.ssid, password=None, security="nopass", hidden=False)
    return {"guest_id": str(g.id), "guest_name": g.full_name, "company": g.company, "location": g.location.name,
            "ssid": g.location.ssid, "access_url": url, "access_code": f"{code[:4]}-{code[4:]}",
            "qr_svg": _qr(url), "wifi_qr_svg": wifi.svg_data_uri(scale=6, border=2),
            "duration_hours": g.duration_hours, "visit_date": g.visit_date.isoformat(),
            "redeem_before": iso(ap.redeem_before), "redeemed": ap.redeemed_at is not None,
            "status": g.status.value}


def pass_available(g: Guest) -> AccessPass | None:
    ap = current_pass(g)
    if ap and g.status in (GuestStatus.approved, GuestStatus.active):
        return ap
    return None
