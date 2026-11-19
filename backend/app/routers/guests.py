import logging
import smtplib
import uuid
from datetime import date, datetime, time, timedelta
from email.message import EmailMessage
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from ..access import issue_pass, mark_disconnected, queue_disconnects, revoke
from ..coa import send_disconnect
from ..config import get_settings
from ..db import get_db
from ..models import (AuthEvent, Guest, GuestStatus, Location, PassDevice, PendingDisconnect, RadiusSession, Role,
                      User)
from ..schemas import ApproveIn, GuestIn, PermanentIn, ReasonIn
from ..security import assert_location, audit, current_user, location_scope, require_roles, utcnow
from ..serialize import guest_out, iso, location_out, pass_available, pass_payload, session_out

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["guests"])
STAFF = (Role.super_admin, Role.reception)
ANY = (Role.super_admin, Role.reception, Role.auditor)


@router.get("/meta")
def meta(user: User = Depends(current_user), db: Session = Depends(get_db)):
    scope = location_scope(user)
    q = select(Location).where(Location.enabled.is_(True)).order_by(Location.id)
    if scope is not None:
        q = q.where(Location.id == scope)
    return {"locations": [location_out(loc) for loc in db.scalars(q)], "durations": get_settings().durations,
            "statuses": [s.value for s in GuestStatus]}


def _get_guest(db: Session, guest_id: str, user: User) -> Guest:
    try:
        gid = uuid.UUID(guest_id)
    except ValueError:
        raise HTTPException(404, "Guest not found")
    g = db.get(Guest, gid)
    if not g:
        raise HTTPException(404, "Guest not found")
    assert_location(user, g.location_id)
    return g


def guest_query(user: User, location_id: int | None = None, status: str | None = None, q: str | None = None,
                mobile: str | None = None, date_from: date | None = None, date_to: date | None = None,
                approval: str | None = None, kind: str | None = None) -> Select:
    stmt = select(Guest)
    if kind in ("visitor", "permanent"):
        stmt = stmt.where(Guest.pass_kind == kind)
    scope = location_scope(user)
    if scope is not None:
        stmt = stmt.where(Guest.location_id == scope)
    elif location_id:
        stmt = stmt.where(Guest.location_id == location_id)
    if status:
        stmt = stmt.where(Guest.status.in_([GuestStatus(s) for s in status.split(",")]))
    if approval == "pending":
        stmt = stmt.where(Guest.status == GuestStatus.pending)
    elif approval == "approved":
        stmt = stmt.where(Guest.status.in_([GuestStatus.approved, GuestStatus.active, GuestStatus.expired,
                                            GuestStatus.revoked]))
    elif approval == "rejected":
        stmt = stmt.where(Guest.status == GuestStatus.rejected)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Guest.full_name.ilike(like), Guest.company.ilike(like), Guest.host_person.ilike(like)))
    if mobile:
        stmt = stmt.where(Guest.mobile.ilike(f"%{mobile.strip()}%"))
    if date_from:
        stmt = stmt.where(Guest.visit_date >= date_from)
    if date_to:
        stmt = stmt.where(Guest.visit_date <= date_to)
    return stmt


@router.get("/guests")
def list_guests(location_id: int | None = None, status: str | None = None, q: str | None = None,
                mobile: str | None = None, date_from: date | None = None, date_to: date | None = None,
                approval: str | None = None, kind: str | None = None, page: int = Query(1, ge=1),
                page_size: int = Query(25, ge=1, le=200),
                user: User = Depends(require_roles(*ANY)), db: Session = Depends(get_db)):
    try:
        stmt = guest_query(user, location_id, status, q, mobile, date_from, date_to, approval, kind)
    except ValueError:
        raise HTTPException(400, "Invalid status filter")
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(Guest.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"total": total, "page": page, "page_size": page_size, "items": [guest_out(g) for g in rows]}


DEFAULT_DURATION_HOURS = 4


