"""Guest-facing portal (server-rendered, works inside iOS/Android captive-portal mini browsers).

Flow A (QR):   scan QR -> GET /q/<token> -> accept terms -> POST /q/<token> (claims pass, sets cookie)
               -> browser sent to CAPTIVE_TRIGGER_URL -> FortiGate intercepts -> GET /portal?post=..&magic=..
               -> cookie found -> auto-submit one-time RADIUS credentials to FortiGate -> online.
Flow B (code): connect to SSID -> captive popup -> GET /portal?post=..&magic=.. -> enter 8-char code + accept
               terms -> POST /portal/code -> auto-submit credentials to FortiGate -> online.
"""
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..access import PassError, check_pass_usable, find_pass_by_claim, find_pass_by_code, find_pass_by_token, redeem
from ..config import get_settings
from ..db import get_db
from ..models import AccessPass, AuthEvent, Location
from ..security import client_ip, consteq, new_token, normalize_code, utcnow
from .admin import portal_texts

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))
CLAIM_COOKIE = "bgw_claim"
CSRF_COOKIE = "bgw_gcsrf"
MAX_FAILS_PER_IP = 10  # per 15 minutes


def _csp(form_origin: str | None = None) -> str:
    fa = "'self'" + (f" {form_origin}" if form_origin else "")
    return ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
            f"form-action {fa}; frame-ancestors 'none'; base-uri 'none'")


def _render(request: Request, name: str, ctx: dict, status: int = 200, csrf: str | None = None,
            form_origin: str | None = None) -> HTMLResponse:
    ctx = {"request": request, "csrf": csrf, **ctx}
    resp = templates.TemplateResponse(request, name, ctx, status_code=status)
    resp.headers["Content-Security-Policy"] = _csp(form_origin)
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["Referrer-Policy"] = "no-referrer"  # never leak the QR token
    if csrf:
        resp.set_cookie(CSRF_COOKIE, csrf, httponly=True, secure=get_settings().secure_cookies, samesite="lax",
                        path="/")
    return resp


def _error(request: Request, message: str, status: int = 400) -> HTMLResponse:
    return _render(request, "error.html", {"message": message}, status)


def _check_csrf(request: Request, form_value: str) -> bool:
    return bool(form_value) and consteq(form_value, request.cookies.get(CSRF_COOKIE, ""))


def _too_many_failures(db: Session, ip: str) -> bool:
    since = utcnow() - timedelta(minutes=15)
    n = db.scalar(select(func.count(AuthEvent.id)).where(AuthEvent.source == "portal", AuthEvent.result == "reject",
                                                          AuthEvent.client_ip == ip, AuthEvent.ts >= since))
    return (n or 0) >= MAX_FAILS_PER_IP


def _log(db: Session, result: str, reason: str, request: Request, ap: AccessPass | None = None):
    db.add(AuthEvent(source="portal", result=result, reason=reason, client_ip=client_ip(request),
                     guest_id=ap.guest_id if ap else None, location_id=ap.guest.location_id if ap else None,
                     username=ap.radius_username if ap else None))
    db.commit()


def _validate_post_url(db: Session, post: str) -> tuple[Location, str] | None:
    """Only post credentials back to a configured FortiGate guest-interface address (no open redirect)."""
    try:
        u = urlsplit(post)
    except ValueError:
        return None
    if u.scheme not in ("http", "https") or not u.netloc or u.username or u.password:
        return None
    for loc in db.scalars(select(Location).where(Location.enabled.is_(True))):
        if u.netloc.lower() in [h.lower() for h in (loc.portal_post_hosts or [])]:
            return loc, f"{u.scheme}://{u.netloc}"
    return None


def _set_claim(resp, claim: str):
    resp.set_cookie(CLAIM_COOKIE, claim, httponly=True, secure=get_settings().secure_cookies, samesite="lax",
                    path="/", max_age=13 * 3600)


def _autosubmit(request: Request, db: Session, ap: AccessPass, claim: str, username: str, password: str,
                post: str, magic: str) -> HTMLResponse:
    checked = _validate_post_url(db, post)
    if not checked:
        return _error(request, "This sign-in page was not opened from the Bessel Systems guest network.")
    loc, origin = checked
    if loc.id != ap.guest.location_id:
        return _error(request, f"This pass is valid at {ap.guest.location.name} only.", 403)
    redirect_after = f"{get_settings().guest_base_url.rstrip('/')}/portal/status"
    resp = _render(request, "autosubmit.html", {"post": post, "magic": magic, "username": username,
                                                "password": password, "redir": redirect_after},
                   form_origin=origin)
    _set_claim(resp, claim)
    return resp


# ---------------- Flow A: QR link ----------------
@router.get("/q/{token}", response_class=HTMLResponse)
def qr_landing(token: str, request: Request, db: Session = Depends(get_db)):
    # GET never redeems: link previews / scanners must not consume a single-use pass.
    ap = find_pass_by_token(db, token)
    try:
        check_pass_usable(ap)
    except PassError as e:
        _log(db, "reject", e.code, request, ap)
        return _error(request, e.message, 403)
    terms, privacy = portal_texts(db)
    return _render(request, "landing.html", {"first_name": ap.guest.full_name.split()[0], "ssid": ap.guest.location.ssid,
                                             "location": ap.guest.location.name, "hours": ap.guest.duration_hours,
                                             "token": token, "already": ap.redeemed_at is not None},
                   csrf=new_token(16))


