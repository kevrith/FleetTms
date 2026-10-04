from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../../.env", ".env"), extra="ignore")

    app_name: str = "fleettms-api"
    version: str = "0.1.0"
    environment: str = "development"
    database_url: str = ""
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: str = "http://localhost:5180"
    # Rate limits (see ratelimit.py). Believe X-Forwarded-For only when a proxy you control sets it.
    rate_limits_enabled: bool = True
    trust_proxy_headers: bool = False
    rate_limit_per_minute: int = 1200  # a backstop for every address, far above what a busy office does

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
    # The platform's own Paybill, where subscriptions are paid by M-Pesa prompt (STK push). Separate from the Paybills businesses use for their clients.
    platform_shortcode: str = ""
    platform_passkey: str = ""
    # Switch on at launch: plan limits and read-only mode. Off, every account has every feature and nothing is ever read-only.
    enforce_plans: bool = True
    enforce_billing: bool = True
    public_api_url: str = ""  # the address Safaricom can reach this API on, for payment callbacks

    # KRA eTIMS. Leave the base address empty in development: a stand-in is used. The sandbox address is in .env.example.
    etims_base_url: str = ""

    # Phone GPS and client tracking links (masterplan 5.3, 5.26, 11.3).
    public_web_url: str = "http://localhost:5180"  # where the web app is, for the links clients are sent
    going_dark_minutes: int = 15  # a lorry on a trip that has not reported for this long is "going dark"
    gps_retention_days: int = 365  # raw location points are deleted after this, once the trip totals are kept
    # The rest of the retention policy (masterplan 11.3). Financial records are never deleted on a timer: the five years is a minimum.
    photo_retention_days: int = 730  # odometer and receipt photos, unless tied to an open dispute or alert
    audit_retention_days: int = 1826  # five years; the database refuses to delete a younger row whatever this says
    financial_retention_days: int = 1826  # after a business cancels, its financial records are kept this long, then it is erased
    former_staff_retention_days: int = 1826  # a person who has left keeps their staff details this long, then they are anonymised
    # Text messages through Africa's Talking (https://developers.africastalking.com). Leave the username and key empty in development: messages
    # then stay in memory (and the API refuses to start in production without them). AT_SANDBOX=true uses their test environment.
    at_username: str = ""
    at_api_key: str = ""
    at_sender_id: str = ""  # a sender name registered for Kenya, such as FleetTms; empty uses their shared short code
    at_sandbox: bool = False
    # The partner programme (masterplan Section 9): tracker installers who bring in customers earn a share of what those customers pay.
    # These are proposals to be decided, not agreements: the percentage is each partner's own once approved, and zero months means for as long as they pay.
    partner_commission_pct: int = 20
    partner_commission_months: int = 24
    web_app_url: str = ""  # where the web app is, for the links we text to partners
    # Product analytics (analytics.py): counts of which parts of the product each business uses, with no people and no content in them.
    analytics_enabled: bool = True
    # How customers reach us (shown in the apps and on the help pages). Leave empty until the channels exist.
    support_whatsapp: str = ""  # a Kenyan number, like 0712 345 678
    support_email: str = ""
    support_hours: str = "Monday to Saturday, 8am to 6pm (Nairobi time)"
    # Monitoring (see readiness.py). Leave BACKUP_DIR empty where backups are not made on this machine: the check then says "not configured".
    backup_dir: str = ""  # the folder that holds base/ and wal/ (scripts/dr)
    backup_max_age_hours: int = 30  # a daily base backup older than this is a failure
    wal_max_age_minutes: int = 15  # the newest archived WAL segment (recovery point target), checked on the database
    worker_heartbeat_max_seconds: int = 180
    alert_emails: str = ""  # who the uptime checker emails when the system is down (comma separated); needs the SMTP settings above
    alert_webhook_url: str = ""  # or a chat webhook that accepts {"text": ...} (Slack, Teams, Mattermost)
    dsar_due_days: int = 30  # how long a person's data protection request may stay open; to be confirmed with the advocate
    cancelled_grace_days: int = 90  # a cancelled business is read-only this long for export, then its personal data is removed
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
    privacy_version: str = "draft-2"
    dpa_version: str = "draft-1"
    # Route suggestions and pump prices (masterplan 5.12, 5.28). Empty means the built-in estimate and manual prices.
    google_maps_api_key: str = ""
    epra_prices_url: str = ""
    route_lorry_factor: float = 1.3
    # Document reading (masterplan 5.28): photos of receipts and tickets are read by a cloud vision model. "fake" is for tests and local
    # development; empty with no key means reading is switched off. The photo leaves our servers, so the provider is a disclosed sub-processor.
    document_reader: str = ""
    anthropic_api_key: str = ""
    document_reader_model: str = "claude-haiku-4-5-20251001"
    document_reads_per_day: int = 200  # per person, so a stuck screen cannot run up the bill
    # Asking questions in plain English: a model that may only call read-only lookups on the business's own data. "fake" is for tests.
    ask_llm: str = ""
    ask_model: str = "claude-sonnet-5-5"
    ask_per_day: int = 100  # questions per person per day, so a stuck screen cannot run up the bill
    monitoring_notice_version: str = "draft-2"


settings = Settings()
