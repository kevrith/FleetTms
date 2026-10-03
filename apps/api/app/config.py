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
    quick_login_max_attempts: int = 5  # wrong PINs before quick sign-in switches itself off
    otp_resend_seconds: int = 60
    invite_ttl_hours: int = 72

    # Report delivery. Leave these empty in development: reports then go to an in-memory outbox.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    whatsapp_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_report_template: str = ""  # an approved template with a document header, needed to message people first

    # M-Pesa Daraja (client payments). Leave the keys empty in development: a stand-in is used and nothing leaves the machine.
    daraja_env: str = "sandbox"  # sandbox or production
    daraja_consumer_key: str = ""
    daraja_consumer_secret: str = ""
    public_api_url: str = ""  # the address Safaricom can reach this API on, for payment callbacks

    # KRA eTIMS. Leave the base address empty in development: a stand-in is used. The sandbox address is in .env.example.
    etims_base_url: str = ""

    # Phone GPS and client tracking links (masterplan 5.3, 5.26, 11.3).
    public_web_url: str = "http://localhost:5180"  # where the web app is, for the links clients are sent
    going_dark_minutes: int = 15  # a lorry on a trip that has not reported for this long is "going dark"
    gps_retention_days: int = 365  # raw location points are deleted after this, once the trip totals are kept
    tracking_link_days: int = 7  # how long a client tracking link lives at most (it also ends when the trip is delivered)
    max_points_per_batch: int = 500

    # GPS trackers through Traccar (masterplan Section 7). Traccar forwards what devices send to /hooks/traccar/<forward key>; leave the
    # key empty to switch that address off. The URL and token are for sending commands (the immobiliser) back through Traccar; with
    # the URL empty a stand-in is used and nothing real is sent.
    traccar_forward_key: str = ""
    traccar_url: str = ""
    traccar_token: str = ""
    tracker_offline_minutes: int = 30  # a tracker silent this long is offline

    # Photos live in private storage and are only ever viewed through short-lived signed links.
    media_dir: str = "media_store"
    media_link_seconds: int = 300
    max_photo_bytes: int = 8 * 1024 * 1024
    photo_fresh_minutes: int = 10  # how old a captured photo may be when it is uploaded

    # Current versions of the legal documents users must accept (masterplan Section 11).
    terms_version: str = "draft-1"
    privacy_version: str = "draft-1"
    dpa_version: str = "draft-1"
    # Route suggestions and pump prices (masterplan 5.12, 5.28). Empty means the built-in estimate and manual prices.
    google_maps_api_key: str = ""
    epra_prices_url: str = ""
    route_lorry_factor: float = 1.3  # Google's drive times are for cars; a loaded lorry takes this much longer
    monitoring_notice_version: str = "draft-2"


settings = Settings()
