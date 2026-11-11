import logging
import smtplib
import uuid
from datetime import date, datetime, time
from email.message import EmailMessage
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from ..access import issue_pass, mark_disconnected, revoke
from ..coa import send_disconnect
from ..config import get_settings
from ..db import get_db
from ..models import AuthEvent, Guest, GuestStatus, Location, PendingDisconnect, RadiusSession, Role, User
from ..schemas import GuestIn, ReasonIn
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
                approval: str | None = None) -> Select:
    stmt = select(Guest)
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
                approval: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200),
                user: User = Depends(require_roles(*ANY)), db: Session = Depends(get_db)):
    try:
        stmt = guest_query(user, location_id, status, q, mobile, date_from, date_to, approval)
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
    return out


@router.post("/guests/{guest_id}/approve")
def approve(guest_id: str, request: Request, user: User = Depends(require_roles(*STAFF)),
            db: Session = Depends(get_db)):
    g = _get_guest(db, guest_id, user)
    if g.status != GuestStatus.pending:
        raise HTTPException(409, f"Guest is {g.status.value}, not pending")
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
    if not ap or ap.redeemed_at:
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
