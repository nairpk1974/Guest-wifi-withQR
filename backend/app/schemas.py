import re
from datetime import date

from pydantic import BaseModel, Field, field_validator

from .models import Role

_MOBILE = re.compile(r"^\+?[0-9][0-9 \-]{6,18}[0-9]$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _clean(v: str) -> str:
    v = " ".join(v.split())
    if any(ord(c) < 32 for c in v):
        raise ValueError("Invalid characters")
    return v


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class MfaIn(BaseModel):
    ticket: str = Field(min_length=10, max_length=100)
    code: str = Field(min_length=6, max_length=8)


class CodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class GuestIn(BaseModel):
    """Only name and mobile are required; everything else has a sensible default (quick pass)."""
    full_name: str = Field(min_length=2, max_length=120)
    mobile: str = Field(min_length=7, max_length=20)
    company: str | None = Field(default=None, max_length=160)
    email: str | None = Field(default=None, max_length=160)
    host_person: str | None = Field(default=None, max_length=120)
    department: str | None = Field(default=None, max_length=80)
    location_id: int | None = None
    purpose: str | None = Field(default=None, max_length=255)
    visit_date: date | None = None
    duration_hours: int | None = None

    @field_validator("full_name")
    @classmethod
    def clean_name(cls, v: str) -> str:
        return _clean(v)

    @field_validator("company", "host_person", "department", "purpose")
    @classmethod
    def clean_optional(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = _clean(v)
        return v or None

    @field_validator("mobile")
    @classmethod
    def check_mobile(cls, v: str) -> str:
        v = v.strip()
        if not _MOBILE.match(v):
            raise ValueError("Invalid mobile number")
        return v

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        v = v.strip().lower()
        if not _EMAIL.match(v):
            raise ValueError("Invalid e-mail address")
        return v


class ReasonIn(BaseModel):
    reason: str = Field(min_length=2, max_length=255)


class UserIn(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9._-]+$")
    full_name: str = Field(min_length=2, max_length=120)
    email: str | None = Field(default=None, max_length=160)
    role: Role
    location_id: int | None = None


class UserPatch(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    email: str | None = Field(default=None, max_length=160)
    role: Role | None = None
    location_id: int | None = None
    is_active: bool | None = None


class LocationPatch(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    ssid: str | None = Field(default=None, max_length=32)
    coa_host: str | None = Field(default=None, max_length=64)
    coa_port: int | None = Field(default=None, ge=1, le=65535)
    portal_post_hosts: list[str] | None = None
    monitor_host: str | None = Field(default=None, max_length=64)
    enabled: bool | None = None

    @field_validator("portal_post_hosts")
    @classmethod
    def check_hosts(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        out = []
        for h in v:
            h = h.strip()
            if not re.match(r"^[A-Za-z0-9.\-]+(:[0-9]{1,5})?$", h):
                raise ValueError(f"Invalid host: {h}")
            out.append(h)
        return out

    @field_validator("coa_host", "monitor_host")
    @classmethod
    def check_host(cls, v: str | None) -> str | None:
        if v and not re.match(r"^[A-Za-z0-9.\-]+$", v):
            raise ValueError("Invalid host")
        return v or None


class SettingsIn(BaseModel):
    terms_text: str | None = Field(default=None, max_length=20000)
    privacy_text: str | None = Field(default=None, max_length=20000)
