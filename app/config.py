from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Azure / Entra ID
    AZURE_TENANT_ID: str = "your-tenant-id"
    AZURE_CLIENT_ID: str = "your-client-id"
    AZURE_CLIENT_SECRET: str = "your-client-secret"
    AZURE_REDIRECT_URI: str = "http://localhost:8000/auth/callback"

    # Session security
    SECRET_KEY: str = "change-me-to-a-32-byte-random-hex-string"
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