@router.post("/q/{token}", response_class=HTMLResponse)
def qr_claim(token: str, request: Request, csrf: str = Form(""), accept: str = Form(""),
             db: Session = Depends(get_db)):
    if not _check_csrf(request, csrf):
        return _error(request, "Your session expired. Please scan the QR code again.")
    if accept != "yes":
        return _error(request, "You must accept the terms of use to continue.")
    ip = client_ip(request)
    if _too_many_failures(db, ip):
        return _error(request, "Too many attempts. Please wait 15 minutes or contact reception.", 429)
    ap = find_pass_by_token(db, token)
    try:
        if ap is None:
            raise PassError("unknown_token", "This QR code is not valid.")
        claim, _, _ = redeem(db, ap, request.cookies.get(CLAIM_COOKIE), ip)
    except PassError as e:
        db.rollback()
        _log(db, "reject", e.code, request, ap)
        return _error(request, e.message, 403)
    db.commit()
    _log(db, "accept", "qr_claimed", request, ap)
    resp = _render(request, "connect.html", {"trigger": get_settings().captive_trigger_url,
                                             "ssid": ap.guest.location.ssid})
    _set_claim(resp, claim)
    return resp


# ---------------- FortiGate external captive portal landing ----------------
@router.get("/portal", response_class=HTMLResponse)
def portal(request: Request, post: str = "", magic: str = "", db: Session = Depends(get_db)):
    if not post or not magic:
        return RedirectResponse("/portal/status", status_code=303)
    if not _validate_post_url(db, post):
        return _error(request, "This sign-in page was not opened from the Bessel Systems guest network.")
    ap = find_pass_by_claim(db, request.cookies.get(CLAIM_COOKIE))
    if ap:
        try:
            claim, user, pw = redeem(db, ap, request.cookies.get(CLAIM_COOKIE), client_ip(request))
            db.commit()
            return _autosubmit(request, db, ap, claim, user, pw, post, magic)
        except PassError:
            db.rollback()  # fall through to code entry
    terms, privacy = portal_texts(db)
    return _render(request, "code.html", {"post": post, "magic": magic, "error": None}, csrf=new_token(16))


@router.post("/portal/code", response_class=HTMLResponse)
def portal_code(request: Request, code: str = Form(""), post: str = Form(""), magic: str = Form(""),
                csrf: str = Form(""), accept: str = Form(""), db: Session = Depends(get_db)):
    def again(msg: str, status: int = 400):
        return _render(request, "code.html", {"post": post, "magic": magic, "error": msg}, status=status,
                       csrf=new_token(16))

    if not _check_csrf(request, csrf):
        return again("Your session expired. Please try again.")
    if accept != "yes":
        return again("You must accept the terms of use to continue.")
    ip = client_ip(request)
    if _too_many_failures(db, ip):
        return again("Too many attempts. Please wait 15 minutes or contact reception.", 429)
    ap = find_pass_by_code(db, normalize_code(code))
    try:
        if ap is None:
            raise PassError("bad_code", "That access code is not valid. Check it and try again.")
        claim, user, pw = redeem(db, ap, request.cookies.get(CLAIM_COOKIE), ip)
    except PassError as e:
        db.rollback()
        _log(db, "reject", e.code, request, ap)
        return again(e.message, 403)
    db.commit()
    _log(db, "accept", "code_redeemed", request, ap)
    return _autosubmit(request, db, ap, claim, user, pw, post, magic)


# ---------------- status / static texts ----------------
@router.get("/portal/status", response_class=HTMLResponse)
def portal_status(request: Request, db: Session = Depends(get_db)):
    ap = find_pass_by_claim(db, request.cookies.get(CLAIM_COOKIE))
    ctx = {"ap": None}
    if ap:
        g = ap.guest
        tz = ZoneInfo(g.location.timezone)
        state, message = "connected", None
        try:
            check_pass_usable(ap)
            if not ap.access_started_at:
                state = "pending"
        except PassError as e:
            state, message = "ended", e.message
        remaining = int((ap.access_expires_at - utcnow()).total_seconds() // 60) if ap.access_expires_at else None
        ctx = {"ap": ap, "first_name": g.full_name.split()[0], "location": g.location.name, "ssid": g.location.ssid,
               "state": state, "message": message,
               "expires": ap.access_expires_at.astimezone(tz).strftime("%d %b %Y, %I:%M %p") if ap.access_expires_at else None,
               "remaining": max(remaining, 0) if remaining is not None else None, "hours": g.duration_hours}
    return _render(request, "status.html", ctx)


@router.get("/portal/terms", response_class=HTMLResponse)
def terms(request: Request, db: Session = Depends(get_db)):
    t, _ = portal_texts(db)
    return _render(request, "text.html", {"title": "Terms of use", "text": t})


@router.get("/portal/privacy", response_class=HTMLResponse)
def privacy(request: Request, db: Session = Depends(get_db)):
    _, p = portal_texts(db)
    return _render(request, "text.html", {"title": "Privacy notice", "text": p})
