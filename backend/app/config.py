"""Application settings. All secrets come from environment variables (see deploy/.env.example)."""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    # Core
    environment: str = "production"
    database_url: str = Field(..., alias="DATABASE_URL")
    # 32-byte url-safe base64 Fernet key used to encrypt QR tokens / access codes / MFA secrets at rest
    data_encryption_key: str = Field(..., alias="DATA_ENCRYPTION_KEY")
    # Shared secret between FreeRADIUS (rlm_rest) and the backend internal API
    radius_api_key: str = Field(..., alias="RADIUS_API_KEY")

    # Public hostnames (must match nginx + TLS certificate)
    admin_base_url: str = Field("https://wifi-admin.example.invalid", alias="ADMIN_BASE_URL")
    guest_base_url: str = Field("https://guest.example.invalid", alias="GUEST_BASE_URL")

    # Admin sessions / auth
    session_idle_minutes: int = Field(30, alias="SESSION_IDLE_MINUTES")
    session_absolute_hours: int = Field(10, alias="SESSION_ABSOLUTE_HOURS")
    mfa_enforced: bool = Field(True, alias="MFA_ENFORCED")
    max_failed_logins: int = Field(5, alias="MAX_FAILED_LOGINS")
    lockout_minutes: int = Field(15, alias="LOCKOUT_MINUTES")
    require_separate_approver: bool = Field(False, alias="REQUIRE_SEPARATE_APPROVER")

    # Guest access
    allowed_durations_hours: str = Field("1,4,8,12", alias="ALLOWED_DURATIONS_HOURS")
    # How long an approved QR code can be redeemed before it is void (minutes after approval)
    qr_redeem_window_minutes: int = Field(120, alias="QR_REDEEM_WINDOW_MINUTES")
    # Plain-HTTP URL the guest browser is sent to after claiming the QR, so FortiGate intercepts it
    # and redirects to the external captive portal with its "magic" parameter.
    captive_trigger_url: str = Field("http://neverssl.com/", alias="CAPTIVE_TRIGGER_URL")
    # Shown on the pass. Open SSID (or OWE) - no reusable password is ever printed.
    radius_group_name: str = Field("BESSEL-GUEST", alias="RADIUS_GROUP_NAME")

    # Privacy / retention
    guest_pii_retention_days: int = Field(180, alias="GUEST_PII_RETENTION_DAYS")
    log_retention_days: int = Field(365, alias="LOG_RETENTION_DAYS")

    # Optional SMTP for e-mailing passes
    smtp_host: str = Field("", alias="SMTP_HOST")
    smtp_port: int = Field(587, alias="SMTP_PORT")
    smtp_user: str = Field("", alias="SMTP_USER")
    smtp_password: str = Field("", alias="SMTP_PASSWORD")
    smtp_from: str = Field("", alias="SMTP_FROM")

    # Per-location RADIUS CoA/Disconnect secrets (never stored in the DB)
    coa_secret_blr: str = Field("", alias="COA_SECRET_BLR")
    coa_secret_hyd: str = Field("", alias="COA_SECRET_HYD")

    # Worker
    worker_interval_seconds: int = Field(30, alias="WORKER_INTERVAL_SECONDS")
    session_stale_minutes: int = Field(20, alias="SESSION_STALE_MINUTES")

    @property
    def durations(self) -> list[int]:
        return sorted({int(x) for x in self.allowed_durations_hours.split(",") if x.strip()})

    def coa_secret_for(self, location_code: str) -> str:
        return {"BLR": self.coa_secret_blr, "HYD": self.coa_secret_hyd}.get(location_code.upper(), "")

    @property
    def secure_cookies(self) -> bool:
        return self.environment != "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