@router.post("/guests", status_code=201)
def create_guest(body: GuestIn, request: Request, approve: bool = False,
                 user: User = Depends(require_roles(*STAFF)), db: Session = Depends(get_db)):
    """Register a visitor. With ?approve=true (quick pass) the same staff member also approves it and the
    pass is returned immediately; both steps are audited separately."""
    s = get_settings()
    location_id = body.location_id or location_scope(user)
    if location_id is None:  # super admin without a choice -> first enabled location
        first = db.scalar(select(Location).where(Location.enabled.is_(True)).order_by(Location.id))
        location_id = first.id if first else None
    if location_id is None:
        raise HTTPException(400, "No location available")
    assert_location(user, location_id)
    loc = db.get(Location, location_id)
    if not loc or not loc.enabled:
        raise HTTPException(400, "Unknown or disabled location")
    duration = body.duration_hours or (DEFAULT_DURATION_HOURS if DEFAULT_DURATION_HOURS in s.durations
                                        else s.durations[0])
    if duration not in s.durations:
        raise HTTPException(400, f"Duration must be one of {s.durations} hours")
    today = utcnow().astimezone(ZoneInfo(loc.timezone)).date()
    visit_date = body.visit_date or today
    if visit_date < today:
        raise HTTPException(400, "Visit date cannot be in the past")
    if approve and s.require_separate_approver:
        raise HTTPException(403, "Quick pass is disabled: a different staff member must approve requests")
    g = Guest(full_name=body.full_name, mobile=body.mobile, email=body.email,
              company=body.company or "-", host_person=body.host_person or "-",
              department=body.department or "-", purpose=body.purpose or "Visitor",
              location_id=loc.id, visit_date=visit_date, duration_hours=duration,
              status=GuestStatus.pending, created_by_id=user.id)
    db.add(g)
    db.flush()
    audit(db, request, user, "guest.registered", "guest", str(g.id), g.location_id, name=g.full_name,
          duration_hours=g.duration_hours, quick=approve)
    if approve:
        g.status = GuestStatus.approved
        g.decided_by_id = user.id
        g.decided_at = utcnow()
        ap, _, _ = issue_pass(db, g)
        audit(db, request, user, "guest.approved", "guest", str(g.id), g.location_id, quick=True)
        db.commit()
        db.refresh(g)
        return {**guest_out(g), "pass": pass_payload(g, ap)}
    db.commit()
    db.refresh(g)
    return guest_out(g)


@router.post("/permanent-codes", status_code=201)
def create_permanent(body: PermanentIn, request: Request, user: User = Depends(require_roles(Role.super_admin)),
                     db: Session = Depends(get_db)):
    """Super Administrator assigns a permanent Wi-Fi code to a named person. The code works on any number of
    devices until it is revoked, or until valid_until (inclusive) if set."""
    loc = db.get(Location, body.location_id)
    if not loc or not loc.enabled:
        raise HTTPException(400, "Unknown or disabled location")
    today = utcnow().astimezone(ZoneInfo(loc.timezone)).date()
    if body.valid_until and body.valid_until < today:
        raise HTTPException(400, "End date cannot be in the past")
    now = utcnow()
    g = Guest(full_name=body.full_name, mobile=body.mobile, email=body.email, company=body.company or "-",
              host_person="-", department=body.department or "-", purpose=body.purpose or "Permanent Wi-Fi code",
              location_id=loc.id, visit_date=today, duration_hours=0, status=GuestStatus.approved,
              pass_kind="permanent", valid_until=body.valid_until, created_by_id=user.id, decided_by_id=user.id,
              decided_at=now)
    db.add(g)
    db.flush()
    ap, _, _ = issue_pass(db, g)
    audit(db, request, user, "permanent.created", "guest", str(g.id), g.location_id, name=g.full_name,
          valid_until=body.valid_until.isoformat() if body.valid_until else None)
    db.commit()
    db.refresh(g)
    return {**guest_out(g), "pass": pass_payload(g, ap)}


