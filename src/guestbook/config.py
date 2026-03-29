from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Walk up from this file to find the project root .env
# src/guestbook/config.py -> src/guestbook -> src -> project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GUESTBOOK_",
        env_file=str(_ENV_FILE) if _ENV_FILE.is_file() else None,
        env_file_encoding="utf-8",
    )

    secret_key: str = "change-me-in-production"
    base_url: str = "http://localhost:8000"
    debug: bool = False
    development: bool = False
    host: str = "0.0.0.0"
    port: int = 8000

    # Database
    database_url: str = "sqlite+aiosqlite:///./guestbook.db"

    # SMTP
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "guestbook@localhost"
    mail_backend: str = "console"  # "console" or "smtp"

    # Session
    session_max_age: int = 604800  # 7 days

    # Auth
    token_expiry_hours: int = 24
    rate_limit_auth: str = "3/hour"


settings = Settings()
