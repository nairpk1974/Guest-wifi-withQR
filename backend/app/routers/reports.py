import csv
import io
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from openpyxl import Workbook
from sqlalchemy import and_, func, select, text
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import AuditLog, AuthEvent, Guest, GuestStatus, Location, RadiusSession, Role, User, WorkerHeartbeat
from ..security import audit, location_scope, require_roles, utcnow
from ..serialize import iso, location_out
from .guests import ANY, guest_query

router = APIRouter(prefix="/api", tags=["reports"])
TZ = ZoneInfo("Asia/Kolkata")


def _range(date_from: date | None, date_to: date | None) -> tuple[datetime, datetime]:
    end = date_to or utcnow().astimezone(TZ).date()
    start = date_from or (end - timedelta(days=30))
    return datetime.combine(start, time.min, tzinfo=TZ), datetime.combine(end, time.max, tzinfo=TZ)


def _loc_filter(user: User, location_id: int | None) -> int | None:
    scope = location_scope(user)
    return scope if scope is not None else location_id


@router.get("/dashboard")
def dashboard(location_id: int | None = None, user: User = Depends(require_roles(*ANY)),
              db: Session = Depends(get_db)):
    loc = _loc_filter(user, location_id)
    gw = [Guest.location_id == loc] if loc else []
    counts = dict(db.execute(select(Guest.status, func.count()).where(*gw).group_by(Guest.status)).all())
    sw = [RadiusSession.location_id == loc] if loc else []
    active_by_loc = dict(db.execute(select(Location.code, func.count(RadiusSession.id))
                                    .join(RadiusSession, RadiusSession.location_id == Location.id)
                                    .where(RadiusSession.stopped_at.is_(None), *sw).group_by(Location.code)).all())
    bytes_total = db.execute(select(func.coalesce(func.sum(RadiusSession.input_octets), 0),
                                    func.coalesce(func.sum(RadiusSession.output_octets), 0)).where(*sw)).one()
    today = utcnow().astimezone(TZ).date()
    month_start = today.replace(day=1)
    bw_month = db.execute(select(func.coalesce(func.sum(RadiusSession.input_octets + RadiusSession.output_octets), 0))
                          .where(RadiusSession.started_at >= datetime.combine(month_start, time.min, tzinfo=TZ),
                                 *sw)).scalar()

    loc_sql = "AND location_id = :loc" if loc else ""
    daily = db.execute(text(f"""
        SELECT d::date AS day, COALESCE(c.n, 0) AS n FROM generate_series(:start, :end, interval '1 day') d
        LEFT JOIN (SELECT visit_date, count(*) n FROM guests WHERE visit_date >= :start {loc_sql}
                   GROUP BY visit_date) c ON c.visit_date = d::date ORDER BY 1"""),
                       {"start": today - timedelta(days=29), "end": today, "loc": loc}).all()
    monthly = db.execute(text(f"""
        SELECT to_char(date_trunc('month', visit_date), 'YYYY-MM') m, count(*) n FROM guests
        WHERE visit_date >= :start {loc_sql} GROUP BY 1 ORDER BY 1"""),
                         {"start": (month_start - timedelta(days=335)).replace(day=1), "loc": loc}).all()

    locs = db.scalars(select(Location).order_by(Location.id)).all()
    now = utcnow()
    fw = []
    for l in locs:
        if loc and l.id != loc:
            continue
        radius_recent = bool(l.last_radius_seen_at and now - l.last_radius_seen_at < timedelta(minutes=30))
        ping_ok = bool(l.last_ping_ok_at and l.last_ping_checked_at and l.last_ping_ok_at >= l.last_ping_checked_at
                       - timedelta(seconds=5))
        fw.append({**location_out(l), "ping_ok": ping_ok if l.monitor_host else None, "radius_recent": radius_recent,
                   "last_radius_seen_at": iso(l.last_radius_seen_at), "last_ping_ok_at": iso(l.last_ping_ok_at)})
    hb = db.get(WorkerHeartbeat, "worker")
    db_ok = db.execute(text("SELECT 1")).scalar() == 1
    return {
        "totals": {"registered": sum(counts.values()), **{s.value: counts.get(s, 0) for s in GuestStatus}},
        "active_sessions": sum(active_by_loc.values()),
        "active_sessions_by_location": active_by_loc,
        "bandwidth": {"input_octets": int(bytes_total[0]), "output_octets": int(bytes_total[1]),
                      "month_octets": int(bw_month or 0)},
        "daily": [{"day": r.day.isoformat(), "count": r.n} for r in daily],
        "monthly": [{"month": r.m, "count": r.n} for r in monthly],
        "firewalls": fw,
        "server": {"api": "ok", "database": "ok" if db_ok else "down",
                   "worker_last_seen": iso(hb.ts) if hb else None,
                   "worker_ok": bool(hb and now - hb.ts < timedelta(seconds=get_settings().worker_interval_seconds * 4))},
    }


