"""Application configuration from environment variables."""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://jobplatform:jobplatform@localhost:5432/jobplatform"
    database_url_sync: str = "postgresql://jobplatform:jobplatform@localhost:5432/jobplatform"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Auth
    google_client_id: str = ""
    google_client_secret: str = ""
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 24
    allowed_emails: str = ""  # comma-separated list, empty = allow all

    # App
    app_url: str = "http://localhost:3000"
    api_url: str = "http://localhost:8000"
    debug: bool = False

    # LinkedIn (RapidAPI)
    rapidapi_key: str = ""
    rapidapi_linkedin_host: str = "jsearch.p.rapidapi.com"  # or linkedin-data-api.p.rapidapi.com

    # AI
    anthropic_api_key: str = ""
    ai_daily_limit_per_user: int = 10  # max AI customizations per user per day

    # Security
    credential_encryption_key: str = ""  # Falls back to jwt_secret if empty

    # Scanning
    scan_interval_hours: int = 6
    scan_rate_limit_per_second: float = 2.0
    job_expiry_days: int = 14

    # Enrichment
    enrichment_stale_days: int = 30
    contact_verify_stale_days: int = 14
    enrichment_batch_size: int = 50

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def allowed_email_list(self) -> list[str]:
        if not self.allowed_emails:
            return []
        return [e.strip() for e in self.allowed_emails.split(",") if e.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
