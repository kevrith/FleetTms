from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../../.env", ".env"), extra="ignore")

    app_name: str = "fleettms-api"
    version: str = "0.1.0"
    environment: str = "development"
    database_url: str = ""
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: str = "http://localhost:5180"

    # Auth. jwt_secret must come from the environment; there is deliberately no default.
    jwt_secret: str = ""
    access_token_minutes: int = 15
    staff_session_hours: int = 12
    driver_session_days: int = 30
    max_failed_logins: int = 5
    lockout_minutes: int = 15
    otp_ttl_minutes: int = 5
    otp_max_attempts: int = 5
    otp_resend_seconds: int = 60
    invite_ttl_hours: int = 72

    # Photos live in private storage and are only ever viewed through short-lived signed links.
    media_dir: str = "media_store"
    media_link_seconds: int = 300
    max_photo_bytes: int = 8 * 1024 * 1024
    photo_fresh_minutes: int = 10  # how old a captured photo may be when it is uploaded

    # Current versions of the legal documents users must accept (masterplan Section 11).
    terms_version: str = "draft-1"
    privacy_version: str = "draft-1"
    dpa_version: str = "draft-1"
    monitoring_notice_version: str = "draft-1"


settings = Settings()