# ---------------- reports ----------------
REPORTS = {
    "visitors": "Visitor registration history",
    "devices": "Guest device log (MAC & mobile)",
    "logins": "Guest login history",
    "sessions": "Guest sessions (duration & usage)",
    "locations": "Location-wise summary",
    "usage": "Internet usage per guest",
    "expired-revoked": "Expired and revoked access",
    "approvals": "Administrator approval history",
    "auth-failures": "Security & authentication failures",
    "audit": "Administrative audit log",
}


def _fmt_bytes(n: int) -> float:
    return round((n or 0) / 1_048_576, 2)


def build_report(kind: str, db: Session, user: User, location_id: int | None, date_from: date | None,
                 date_to: date | None, q: str | None, mobile: str | None, status: str | None,
                 limit: int = 50000) -> tuple[list[str], list[list]]:
    loc = _loc_filter(user, location_id)
    start, end = _range(date_from, date_to)
    codes = {l.id: l.code for l in db.scalars(select(Location))}

    if kind in ("visitors", "expired-revoked"):
        st = status if kind == "visitors" else (status or "expired,revoked")
        stmt = guest_query(user, loc, st, q, mobile, start.date(), end.date())
        cols = ["Visit date", "Name", "Company", "Mobile", "Email", "Host", "Department", "Location", "Purpose",
                "Duration (h)", "Status", "Registered at", "Registered by", "Decided by", "Decided at",
                "Revoked at", "Revoke reason"]
        rows = [[g.visit_date, g.full_name, g.company, g.mobile, g.email, g.host_person, g.department,
                 g.location.code, g.purpose, g.duration_hours, g.status.value, g.created_at,
                 g.created_by.full_name if g.created_by else "", g.decided_by.full_name if g.decided_by else "",
                 g.decided_at, g.revoked_at, g.revoke_reason]
                for g in db.scalars(stmt.order_by(Guest.created_at.desc()).limit(limit))]
        return cols, rows

    if kind in ("logins", "auth-failures"):
        stmt = select(AuthEvent, Guest).outerjoin(Guest, Guest.id == AuthEvent.guest_id) \
            .where(AuthEvent.ts.between(start, end))
        if kind == "logins":
            stmt = stmt.where(AuthEvent.source.in_(["radius", "portal"]))
        else:
            stmt = stmt.where(AuthEvent.result == "reject")
        if loc:
            stmt = stmt.where(AuthEvent.location_id == loc)
        elif location_scope(user) is None and kind == "auth-failures":
            pass
        if q:
            stmt = stmt.where(Guest.full_name.ilike(f"%{q}%"))
        if mobile:
            stmt = stmt.where(Guest.mobile.ilike(f"%{mobile}%"))
        cols = ["Time", "Source", "Result", "Reason", "Username", "Guest", "Mobile", "Location", "Client IP",
                "Client MAC", "NAS"]
        rows = [[e.ts, e.source, e.result, e.reason, e.username, g.full_name if g else "", g.mobile if g else "",
                 codes.get(e.location_id, ""), e.client_ip, e.client_mac, e.nas_shortname]
                for e, g in db.execute(stmt.order_by(AuthEvent.ts.desc()).limit(limit))]
        return cols, rows

    if kind == "devices":
        # One row per guest + device MAC, built from accepted RADIUS logins (the FortiGate sends the
        # client MAC in Calling-Station-Id for captive-portal users).
        stmt = select(AuthEvent, Guest).join(Guest, Guest.id == AuthEvent.guest_id) \
            .where(AuthEvent.ts.between(start, end), AuthEvent.source == "radius", AuthEvent.result == "accept")
        if loc:
            stmt = stmt.where(AuthEvent.location_id == loc)
        if q:
            stmt = stmt.where(Guest.full_name.ilike(f"%{q}%"))
        if mobile:
            stmt = stmt.where(Guest.mobile.ilike(f"%{mobile}%"))
        dev: dict = {}
        for e, g in db.execute(stmt.order_by(AuthEvent.ts)):
            key = (g.id, e.client_mac or e.client_ip or "")
            d = dev.get(key)
            if d is None:
                dev[key] = d = [g.full_name, g.mobile, g.company, codes.get(e.location_id, ""), e.client_mac,
                                e.client_ip, e.ts, e.ts, 0]
            d[5] = e.client_ip or d[5]
            d[7] = e.ts
            d[8] += 1
        cols = ["Guest", "Mobile", "Company", "Location", "Device MAC", "Last IP", "First login", "Last login",
                "Logins"]
        rows = sorted(dev.values(), key=lambda r: r[7], reverse=True)[:limit]
        return cols, rows

    if kind in ("sessions", "usage"):
        stmt = select(RadiusSession, Guest).outerjoin(Guest, Guest.id == RadiusSession.guest_id) \
            .where(RadiusSession.started_at.between(start, end))
        if loc:
            stmt = stmt.where(RadiusSession.location_id == loc)
        if q:
            stmt = stmt.where(Guest.full_name.ilike(f"%{q}%"))
        if mobile:
            stmt = stmt.where(Guest.mobile.ilike(f"%{mobile}%"))
        if kind == "sessions":
            cols = ["Started", "Stopped", "Duration (min)", "Guest", "Mobile", "Company", "Location", "Client IP",
                    "Client MAC", "Download MB", "Upload MB", "Terminate cause"]
            rows = [[rs.started_at, rs.stopped_at, round((rs.session_time or 0) / 60, 1), g.full_name if g else rs.username,
                     g.mobile if g else "", g.company if g else "", codes.get(rs.location_id, ""), rs.client_ip, rs.client_mac,
                     _fmt_bytes(rs.output_octets), _fmt_bytes(rs.input_octets), rs.terminate_cause]
                    for rs, g in db.execute(stmt.order_by(RadiusSession.started_at.desc()).limit(limit))]
            return cols, rows
        agg = {}
        for rs, g in db.execute(stmt):
            key = rs.guest_id
            a = agg.setdefault(key, [g.full_name if g else rs.username, g.company if g else "",
                                     g.mobile if g else "", codes.get(rs.location_id, ""), 0, 0, 0, 0])
            a[4] += 1
            a[5] += rs.session_time or 0
            a[6] += rs.output_octets or 0
            a[7] += rs.input_octets or 0
        cols = ["Guest", "Company", "Mobile", "Location", "Sessions", "Online (min)", "Download MB", "Upload MB"]
        rows = sorted(([a[0], a[1], a[2], a[3], a[4], round(a[5] / 60, 1), _fmt_bytes(a[6]), _fmt_bytes(a[7])]
                       for a in agg.values()), key=lambda r: -(r[6] + r[7]))
        return cols, rows

    if kind == "locations":
        cols = ["Location", "Registered", "Approved/used", "Rejected", "Expired", "Revoked", "Sessions", "Total MB"]
        rows = []
        for l in db.scalars(select(Location).order_by(Location.id)):
            if loc and l.id != loc:
                continue
            gw = and_(Guest.location_id == l.id, Guest.visit_date.between(start.date(), end.date()))
            c = dict(db.execute(select(Guest.status, func.count()).where(gw).group_by(Guest.status)).all())
            s = db.execute(select(func.count(RadiusSession.id),
                                  func.coalesce(func.sum(RadiusSession.input_octets + RadiusSession.output_octets), 0))
                           .where(RadiusSession.location_id == l.id,
                                  RadiusSession.started_at.between(start, end))).one()
            rows.append([l.code, sum(c.values()), c.get(GuestStatus.approved, 0) + c.get(GuestStatus.active, 0)
                         + c.get(GuestStatus.expired, 0), c.get(GuestStatus.rejected, 0),
                         c.get(GuestStatus.expired, 0), c.get(GuestStatus.revoked, 0), s[0], _fmt_bytes(s[1])])
        return cols, rows

    if kind in ("approvals", "audit"):
        if kind == "audit" and user.role == Role.reception:
            raise HTTPException(403, "Audit log is restricted to Super Administrator and Security/Audit")
        stmt = select(AuditLog).where(AuditLog.ts.between(start, end))
        if kind == "approvals":
            stmt = stmt.where(AuditLog.action.in_(["guest.approved", "guest.rejected", "guest.revoked",
                                                   "guest.pass_reissued", "session.disconnected"]))
        if loc:
            stmt = stmt.where(AuditLog.location_id == loc)
        if q:
            stmt = stmt.where(AuditLog.action.ilike(f"%{q}%") | AuditLog.username.ilike(f"%{q}%"))
        cols = ["Time", "User", "Action", "Entity", "Entity ID", "Location", "IP", "Details"]
        rows = [[a.ts, a.username, a.action, a.entity_type, a.entity_id, codes.get(a.location_id, ""), a.ip,
                 str(a.details or "")] for a in db.scalars(stmt.order_by(AuditLog.ts.desc()).limit(limit))]
        return cols, rows
    raise HTTPException(404, "Unknown report")


