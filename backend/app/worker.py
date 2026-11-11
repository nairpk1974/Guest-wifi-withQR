"""Background worker: expiry enforcement, RADIUS Disconnect retries, stale-session cleanup,
firewall reachability checks and data-retention purge. Run: python -m app.worker"""
import logging
import signal
import subprocess
import time
from datetime import timedelta

from sqlalchemy import delete, select, update

from .access import mark_disconnected, queue_disconnects
from .coa import send_disconnect
from .config import get_settings
from .db import SessionLocal
from .models import (AccessPass, AdminSession, AuditLog, AuthEvent, Guest, GuestStatus, Location, MfaTicket,
                     PendingDisconnect, RadiusSession, WorkerHeartbeat)
from .security import utcnow

log = logging.getLogger("worker")
_running = True


def _stop(*_):
    global _running
    _running = False


def expire_passes(db) -> int:
    now = utcnow()
    n = 0
    # Access clock ran out
    for ap in db.scalars(select(AccessPass).join(Guest).where(Guest.status == GuestStatus.active,
                                                             AccessPass.valid.is_(True),
                                                             AccessPass.access_expires_at <= now)):
        ap.valid = False
        ap.guest.status = GuestStatus.expired
        queue_disconnects(db, ap.guest)
        db.add(AuditLog(action="guest.expired", entity_type="guest", entity_id=str(ap.guest_id),
                        location_id=ap.guest.location_id, details={"reason": "duration elapsed"}))
        n += 1
    # QR never used within its redemption window (or redeemed but never logged in)
    for ap in db.scalars(select(AccessPass).join(Guest).where(Guest.status == GuestStatus.approved,
                                                             AccessPass.valid.is_(True),
                                                             AccessPass.access_started_at.is_(None),
                                                             AccessPass.redeem_before <= now)):
        if ap.redeemed_at and ap.redeemed_at > now - timedelta(minutes=30):
            continue  # give a redeemed pass a grace period to complete the FortiGate login
        ap.valid = False
        ap.guest.status = GuestStatus.expired
        db.add(AuditLog(action="guest.expired", entity_type="guest", entity_id=str(ap.guest_id),
                        location_id=ap.guest.location_id, details={"reason": "QR not used in time"}))
        n += 1
    # Pending requests for a visit day that has passed
    for g in db.scalars(select(Guest).where(Guest.status == GuestStatus.pending,
                                            Guest.visit_date < (now - timedelta(days=1)).date())):
        g.status = GuestStatus.expired
        n += 1
    db.commit()
    return n


def send_pending_disconnects(db) -> None:
    s = get_settings()
    for pd in db.scalars(select(PendingDisconnect).where(PendingDisconnect.done.is_(False),
                                                         PendingDisconnect.attempts < 20)).all():
        loc = db.get(Location, pd.location_id)
        ok, msg = send_disconnect(loc.coa_host or "", loc.coa_port, s.coa_secret_for(loc.code), pd.username,
                                  pd.acct_session_id, pd.client_ip)
        pd.attempts += 1
        pd.last_result = msg
        pd.done = ok
        if ok:
            mark_disconnected(db, pd, "Disconnect-ACK")
            log.info("Disconnect ACK user=%s site=%s", pd.username, loc.code)
        else:
            log.warning("Disconnect failed user=%s site=%s: %s", pd.username, loc.code, msg)
    db.commit()


def close_stale_sessions(db) -> None:
    cutoff = utcnow() - timedelta(minutes=get_settings().session_stale_minutes)
    db.execute(update(RadiusSession).where(RadiusSession.stopped_at.is_(None), RadiusSession.last_update_at < cutoff)
               .values(stopped_at=RadiusSession.last_update_at, terminate_cause="Stale-No-Accounting"))
    db.commit()


def ping_firewalls(db) -> None:
    for loc in db.scalars(select(Location).where(Location.monitor_host.is_not(None))):
        try:
            ok = subprocess.run(["ping", "-c", "1", "-W", "2", loc.monitor_host], capture_output=True,
                                timeout=5).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            ok = False
        now = utcnow()
        loc.last_ping_checked_at = now
        if ok:
            loc.last_ping_ok_at = now
    db.commit()


def retention(db) -> None:
    s = get_settings()
    now = utcnow()
    pii_cutoff = now - timedelta(days=s.guest_pii_retention_days)
    for g in db.scalars(select(Guest).where(Guest.anonymized.is_(False), Guest.created_at < pii_cutoff,
                                            Guest.status.in_([GuestStatus.expired, GuestStatus.revoked,
                                                              GuestStatus.rejected]))):
        g.full_name = "Anonymised visitor"
        g.mobile = "XXXXXXXX" + g.mobile[-2:]
        g.email = None
        g.purpose = "-"
        g.anonymized = True
    log_cutoff = now - timedelta(days=s.log_retention_days)
    db.execute(delete(AuthEvent).where(AuthEvent.ts < log_cutoff))
    db.execute(delete(AuditLog).where(AuditLog.ts < log_cutoff))
    db.execute(delete(RadiusSession).where(RadiusSession.started_at < log_cutoff))
    db.execute(delete(PendingDisconnect).where(PendingDisconnect.created_at < now - timedelta(days=7)))
    db.execute(delete(AdminSession).where(AdminSession.expires_at < now))
    db.execute(delete(MfaTicket).where(MfaTicket.expires_at < now))
    db.commit()


def heartbeat(db) -> None:
    hb = db.get(WorkerHeartbeat, "worker")
    if hb:
        hb.ts = utcnow()
    else:
        db.add(WorkerHeartbeat(name="worker", ts=utcnow()))
    db.commit()


def run_once(cycle: int) -> None:
    db = SessionLocal()
    try:
        expire_passes(db)
        send_pending_disconnects(db)
        close_stale_sessions(db)
        if cycle % 2 == 0:
            ping_firewalls(db)
        if cycle % 120 == 0:  # ~hourly at 30 s interval
            retention(db)
        heartbeat(db)
    except Exception:  # noqa: BLE001
        log.exception("worker cycle failed")
        db.rollback()
    finally:
        db.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    interval = get_settings().worker_interval_seconds
    log.info("worker started, interval=%ss", interval)
    cycle = 0
    while _running:
        run_once(cycle)
        cycle += 1
        for _ in range(interval):
            if not _running:
                break
            time.sleep(1)


if __name__ == "__main__":
    main()