@router.get("/guests/{guest_id}")
def get_guest(guest_id: str, user: User = Depends(require_roles(*ANY)), db: Session = Depends(get_db)):
    g = _get_guest(db, guest_id, user)
    sessions = db.scalars(select(RadiusSession).where(RadiusSession.guest_id == g.id)
                          .order_by(RadiusSession.started_at.desc())).all()
    events = db.scalars(select(AuthEvent).where(AuthEvent.guest_id == g.id).order_by(AuthEvent.ts.desc()).limit(50))
    out = guest_out(g)
    out["sessions"] = [session_out(s, g, g.location.code) for s in sessions]
    out["auth_events"] = [{"ts": iso(e.ts), "source": e.source, "result": e.result, "reason": e.reason,
                           "client_ip": e.client_ip} for e in events]
    out["pass_available"] = pass_available(g) is not None
    if g.pass_kind == "permanent":
        pass_ids = [p.id for p in g.passes]
        devs = db.scalars(select(PassDevice).where(PassDevice.pass_id.in_(pass_ids))
                          .order_by(PassDevice.last_used_at.desc())).all() if pass_ids else []
        out["devices"] = [{"first_used": iso(d.created_at), "last_used": iso(d.last_used_at), "ip": d.ip}
                          for d in devs]
    return out


REQUEST_WINDOW_MINUTES = 30  # keep in sync with portal.REQUEST_WAIT_MINUTES


def _request_out(g: Guest) -> dict:
    return {"id": str(g.id), "full_name": g.full_name, "mobile": g.mobile, "location_id": g.location_id,
            "location_code": g.location.code, "requested_at": iso(g.created_at), "client_ip": g.request_ip,
            "device": g.request_device, "user_agent": g.request_user_agent,
            "waiting_seconds": int((utcnow() - g.created_at).total_seconds())}


def _open_requests(user: User, db: Session):
    stmt = select(Guest).where(Guest.source == "self", Guest.status == GuestStatus.pending,
                               Guest.created_at >= utcnow() - timedelta(minutes=REQUEST_WINDOW_MINUTES))
    scope = location_scope(user)
    if scope is not None:
        stmt = stmt.where(Guest.location_id == scope)
    return db.scalars(stmt.order_by(Guest.created_at)).all()


@router.get("/requests")
def list_requests(user: User = Depends(require_roles(*STAFF)), db: Session = Depends(get_db)):
    """Guests waiting on the Wi-Fi sign-in page for approval (self-service requests)."""
    return {"items": [_request_out(g) for g in _open_requests(user, db)], "durations": get_settings().durations,
            "window_minutes": REQUEST_WINDOW_MINUTES}


@router.get("/requests/count")
def count_requests(user: User = Depends(require_roles(*STAFF)), db: Session = Depends(get_db)):
    return {"pending": len(_open_requests(user, db))}


@router.post("/guests/{guest_id}/approve")
def approve(guest_id: str, request: Request, body: ApproveIn | None = Body(default=None),
            user: User = Depends(require_roles(*STAFF)), db: Session = Depends(get_db)):
    g = _get_guest(db, guest_id, user)
    if g.status != GuestStatus.pending:
        raise HTTPException(409, f"Guest is {g.status.value}, not pending")
    if body and body.duration_hours:
        if body.duration_hours not in get_settings().durations:
            raise HTTPException(400, f"Duration must be one of {get_settings().durations} hours")
        g.duration_hours = body.duration_hours
    if get_settings().require_separate_approver and g.created_by_id == user.id:
        raise HTTPException(403, "A different staff member must approve this request")
    g.status = GuestStatus.approved
    g.decided_by_id = user.id
    g.decided_at = utcnow()
    ap, _, _ = issue_pass(db, g)
    audit(db, request, user, "guest.approved", "guest", str(g.id), g.location_id)
    db.commit()
    return pass_payload(g, ap)


@router.post("/guests/{guest_id}/reject")
def reject(guest_id: str, body: ReasonIn, request: Request, user: User = Depends(require_roles(*STAFF)),
           db: Session = Depends(get_db)):
    g = _get_guest(db, guest_id, user)
    if g.status != GuestStatus.pending:
        raise HTTPException(409, f"Guest is {g.status.value}, not pending")
    g.status = GuestStatus.rejected
    g.decided_by_id = user.id
    g.decided_at = utcnow()
    g.rejection_reason = body.reason
    audit(db, request, user, "guest.rejected", "guest", str(g.id), g.location_id, reason=body.reason)
    db.commit()
    return guest_out(g)


