"""Super Administrator: user management, location / firewall integration settings, portal texts."""
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AdminSession, Location, Role, Setting, User
from ..schemas import LocationPatch, SettingsIn, UserIn, UserPatch
from ..security import audit, hash_password, require_roles
from ..serialize import location_out, user_out

router = APIRouter(prefix="/api/admin", tags=["admin"])
SUPER = require_roles(Role.super_admin)

DEFAULT_TERMS = """By using Bessel Systems Guest Wi-Fi you agree to:
1. Use the service only for lawful purposes and in line with Bessel Systems policies.
2. Not attempt to access internal Bessel Systems systems, other guests' devices or network equipment.
3. Not download, store or distribute illegal, offensive or copyrighted material.
4. Accept that access is time-limited, may be monitored and logged, and may be revoked at any time.
5. Accept that the service is provided "as is" without any guarantee of availability or security.
Use a VPN or HTTPS for sensitive work. Bessel Systems is not responsible for loss of data on your device."""

DEFAULT_PRIVACY = """Bessel Systems collects your name, company, mobile number, optional e-mail, host, purpose of visit,
and technical connection data (device IP/MAC address, connection times, data volume) to provide guest internet
access, ensure security and meet legal record-keeping obligations. The data is stored on Bessel Systems servers
in India, accessible only to authorised reception, IT and security staff, and is not sold or shared with third
parties except where required by law. Personal details are anonymised after the configured retention period.
To request access to or correction of your data, contact reception or the IT department."""


def get_setting(db: Session, key: str, default: str = "") -> str:
    s = db.get(Setting, key)
    return s.value if s else default


def portal_texts(db: Session) -> tuple[str, str]:
    return get_setting(db, "terms_text", DEFAULT_TERMS), get_setting(db, "privacy_text", DEFAULT_PRIVACY)


def _validate_role_location(db: Session, role: Role, location_id: int | None) -> None:
    if role == Role.reception:
        if not location_id or not db.get(Location, location_id):
            raise HTTPException(400, "Reception accounts must be assigned to a location")


def _temp_password() -> str:
    return "Tmp-" + secrets.token_urlsafe(12) + "9a"


@router.get("/users")
def list_users(user: User = Depends(SUPER), db: Session = Depends(get_db)):
    return [user_out(u) for u in db.scalars(select(User).order_by(User.username))]


@router.post("/users", status_code=201)
def create_user(body: UserIn, request: Request, user: User = Depends(SUPER), db: Session = Depends(get_db)):
    username = body.username.lower()
    if db.scalar(select(User).where(User.username == username)):
        raise HTTPException(409, "Username already exists")
    _validate_role_location(db, body.role, body.location_id)
    temp = _temp_password()
    u = User(username=username, full_name=body.full_name, email=body.email, role=body.role,
             location_id=body.location_id if body.role == Role.reception else None,
             password_hash=hash_password(temp), must_change_password=True)
    db.add(u)
    db.flush()
    audit(db, request, user, "user.created", "user", str(u.id), role=body.role.value, username=username)
    db.commit()
    db.refresh(u)
    return {"user": user_out(u), "temporary_password": temp}


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserPatch, request: Request, user: User = Depends(SUPER),
                db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    data = body.model_dump(exclude_unset=True)
    if u.id == user.id and (data.get("is_active") is False or data.get("role", Role.super_admin) != Role.super_admin):
        raise HTTPException(400, "You cannot deactivate or demote your own account")
    role = data.get("role", u.role)
    loc = data.get("location_id", u.location_id)
    _validate_role_location(db, role, loc)
    for k, v in data.items():
        setattr(u, k, v)
    if role != Role.reception:
        u.location_id = None
    if data.get("is_active") is False or "role" in data or "location_id" in data:
        for s in db.scalars(select(AdminSession).where(AdminSession.user_id == u.id)):
            db.delete(s)  # force re-login with new privileges
    audit(db, request, user, "user.updated", "user", str(u.id), changes={k: str(v) for k, v in data.items()})
    db.commit()
    return user_out(u)


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: int, request: Request, user: User = Depends(SUPER), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    temp = _temp_password()
    u.password_hash = hash_password(temp)
    u.must_change_password = True
    u.failed_logins = 0
    u.locked_until = None
    for s in db.scalars(select(AdminSession).where(AdminSession.user_id == u.id)):
        db.delete(s)
    audit(db, request, user, "user.password_reset", "user", str(u.id))
    db.commit()
    return {"temporary_password": temp}


@router.post("/users/{user_id}/reset-mfa")
def reset_mfa(user_id: int, request: Request, user: User = Depends(SUPER), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    u.mfa_enabled = False
    u.mfa_secret_enc = None
    for s in db.scalars(select(AdminSession).where(AdminSession.user_id == u.id)):
        db.delete(s)
    audit(db, request, user, "user.mfa_reset", "user", str(u.id))
    db.commit()
    return user_out(u)


@router.post("/users/{user_id}/unlock")
def unlock(user_id: int, request: Request, user: User = Depends(SUPER), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    u.failed_logins = 0
    u.locked_until = None
    audit(db, request, user, "user.unlocked", "user", str(u.id))
    db.commit()
    return user_out(u)


@router.get("/locations")
def list_locations(user: User = Depends(SUPER), db: Session = Depends(get_db)):
    return [location_out(l, full=True) for l in db.scalars(select(Location).order_by(Location.id))]


@router.patch("/locations/{location_id}")
def update_location(location_id: int, body: LocationPatch, request: Request, user: User = Depends(SUPER),
                    db: Session = Depends(get_db)):
    loc = db.get(Location, location_id)
    if not loc:
        raise HTTPException(404, "Location not found")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(loc, k, v)
    audit(db, request, user, "location.updated", "location", str(loc.id), loc.id,
          changes={k: str(v) for k, v in data.items()})
    db.commit()
    return location_out(loc, full=True)


@router.get("/settings")
def get_settings_texts(user: User = Depends(SUPER), db: Session = Depends(get_db)):
    terms, privacy = portal_texts(db)
    return {"terms_text": terms, "privacy_text": privacy}


@router.put("/settings")
def put_settings(body: SettingsIn, request: Request, user: User = Depends(SUPER), db: Session = Depends(get_db)):
    for key, val in body.model_dump(exclude_none=True).items():
        s = db.get(Setting, key)
        if s:
            s.value = val
        else:
            db.add(Setting(key=key, value=val))
    audit(db, request, user, "settings.updated", "settings", None, keys=list(body.model_dump(exclude_none=True)))
    db.commit()
    terms, privacy = portal_texts(db)
    return {"terms_text": terms, "privacy_text": privacy}
