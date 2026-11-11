"""Database schema. Alembic migrations in backend/migrations are generated from these models."""
import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class Role(str, enum.Enum):
    super_admin = "super_admin"
    reception = "reception"
    auditor = "auditor"


class GuestStatus(str, enum.Enum):
    pending = "pending"  # submitted, awaiting approval
    approved = "approved"  # QR issued, not yet used
    active = "active"  # first RADIUS login done, access clock running
    expired = "expired"
    rejected = "rejected"
    revoked = "revoked"


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Location(Base):
    __tablename__ = "locations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(8), unique=True)  # BLR / HYD
    name: Mapped[str] = mapped_column(String(80))
    ssid: Mapped[str] = mapped_column(String(32))
    timezone: Mapped[str] = mapped_column(String(40), default="Asia/Kolkata")
    # FreeRADIUS client shortname for this site's FortiGate (deploy/freeradius/clients.conf)
    nas_shortname: Mapped[str] = mapped_column(String(32), unique=True)
    # FortiGate address that receives RADIUS Disconnect/CoA (UDP 3799). Filled after discovery.
    coa_host: Mapped[str | None] = mapped_column(String(64), nullable=True)
    coa_port: Mapped[int] = mapped_column(Integer, default=3799)
    # Hosts (IP[:port]) the captive portal is allowed to post credentials to (FortiGate guest interface)
    portal_post_hosts: Mapped[list] = mapped_column(JSON, default=list)
    # Host pinged by the worker for the "firewall connectivity" tile
    monitor_host: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_radius_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_ping_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_ping_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    full_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(160), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role, name="role"))
    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    mfa_secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    location: Mapped[Location | None] = relationship()


class AdminSession(Base):
    __tablename__ = "admin_sessions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # "full" = normal; "mfa_setup" = may only enrol MFA / change password
    stage: Mapped[str] = mapped_column(String(16), default="full")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user: Mapped[User] = relationship()


class MfaTicket(Base):
    """Short-lived ticket between password step and TOTP step of login."""

    __tablename__ = "mfa_tickets"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)


class Guest(Base):
    __tablename__ = "guests"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    full_name: Mapped[str] = mapped_column(String(120))
    company: Mapped[str] = mapped_column(String(160))
    mobile: Mapped[str] = mapped_column(String(20), index=True)
    email: Mapped[str | None] = mapped_column(String(160), nullable=True)
    host_person: Mapped[str] = mapped_column(String(120))
    department: Mapped[str] = mapped_column(String(80))
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"), index=True)
    purpose: Mapped[str] = mapped_column(String(255))
    visit_date: Mapped[date] = mapped_column(Date, index=True)
    duration_hours: Mapped[int] = mapped_column(Integer)
    status: Mapped[GuestStatus] = mapped_column(Enum(GuestStatus, name="guest_status"), index=True)

    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    decided_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    revoked_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    terms_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    anonymized: Mapped[bool] = mapped_column(Boolean, default=False)

    location: Mapped[Location] = relationship()
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    decided_by: Mapped[User | None] = relationship(foreign_keys=[decided_by_id])
    revoked_by: Mapped[User | None] = relationship(foreign_keys=[revoked_by_id])
    passes: Mapped[list["AccessPass"]] = relationship(back_populates="guest", order_by="AccessPass.issued_at")


class AccessPass(Base):
    """One QR / access code. A guest can have several passes over time (re-issue), only one valid."""

    __tablename__ = "access_passes"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    guest_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("guests.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    token_enc: Mapped[str] = mapped_column(Text)  # encrypted so reception can re-print while valid
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    code_enc: Mapped[str] = mapped_column(Text)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    redeem_before: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid: Mapped[bool] = mapped_column(Boolean, default=True)  # false after re-issue / revoke / expiry

    # Set on redemption (QR scan or code entry)
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    redeemed_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    claim_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)  # browser cookie
    radius_username: Mapped[str | None] = mapped_column(String(32), nullable=True, unique=True)
    radius_password_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    radius_password_enc: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Set at first successful RADIUS authentication
    access_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    access_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    bound_device: Mapped[str | None] = mapped_column(String(64), nullable=True)

    guest: Mapped[Guest] = relationship(back_populates="passes")


class RadiusSession(Base):
    __tablename__ = "radius_sessions"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    pass_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("access_passes.id", ondelete="SET NULL"), nullable=True)
    guest_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("guests.id", ondelete="SET NULL"), nullable=True, index=True)
    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"), nullable=True, index=True)
    username: Mapped[str] = mapped_column(String(64))
    acct_session_id: Mapped[str] = mapped_column(String(128))
    nas_shortname: Mapped[str | None] = mapped_column(String(32), nullable=True)
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    client_mac: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    last_update_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    input_octets: Mapped[int] = mapped_column(BigInteger, default=0)
    output_octets: Mapped[int] = mapped_column(BigInteger, default=0)
    session_time: Mapped[int] = mapped_column(Integer, default=0)
    terminate_cause: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (Index("ix_radius_sessions_acct", "nas_shortname", "acct_session_id", "username", unique=True),)


class AuthEvent(Base):
    """Every RADIUS authentication and guest-portal redemption attempt (accept or reject)."""

    __tablename__ = "auth_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    source: Mapped[str] = mapped_column(String(16))  # radius | portal | admin-login
    result: Mapped[str] = mapped_column(String(8))  # accept | reject
    reason: Mapped[str] = mapped_column(String(80))
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    guest_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    location_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    client_mac: Mapped[str | None] = mapped_column(String(64), nullable=True)
    nas_shortname: Mapped[str | None] = mapped_column(String(32), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    location_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class PendingDisconnect(Base):
    """Queue of RADIUS Disconnect-Requests to send (revocation / expiry). Retried by the worker."""

    __tablename__ = "pending_disconnects"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    username: Mapped[str] = mapped_column(String(64))
    acct_session_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    done: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    last_result: Mapped[str | None] = mapped_column(String(120), nullable=True)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeat"
    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