def _flush_disconnects(db: Session, loc: Location) -> list[str]:
    """Try queued disconnects for this site immediately; leftovers are retried by the worker."""
    results = []
    secret = get_settings().coa_secret_for(loc.code)
    for pd in db.scalars(select(PendingDisconnect).where(PendingDisconnect.location_id == loc.id,
                                                         PendingDisconnect.done.is_(False))):
        ok, msg = send_disconnect(loc.coa_host or "", loc.coa_port, secret, pd.username, pd.acct_session_id,
                                  pd.client_ip, timeout=2, retries=1)
        pd.attempts += 1
        pd.last_result = msg
        pd.done = ok
        if ok:
            mark_disconnected(db, pd)
        results.append(msg)
    return results


@router.post("/guests/{guest_id}/revoke")
def revoke_guest(guest_id: str, body: ReasonIn, request: Request, user: User = Depends(require_roles(*STAFF)),
                 db: Session = Depends(get_db)):
    g = _get_guest(db, guest_id, user)
    if g.status not in (GuestStatus.approved, GuestStatus.active):
        raise HTTPException(409, f"Guest is {g.status.value}; only approved/active access can be revoked")
    queued = revoke(db, g, user.id, body.reason)
    db.flush()
    results = _flush_disconnects(db, g.location) if queued else []
    audit(db, request, user, "guest.revoked", "guest", str(g.id), g.location_id, reason=body.reason,
          disconnects=results)
    db.commit()
    out = guest_out(g)
    out["disconnect_results"] = results
    return out


@router.post("/guests/{guest_id}/reissue")
def reissue(guest_id: str, request: Request, user: User = Depends(require_roles(*STAFF)),
            db: Session = Depends(get_db)):
    g = _get_guest(db, guest_id, user)
    if g.pass_kind == "permanent":
        if user.role != Role.super_admin:
            raise HTTPException(403, "Only a Super Administrator can change permanent codes")
        if g.status not in (GuestStatus.approved, GuestStatus.active):
            raise HTTPException(409, f"Code is {g.status.value}; create a new permanent code instead")
        # New code: the old one stops working and every device signed in with it is disconnected.
        queued = queue_disconnects(db, g)
        ap, _, _ = issue_pass(db, g)
        g.status = GuestStatus.approved
        db.flush()
        results = _flush_disconnects(db, g.location) if queued else []
        audit(db, request, user, "permanent.code_changed", "guest", str(g.id), g.location_id, disconnects=results)
        db.commit()
        return pass_payload(g, ap)
    if g.status != GuestStatus.approved:
        raise HTTPException(409, "Only approved passes that have not started can be re-issued. "
                                 "For active guests, revoke and register again.")
    ap, _, _ = issue_pass(db, g)
    audit(db, request, user, "guest.pass_reissued", "guest", str(g.id), g.location_id)
    db.commit()
    return pass_payload(g, ap)


@router.get("/guests/{guest_id}/pass")
def get_pass(guest_id: str, request: Request, user: User = Depends(require_roles(*STAFF)),
             db: Session = Depends(get_db)):
    g = _get_guest(db, guest_id, user)
    if g.pass_kind == "permanent" and user.role != Role.super_admin:
        raise HTTPException(403, "Only a Super Administrator can view permanent codes")
    ap = pass_available(g)
    if not ap:
        raise HTTPException(404, "No valid pass for this guest")
    audit(db, request, user, "guest.pass_viewed", "guest", str(g.id), g.location_id)
    db.commit()
    return pass_payload(g, ap)


