"""Password hashing, token generation, encryption at rest, admin session handling and RBAC dependencies."""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import AdminSession, AuditLog, Role, User

SESSION_COOKIE = "bgw_admin"
_ph = PasswordHasher()  # argon2id defaults (RFC 9106 recommended params)

# Characters for human-typed access codes: no 0/O/1/I/L to avoid confusion.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------- hashing / tokens ----------
def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, pw)
    except (VerifyMismatchError, InvalidHashError):
        return False


_DUMMY_HASH = _ph.hash(secrets.token_urlsafe(16))


def dummy_verify() -> None:
    """Burn the same time as a real verify so unknown usernames are not distinguishable by timing."""
    verify_password("x", _DUMMY_HASH)


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def new_access_code(length: int = 8) -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(length))


def normalize_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def consteq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def password_policy_error(pw: str) -> str | None:
    if len(pw) < 12:
        return "Password must be at least 12 characters."
    classes = sum([any(c.islower() for c in pw), any(c.isupper() for c in pw), any(c.isdigit() for c in pw),
                   any(not c.isalnum() for c in pw)])
    if classes < 3:
        return "Password must contain at least three of: lowercase, uppercase, digit, symbol."
    return None


# ---------- encryption at rest ----------
def _fernet() -> Fernet:
    return Fernet(get_settings().data_encryption_key.encode())


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:  # key rotated / tampered
        raise RuntimeError("Unable to decrypt stored secret - check DATA_ENCRYPTION_KEY") from exc


# ---------- request helpers ----------
def client_ip(request: Request) -> str:
    # nginx sets X-Real-IP; backend is only reachable through nginx on the internal docker network
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "")


def audit(db: Session, request: Request | None, user: User | None, action: str, entity_type: str | None = None,
          entity_id: str | None = None, location_id: int | None = None, **details) -> None:
    db.add(AuditLog(user_id=user.id if user else None, username=user.username if user else None, action=action,
                    entity_type=entity_type, entity_id=entity_id, location_id=location_id,
                    ip=client_ip(request) if request else None, details=details))


# ---------- admin sessions ----------
def create_session(db: Session, user: User, request: Request, stage: str = "full") -> tuple[str, AdminSession]:
    s = get_settings()
    token = new_token()
    sess = AdminSession(token_hash=sha256(token), csrf_token=new_token(24), user_id=user.id, stage=stage,
                        expires_at=utcnow() + timedelta(hours=s.session_absolute_hours), ip=client_ip(request),
                        user_agent=(request.headers.get("user-agent") or "")[:255])
    db.add(sess)
    return token, sess


def _load_session(request: Request, db: Session) -> AdminSession:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    sess = db.scalar(select(AdminSession).where(AdminSession.token_hash == sha256(token)))
    now = utcnow()
    idle = timedelta(minutes=get_settings().session_idle_minutes)
    if not sess or sess.expires_at < now or sess.last_seen_at + idle < now or not sess.user.is_active:
        if sess:
            db.delete(sess)
            db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
    # CSRF: every state-changing request must echo the per-session token in a header
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        sent = request.headers.get("x-csrf-token", "")
        if not consteq(sent, sess.csrf_token):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF token missing or invalid")
    sess.last_seen_at = now
    db.commit()
    return sess


def get_session_any_stage(request: Request, db: Session = Depends(get_db)) -> AdminSession:
    return _load_session(request, db)


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    sess = _load_session(request, db)
    if sess.stage != "full":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "MFA enrolment / password change required")
    request.state.session = sess
    return sess.user


def require_roles(*roles: Role):
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
        return user

    return dep


def location_scope(user: User) -> int | None:
    """None = all locations. Reception users are pinned to their own site."""
    if user.role == Role.reception:
        if user.location_id is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Reception account has no location assigned")
        return user.location_id
    return None


def assert_location(user: User, location_id: int) -> None:
    scope = location_scope(user)
    if scope is not None and scope != location_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted for this location")
