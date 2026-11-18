"""Guest pass lifecycle: issue / re-issue, redemption (QR or access code), revocation, expiry."""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import AccessPass, Guest, GuestStatus, PassDevice, PendingDisconnect, RadiusSession
from .security import decrypt, encrypt, new_access_code, new_token, sha256, utcnow


class PassError(Exception):
    """User-facing redemption failure. `code` is logged, `message` is shown to the guest."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def local_today(guest: Guest):
    return utcnow().astimezone(ZoneInfo(guest.location.timezone)).date()


def _end_of_visit_day(guest: Guest) -> datetime:
    tz = ZoneInfo(guest.location.timezone)
    return datetime.combine(guest.visit_date, time(23, 59, 59), tzinfo=tz)


NEVER = datetime(2099, 12, 31, tzinfo=timezone.utc)  # "no end date" for permanent codes


def is_permanent(guest: Guest) -> bool:
    return guest.pass_kind == "permanent"


def permanent_end(guest: Guest) -> datetime | None:
    """End of the last valid day of a permanent code, or None if it runs until revoked."""
    if not guest.valid_until:
        return None
    return datetime.combine(guest.valid_until, time(23, 59, 59), tzinfo=ZoneInfo(guest.location.timezone))


def issue_pass(db: Session, guest: Guest) -> tuple[AccessPass, str, str]:
    """Create a fresh QR token + access code; any previous pass for this guest becomes invalid."""
    for p in guest.passes:
        p.valid = False
    s = get_settings()
    now = utcnow()
    if is_permanent(guest):
        token = new_token(32)
        code = new_access_code(8)
        end = permanent_end(guest)
        ap = AccessPass(guest_id=guest.id, token_hash=sha256(token), token_enc=encrypt(token), code_hash=sha256(code),
                        code_enc=encrypt(code), redeem_before=end or NEVER, access_expires_at=end, valid=True)
        db.add(ap)
        guest.passes.append(ap)
        return ap, token, code
    if guest.visit_date > local_today(guest):
        redeem_before = _end_of_visit_day(guest)  # pre-registered for a later day
    else:
        redeem_before = min(now + timedelta(minutes=s.qr_redeem_window_minutes), _end_of_visit_day(guest))
    token = new_token(32)  # 256-bit, unguessable
    code = new_access_code(8)  # ~39 bits, rate limited + single use + short lived
    ap = AccessPass(guest_id=guest.id, token_hash=sha256(token), token_enc=encrypt(token), code_hash=sha256(code),
                    code_enc=encrypt(code), redeem_before=redeem_before, valid=True)
    db.add(ap)
    guest.passes.append(ap)
    return ap, token, code


def current_pass(guest: Guest) -> AccessPass | None:
    valid = [p for p in guest.passes if p.valid]
    return valid[-1] if valid else None


def pass_secrets(ap: AccessPass) -> tuple[str, str]:
    return decrypt(ap.token_enc), decrypt(ap.code_enc)


def find_pass_by_token(db: Session, token: str) -> AccessPass | None:
    return db.scalar(select(AccessPass).where(AccessPass.token_hash == sha256(token)))


def find_pass_by_code(db: Session, code: str) -> AccessPass | None:
    return db.scalar(select(AccessPass).where(AccessPass.code_hash == sha256(code)))


def find_pass_by_claim(db: Session, claim: str | None) -> AccessPass | None:
    if not claim:
        return None
    h = sha256(claim)
    ap = db.scalar(select(AccessPass).where(AccessPass.claim_hash == h))
    if ap is None:  # a device that redeemed a permanent code
        dev = db.scalar(select(PassDevice).where(PassDevice.claim_hash == h))
        ap = dev.access_pass if dev else None
    return ap


def check_pass_usable(ap: AccessPass | None) -> AccessPass:
    """Validate that a pass may be redeemed / used right now. Raises PassError."""
    if ap is None:
        raise PassError("unknown_token", "This access code is not valid. Please contact reception.")
    g = ap.guest
    now = utcnow()
    if is_permanent(g):
        if g.status == GuestStatus.revoked or not ap.valid:
            raise PassError("revoked", "This Wi-Fi code has been withdrawn. Please contact the IT team.")
        if g.status == GuestStatus.expired or (ap.access_expires_at and ap.access_expires_at <= now):
            raise PassError("expired", "This Wi-Fi code is no longer valid. Please contact the IT team.")
        if g.status not in (GuestStatus.approved, GuestStatus.active):
            raise PassError("not_approved", "This Wi-Fi code is not active.")
        return ap
    if g.status == GuestStatus.revoked:
        raise PassError("revoked", "Your Wi-Fi access has been revoked. Please contact reception.")
    if g.status in (GuestStatus.pending, GuestStatus.rejected):
        raise PassError("not_approved", "This access request has not been approved.")
    if g.status == GuestStatus.expired or (ap.access_expires_at and ap.access_expires_at <= now):
        if ap.redeemed_at is None:
            raise PassError("qr_expired", "This QR code has expired. Please ask reception to re-issue it.")
        raise PassError("expired", "Your Wi-Fi access has expired. Please contact reception for a new pass.")
    if not ap.valid:
        raise PassError("superseded", "This access pass is no longer valid. Please contact reception.")
    if ap.redeemed_at is None:
        if now > ap.redeem_before:
            raise PassError("qr_expired", "This QR code has expired. Please ask reception to re-issue it.")
        if g.visit_date > local_today(g):
            raise PassError("too_early", f"This pass is valid from {g.visit_date.isoformat()}.")
    return ap


def redeem(db: Session, ap: AccessPass, claim_cookie: str | None, ip: str) -> tuple[str, str, str]:
    """Bind the pass to this browser. Returns (claim_cookie_value, radius_username, radius_password).

    Single use: once redeemed, only the browser holding the claim cookie can retrieve the credentials again.
    """
    check_pass_usable(ap)
    if is_permanent(ap.guest):
        return _redeem_permanent(db, ap, claim_cookie, ip)
    if ap.redeemed_at is not None:
        if claim_cookie and ap.claim_hash and ap.claim_hash == sha256(claim_cookie):
            return claim_cookie, ap.radius_username or "", decrypt(ap.radius_password_enc or "")
        raise PassError("already_redeemed", "This QR code has already been used on another device.")
    claim = new_token(32)
    username = "g-" + new_access_code(10).lower()
    password = new_token(24)
    ap.redeemed_at = utcnow()
    ap.redeemed_ip = ip
    ap.claim_hash = sha256(claim)
    ap.radius_username = username
    ap.radius_password_hash = sha256(password)
    ap.radius_password_enc = encrypt(password)
    if ap.guest.terms_accepted_at is None:
        ap.guest.terms_accepted_at = utcnow()
    return claim, username, password


def _redeem_permanent(db: Session, ap: AccessPass, claim_cookie: str | None, ip: str) -> tuple[str, str, str]:
    """Permanent code: every device that enters it may sign in. All devices share one RADIUS identity; each
    browser gets its own claim cookie so it is signed in again automatically next time."""
    now = utcnow()
    if ap.radius_username is None:
        password = new_token(24)
        ap.radius_username = "p-" + new_access_code(10).lower()
        ap.radius_password_hash = sha256(password)
        ap.radius_password_enc = encrypt(password)
        ap.redeemed_at = now
        ap.redeemed_ip = ip
    if ap.guest.terms_accepted_at is None:
        ap.guest.terms_accepted_at = now
    dev = None
    if claim_cookie:
        dev = db.scalar(select(PassDevice).where(PassDevice.claim_hash == sha256(claim_cookie),
                                                 PassDevice.pass_id == ap.id))
    if dev is None:
        claim_cookie = new_token(32)
        dev = PassDevice(pass_id=ap.id, claim_hash=sha256(claim_cookie), ip=ip)
        db.add(dev)
    dev.last_used_at = now
    dev.ip = ip
    return claim_cookie, ap.radius_username, decrypt(ap.radius_password_enc)


def queue_disconnects(db: Session, guest: Guest) -> int:
    """Queue RADIUS Disconnect-Requests for every open session (and the pass username as a fallback)."""
    n = 0
    open_sessions = db.scalars(select(RadiusSession).where(RadiusSession.guest_id == guest.id,
                                                           RadiusSession.stopped_at.is_(None))).all()
    for rs in open_sessions:
        db.add(PendingDisconnect(location_id=guest.location_id, username=rs.username,
                                 acct_session_id=rs.acct_session_id, client_ip=rs.client_ip))
        n += 1
    if n == 0:
        for p in guest.passes:
            if p.radius_username and p.access_started_at:
                db.add(PendingDisconnect(location_id=guest.location_id, username=p.radius_username))
                n += 1
    return n


def revoke(db: Session, guest: Guest, user_id: int | None, reason: str) -> int:
    guest.status = GuestStatus.revoked
    guest.revoked_at = utcnow()
    guest.revoked_by_id = user_id
    guest.revoke_reason = reason[:255]
    for p in guest.passes:
        p.valid = False
    return queue_disconnects(db, guest)


def mark_disconnected(db: Session, pd: PendingDisconnect, cause: str = "Admin-Reset") -> None:
    """After a Disconnect-ACK, close the matching open session(s) without waiting for Accounting-Stop."""
    q = select(RadiusSession).where(RadiusSession.username == pd.username, RadiusSession.stopped_at.is_(None))
    if pd.acct_session_id:
        q = q.where(RadiusSession.acct_session_id == pd.acct_session_id)
    for rs in db.scalars(q):
        rs.stopped_at = utcnow()
        rs.terminate_cause = cause
