from datetime import timedelta

import pyotp
import segno
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import AdminSession, AuthEvent, MfaTicket, User
from ..schemas import CodeIn, LoginIn, MfaIn, PasswordChangeIn
from ..security import (SESSION_COOKIE, audit, client_ip, create_session, decrypt, dummy_verify, encrypt,
                        get_session_any_stage, hash_password, new_token, password_policy_error, sha256, utcnow,
                        verify_password)
from ..serialize import user_out

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _needs(user: User) -> list[str]:
    needs = []
    if user.must_change_password:
        needs.append("password")
    if get_settings().mfa_enforced and not user.mfa_enabled:
        needs.append("mfa")
    return needs


def _start_session(db: Session, user: User, request: Request, response: Response) -> dict:
    needs = _needs(user)
    token, sess = create_session(db, user, request, stage="full" if not needs else "setup")
    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = utcnow()
    audit(db, request, user, "auth.login", "user", str(user.id))
    db.commit()
    s = get_settings()
    response.set_cookie(SESSION_COOKIE, token, httponly=True, secure=s.secure_cookies, samesite="strict",
                        path="/api", max_age=s.session_absolute_hours * 3600)
    return {"stage": sess.stage, "needs": needs, "csrf_token": sess.csrf_token, "user": user_out(user)}


def _fail(db: Session, request: Request, user: User | None, username: str, reason: str):
    s = get_settings()
    if user:
        user.failed_logins += 1
        if user.failed_logins >= s.max_failed_logins:
            user.locked_until = utcnow() + timedelta(minutes=s.lockout_minutes)
            audit(db, request, user, "auth.locked", "user", str(user.id))
    db.add(AuthEvent(source="admin-login", result="reject", reason=reason, username=username[:64],
                     client_ip=client_ip(request)))
    db.commit()
    raise HTTPException(401, "Invalid username, password or code")


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == body.username.strip().lower()))
    if not user:
        dummy_verify()
        _fail(db, request, None, body.username, "unknown_user")
    if user.locked_until and user.locked_until > utcnow():
        raise HTTPException(423, "Account temporarily locked. Try again later or contact an administrator.")
    if not user.is_active or not verify_password(body.password, user.password_hash):
        _fail(db, request, user, body.username, "bad_password" if user.is_active else "inactive")
    if user.mfa_enabled:
        ticket = new_token()
        db.add(MfaTicket(token_hash=sha256(ticket), user_id=user.id, expires_at=utcnow() + timedelta(minutes=5)))
        db.commit()
        return {"mfa_required": True, "ticket": ticket}
    return _start_session(db, user, request, response)


@router.post("/mfa")
def login_mfa(body: MfaIn, request: Request, response: Response, db: Session = Depends(get_db)):
    t = db.get(MfaTicket, sha256(body.ticket))
    if not t or t.expires_at < utcnow() or t.attempts >= 5:
        raise HTTPException(401, "Login expired, please sign in again")
    user = db.get(User, t.user_id)
    totp = pyotp.TOTP(decrypt(user.mfa_secret_enc or ""))
    if not totp.verify(body.code.strip(), valid_window=1):
        t.attempts += 1
        db.commit()
        _fail(db, request, user, user.username, "bad_totp")
    db.delete(t)
    return _start_session(db, user, request, response)


@router.get("/me")
def me(sess: AdminSession = Depends(get_session_any_stage)):
    return {"stage": sess.stage, "needs": _needs(sess.user), "csrf_token": sess.csrf_token,
            "user": user_out(sess.user), "idle_minutes": get_settings().session_idle_minutes}


def _maybe_upgrade(db: Session, sess: AdminSession):
    if not _needs(sess.user):
        sess.stage = "full"


@router.post("/mfa/setup")
def mfa_setup(request: Request, sess: AdminSession = Depends(get_session_any_stage), db: Session = Depends(get_db)):
    user = sess.user
    if user.mfa_enabled:
        raise HTTPException(400, "MFA already enabled. Ask a Super Administrator to reset it.")
    secret = pyotp.random_base32()
    user.mfa_secret_enc = encrypt(secret)
    db.commit()
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.username, issuer_name="Bessel Guest WiFi")
    return {"secret": secret, "otpauth_uri": uri, "qr_svg": segno.make(uri, error="m").svg_data_uri(scale=5)}


@router.post("/mfa/confirm")
def mfa_confirm(body: CodeIn, request: Request, sess: AdminSession = Depends(get_session_any_stage),
                db: Session = Depends(get_db)):
    user = sess.user
    if not user.mfa_secret_enc or user.mfa_enabled:
        raise HTTPException(400, "Start MFA setup first")
    if not pyotp.TOTP(decrypt(user.mfa_secret_enc)).verify(body.code.strip(), valid_window=1):
        raise HTTPException(400, "Code did not match. Check your authenticator app time and try again.")
    user.mfa_enabled = True
    audit(db, request, user, "auth.mfa_enabled", "user", str(user.id))
    _maybe_upgrade(db, sess)
    db.commit()
    return {"stage": sess.stage, "needs": _needs(user)}


@router.post("/password")
def change_password(body: PasswordChangeIn, request: Request, sess: AdminSession = Depends(get_session_any_stage),
                    db: Session = Depends(get_db)):
    user = sess.user
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    err = password_policy_error(body.new_password)
    if err:
        raise HTTPException(400, err)
    if verify_password(body.new_password, user.password_hash):
        raise HTTPException(400, "New password must differ from the current one")
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    # sign out every other session of this user
    for other in db.scalars(select(AdminSession).where(AdminSession.user_id == user.id, AdminSession.id != sess.id)):
        db.delete(other)
    audit(db, request, user, "auth.password_changed", "user", str(user.id))
    _maybe_upgrade(db, sess)
    db.commit()
    return {"stage": sess.stage, "needs": _needs(user)}


@router.post("/logout")
def logout(request: Request, response: Response, sess: AdminSession = Depends(get_session_any_stage),
           db: Session = Depends(get_db)):
    audit(db, request, sess.user, "auth.logout", "user", str(sess.user_id))
    db.delete(sess)
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/api")
    return {"ok": True}