@router.post("/guests/{guest_id}/pass/email")
def email_pass(guest_id: str, request: Request, user: User = Depends(require_roles(*STAFF)),
               db: Session = Depends(get_db)):
    s = get_settings()
    g = _get_guest(db, guest_id, user)
    ap = pass_available(g)
    permanent = g.pass_kind == "permanent"
    if permanent and user.role != Role.super_admin:
        raise HTTPException(403, "Only a Super Administrator can send permanent codes")
    if not ap or (ap.redeemed_at and not permanent):
        raise HTTPException(404, "No unused pass for this guest")
    if not g.email:
        raise HTTPException(400, "Guest has no e-mail address")
    if not s.smtp_host:
        raise HTTPException(400, "SMTP is not configured")
    p = pass_payload(g, ap)
    msg = EmailMessage()
    msg["Subject"] = "Bessel Systems - Guest Wi-Fi access"
    msg["From"] = s.smtp_from
    msg["To"] = g.email
    if permanent:
        until = g.valid_until.strftime("%d %b %Y") if g.valid_until else "until it is withdrawn"
        msg.set_content(
            f"Hello {g.full_name},\n\nYour personal Wi-Fi code for {g.location.name}:\n\n"
            f"    {p['access_code']}\n\n1. Connect your device to the Wi-Fi network: {p['ssid']}\n"
            "2. Open any website; on the sign-in page enter the code above and tap Connect.\n\n"
            f"The code is valid {('until ' + until) if g.valid_until else until} and works on all your devices.\n"
            "It is issued to you personally. Do not share it.\n\nBessel Systems IT")
    else:
        msg.set_content(
            f"Hello {g.full_name},\n\n1. Connect your device to the Wi-Fi network: {p['ssid']}\n"
            f"2. Open this link on the same device: {p['access_url']}\n"
            f"   or enter the access code {p['access_code']} on the sign-in page.\n\n"
            f"Access is valid for {g.duration_hours} hour(s) from first sign-in. The link must be used before "
            f"{ap.redeem_before.astimezone(ZoneInfo(g.location.timezone)).strftime('%d %b %Y %H:%M')}.\n"
            "The link works on one device only. Do not share it.\n\nBessel Systems Reception")
    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as smtp:
            smtp.starttls()
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(msg)
    except (OSError, smtplib.SMTPException) as exc:
        log.warning("SMTP send failed: %s", exc)
        raise HTTPException(502, "Could not send e-mail")
    audit(db, request, user, "guest.pass_emailed", "guest", str(g.id), g.location_id)
    db.commit()
    return {"ok": True}


@router.get("/sessions")
def list_sessions(active: bool = True, location_id: int | None = None, page: int = Query(1, ge=1),
                  page_size: int = Query(50, ge=1, le=200), user: User = Depends(require_roles(*ANY)),
                  db: Session = Depends(get_db)):
    stmt = select(RadiusSession, Guest, Location.code).outerjoin(Guest, Guest.id == RadiusSession.guest_id) \
        .outerjoin(Location, Location.id == RadiusSession.location_id)
    scope = location_scope(user)
    if scope is not None:
        stmt = stmt.where(RadiusSession.location_id == scope)
    elif location_id:
        stmt = stmt.where(RadiusSession.location_id == location_id)
    if active:
        stmt = stmt.where(RadiusSession.stopped_at.is_(None))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(stmt.order_by(RadiusSession.started_at.desc()).offset((page - 1) * page_size)
                      .limit(page_size)).all()
    return {"total": total, "items": [session_out(rs, g, code) for rs, g, code in rows]}


@router.post("/sessions/{session_id}/disconnect")
def disconnect_session(session_id: int, request: Request, user: User = Depends(require_roles(*STAFF)),
                       db: Session = Depends(get_db)):
    rs = db.get(RadiusSession, session_id)
    if not rs or rs.location_id is None:
        raise HTTPException(404, "Session not found")
    assert_location(user, rs.location_id)
    if rs.stopped_at:
        raise HTTPException(409, "Session already ended")
    db.add(PendingDisconnect(location_id=rs.location_id, username=rs.username, acct_session_id=rs.acct_session_id,
                             client_ip=rs.client_ip))
    db.flush()
    results = _flush_disconnects(db, db.get(Location, rs.location_id))
    audit(db, request, user, "session.disconnected", "radius_session", str(rs.id), rs.location_id, results=results)
    db.commit()
    return {"results": results}


def day_bounds(d: date, tz: str = "Asia/Kolkata") -> tuple[datetime, datetime]:
    z = ZoneInfo(tz)
    return datetime.combine(d, time.min, tzinfo=z), datetime.combine(d, time.max, tzinfo=z)