def _cell(v):
    if isinstance(v, datetime):
        return v.astimezone(TZ).strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, date):
        return v.isoformat()
    return v


def _safe_csv(v):
    """Neutralise spreadsheet formula injection (CWE-1236)."""
    v = _cell(v)
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return "" if v is None else v


@router.get("/reports")
def list_reports(user: User = Depends(require_roles(*ANY))):
    return [{"kind": k, "title": t} for k, t in REPORTS.items() if not (k == "audit" and user.role == Role.reception)]


@router.get("/reports/{kind}")
def report(kind: str, request: Request, format: str = "json", location_id: int | None = None,
           date_from: date | None = None, date_to: date | None = None, q: str | None = None,
           mobile: str | None = None, status: str | None = None, user: User = Depends(require_roles(*ANY)),
           db: Session = Depends(get_db)):
    if kind not in REPORTS:
        raise HTTPException(404, "Unknown report")
    try:
        cols, rows = build_report(kind, db, user, location_id, date_from, date_to, q, mobile, status,
                                  limit=500 if format == "json" else 100000)
    except ValueError:
        raise HTTPException(400, "Invalid filter")
    if format == "json":
        return {"title": REPORTS[kind], "columns": cols, "rows": [[_cell(v) for v in r] for r in rows],
                "truncated": len(rows) >= 500}
    audit(db, request, user, "report.exported", "report", kind, location_id, format=format, rows=len(rows))
    db.commit()
    stamp = utcnow().astimezone(TZ).strftime("%Y%m%d-%H%M")
    fname = f"bessel-guestwifi-{kind}-{stamp}"
    if format == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(cols)
        for r in rows:
            w.writerow([_safe_csv(v) for v in r])
        return Response(buf.getvalue().encode("utf-8-sig"), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{fname}.csv"'})
    if format == "xlsx":
        wb = Workbook(write_only=True)
        ws = wb.create_sheet(kind[:31])
        ws.append(cols)
        for r in rows:
            ws.append([_safe_csv(v) for v in r])
        out = io.BytesIO()
        wb.save(out)
        out.seek(0)
        return StreamingResponse(out, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                 headers={"Content-Disposition": f'attachment; filename="{fname}.xlsx"'})
    raise HTTPException(400, "format must be json, csv or xlsx")
