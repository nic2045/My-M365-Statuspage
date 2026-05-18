import logging
import secrets
from pathlib import Path

from pydantic import computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# Sentinel value from .env.example – treated as "not configured"
_SECRET_KEY_PLACEHOLDER = "change-me-to-a-32-byte-random-hex-string"
# Persisted location for the auto-generated key (same writable dir as the DB)
_SECRET_KEY_FILE = Path("data") / "secret_key"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Azure / Entra ID
    AZURE_TENANT_ID: str = "your-tenant-id"
    AZURE_CLIENT_ID: str = "your-client-id"
    AZURE_CLIENT_SECRET: str = "your-client-secret"
    AZURE_REDIRECT_URI: str = "http://localhost:8000/auth/callback"

    # Session security – empty/placeholder triggers auto-generation on first run
    # (persisted to data/secret_key so sessions survive restarts).
    SECRET_KEY: str = ""
    SESSION_MAX_AGE: int = 3600

    # Embed widget API key (empty = OIDC required for /embed)
    EMBED_API_KEY: str = ""

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/statuspage.db"

    # Services (comma-separated, must match Graph API service names exactly)
    MONITORED_SERVICES: str = "Exchange Online,SharePoint Online,Microsoft Teams"

    # Polling
    POLL_INTERVAL_MINUTES: int = 10

    # App
    DEBUG: bool = False
    APP_TITLE: str = "M365 Dienststatus"

    # Dev: bypass Entra ID OIDC – all routes accessible without login
    DISABLE_AUTH: bool = False

    # UI language fallback when the visitor has no cookie, no Accept-Language
    # header and no admin-configured default. Supported: "de", "en".
    DEFAULT_LANGUAGE: str = "de"

    # Notifications – Email (SMTP)
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASS: str = ""
    SMTP_FROM: str = ""
    SMTP_TLS: bool = True          # True = STARTTLS on port 587; False = plain

    # Notifications – MS Teams incoming webhook (comma-separated for multiple channels)
    TEAMS_WEBHOOK_URLS: str = ""

    # Public base URL (used in email links)
    BASE_URL: str = "http://localhost:8000"

    # Build metadata (injected by Docker build args; empty in local dev)
    BUILD_SHA: str = ""
    BUILD_TIME: str = ""

    @model_validator(mode="after")
    def _ensure_secret_key(self) -> "Settings":
        if self.SECRET_KEY and self.SECRET_KEY != _SECRET_KEY_PLACEHOLDER:
            return self

        try:
            _SECRET_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
            if _SECRET_KEY_FILE.is_file():
                stored = _SECRET_KEY_FILE.read_text(encoding="utf-8").strip()
                if stored:
                    self.SECRET_KEY = stored
                    return self
            generated = secrets.token_hex(32)
            _SECRET_KEY_FILE.write_text(generated, encoding="utf-8")
            try:
                _SECRET_KEY_FILE.chmod(0o600)
            except OSError:
                pass
            self.SECRET_KEY = generated
            logger.warning(
                "SECRET_KEY was not configured – generated a new one and "
                "persisted it to %s. Set SECRET_KEY in your environment to "
                "override.",
                _SECRET_KEY_FILE,
            )
        except OSError:
            # Read-only filesystem etc. – fall back to an ephemeral key so the
            # app still boots, but warn that sessions won't survive a restart.
            self.SECRET_KEY = secrets.token_hex(32)
            logger.warning(
                "SECRET_KEY was not configured and %s is not writable – "
                "using an ephemeral key. Sessions will be invalidated on "
                "every restart.",
                _SECRET_KEY_FILE,
            )
        return self

    @property
    def teams_webhook_list(self) -> list[str]:
        return [u.strip() for u in self.TEAMS_WEBHOOK_URLS.split(",") if u.strip()]

    @computed_field
    @property
    def oidc_metadata_url(self) -> str:
        return (
            f"https://login.microsoftonline.com/{self.AZURE_TENANT_ID}"
            "/v2.0/.well-known/openid-configuration"
        )

    @property
    def monitored_services_list(self) -> list[str]:
        return [s.strip() for s in self.MONITORED_SERVICES.split(",") if s.strip()]


settings = Settings()
