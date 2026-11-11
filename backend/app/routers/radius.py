"""Internal endpoints called only by the FreeRADIUS container (rlm_rest). Never exposed through nginx.

Authentication flow: FortiGate captive portal -> RADIUS Access-Request (PAP) -> FreeRADIUS -> POST here.
On accept we return Session-Timeout (remaining seconds) so the FortiGate itself enforces expiry, plus
Fortinet-Group-Name so the FortiGate firewall user group matches.
"""
import base64
import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..access import PassError, check_pass_usable
from ..config import get_settings
from ..db import get_db
from ..models import (AccessPass, AuthEvent, GuestStatus, Location, PendingDisconnect, RadiusSession)
from ..security import consteq, sha256, utcnow

log = logging.getLogger(__name__)
router = APIRouter(prefix="/internal/radius", include_in_schema=False)


def _check_key(authorization: str = Header(""), x_radius_key: str = Header("")):
    """X-Radius-Key header (authenticate) or HTTP Basic user 'radius' / RADIUS_API_KEY (accounting)."""
    key = x_radius_key
    if not key and authorization.lower().startswith("basic "):
        try:
            user, _, key = base64.b64decode(authorization[6:]).decode().partition(":")
        except (ValueError, UnicodeDecodeError):
            key = ""
    if not key or not consteq(key, get_settings().radius_api_key):
        raise HTTPException(401, "unauthorized", headers={"WWW-Authenticate": "Basic"})


def _attrs(body: dict) -> dict[str, str]:
    """Flatten rlm_rest JSON ({"User-Name": {"type": "string", "value": ["x"]}}) into {name: first value}."""
    out = {}
    for k, v in (body or {}).items():
        if isinstance(v, dict):
            v = v.get("value")
        if isinstance(v, list):
            v = v[0] if v else None
        if v is not None:
            out[k] = str(v)
    return out


def _mac(v: str | None) -> str | None:
    if not v:
        return None
    hexd = "".join(c for c in v.lower() if c in "0123456789abcdef")
    if len(hexd) == 12:
        return ":".join(hexd[i:i + 2] for i in range(0, 12, 2))
    return v[:64]


def _nas(db: Session, a: dict) -> Location | None:
    short = a.get("Tmp-String-0") or a.get("NAS-Identifier")
    if not short:
        return None
    loc = db.scalar(select(Location).where(Location.nas_shortname == short))
    if loc:
        loc.last_radius_seen_at = utcnow()
    return loc


def _reject(db: Session, reason: str, a: dict, loc: Location | None, ap: AccessPass | None, msg: str) -> JSONResponse:
    db.add(AuthEvent(source="radius", result="reject", reason=reason, username=a.get("User-Name", "")[:64],
                     guest_id=ap.guest_id if ap else None, location_id=loc.id if loc else None,
                     client_ip=a.get("Framed-IP-Address"), client_mac=_mac(a.get("Calling-Station-Id")),
                     nas_shortname=a.get("Tmp-String-0")))
    db.commit()
    log.info("RADIUS reject user=%s reason=%s", a.get("User-Name"), reason)
    return JSONResponse({"reply:Reply-Message": msg}, status_code=401)


@router.post("/authenticate", dependencies=[Depends(_check_key)])
async def authenticate(request: Request, db: Session = Depends(get_db)):
    a = _attrs(await request.json())
    username = (a.get("User-Name") or "").strip().lower()
    password = a.get("User-Password") or ""
    loc = _nas(db, a)
    if not loc:
        return _reject(db, "unknown_nas", a, None, None, "Unknown NAS")
    ap = db.scalar(select(AccessPass).where(AccessPass.radius_username == username)) if username else None
    if not ap or not ap.radius_password_hash or not consteq(sha256(password), ap.radius_password_hash):
        return _reject(db, "bad_credentials", a, loc, ap, "Invalid credentials")
    g = ap.guest
    if g.location_id != loc.id:
        return _reject(db, "wrong_location", a, loc, ap, "Pass not valid at this office")
    try:
        check_pass_usable(ap)
    except PassError as e:
        return _reject(db, e.code, a, loc, ap, e.message)

    device = _mac(a.get("Calling-Station-Id")) or a.get("Framed-IP-Address")
    if ap.bound_device and device and device != ap.bound_device:
        return _reject(db, "device_mismatch", a, loc, ap, "Pass already in use on another device")

    now = utcnow()
    if ap.access_started_at is None:
        ap.access_started_at = now
        ap.access_expires_at = now + timedelta(hours=g.duration_hours)
        g.status = GuestStatus.active
    if device and not ap.bound_device:
        ap.bound_device = device
    remaining = int((ap.access_expires_at - now).total_seconds())
    if remaining <= 0:
        return _reject(db, "expired", a, loc, ap, "Access expired")
    db.add(AuthEvent(source="radius", result="accept", reason="ok", username=username, guest_id=g.id,
                     location_id=loc.id, client_ip=a.get("Framed-IP-Address"),
                     client_mac=_mac(a.get("Calling-Station-Id")), nas_shortname=loc.nas_shortname))
    db.commit()
    return {"reply:Session-Timeout": remaining, "reply:Fortinet-Group-Name": get_settings().radius_group_name,
            "reply:Acct-Interim-Interval": 300}


def _octets(a: dict, prefix: str) -> int:
    return int(a.get(f"Acct-{prefix}-Gigawords", 0) or 0) * (2 ** 32) + int(a.get(f"Acct-{prefix}-Octets", 0) or 0)


@router.post("/accounting", dependencies=[Depends(_check_key)])
async def accounting(request: Request, db: Session = Depends(get_db)):
    a = _attrs(await request.json())
    loc = _nas(db, a)
    st = a.get("Acct-Status-Type", "")
    now = utcnow()
    short = loc.nas_shortname if loc else a.get("Tmp-String-0")

    if st in ("Accounting-On", "Accounting-Off", "7", "8"):  # NAS rebooted - every session on it is gone
        for rs in db.scalars(select(RadiusSession).where(RadiusSession.nas_shortname == short,
                                                         RadiusSession.stopped_at.is_(None))):
            rs.stopped_at = now
            rs.terminate_cause = "NAS-Reboot"
        db.commit()
        return Response(status_code=204)

    username = (a.get("User-Name") or "").strip().lower()
    sid = a.get("Acct-Session-Id") or ""
    if not username or not sid:
        db.commit()
        return Response(status_code=204)
    rs = db.scalar(select(RadiusSession).where(RadiusSession.nas_shortname == short,
                                               RadiusSession.acct_session_id == sid,
                                               RadiusSession.username == username))
    ap = db.scalar(select(AccessPass).where(AccessPass.radius_username == username))
    if rs is None:
        rs = RadiusSession(username=username, acct_session_id=sid, nas_shortname=short,
                           location_id=loc.id if loc else None, pass_id=ap.id if ap else None,
                           guest_id=ap.guest_id if ap else None, started_at=now)
        db.add(rs)
    rs.last_update_at = now
    rs.client_ip = a.get("Framed-IP-Address") or rs.client_ip
    rs.client_mac = _mac(a.get("Calling-Station-Id")) or rs.client_mac
    if "Acct-Input-Octets" in a:
        rs.input_octets = _octets(a, "Input")
        rs.output_octets = _octets(a, "Output")
    if "Acct-Session-Time" in a:
        rs.session_time = int(a["Acct-Session-Time"])
    if st in ("Stop", "2"):
        rs.stopped_at = now
        rs.terminate_cause = a.get("Acct-Terminate-Cause", "")[:64]
    elif ap and loc and rs.stopped_at is None:
        # Enforcement backstop: traffic for a pass that is no longer valid -> disconnect it
        g = ap.guest
        if g.status in (GuestStatus.revoked, GuestStatus.expired) or (ap.access_expires_at and ap.access_expires_at < now):
            pending = db.scalar(select(PendingDisconnect).where(PendingDisconnect.username == username,
                                                                PendingDisconnect.done.is_(False)))
            if not pending:
                db.add(PendingDisconnect(location_id=loc.id, username=username, acct_session_id=sid,
                                         client_ip=rs.client_ip))
    db.commit()
    return Response(status_code=204)
