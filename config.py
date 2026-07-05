import os
import secrets
import logging
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    google_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash-lite"
    database_url: str = "postgresql://andavar:andavar@localhost:5432/andavar"
    environment: str = "development"
    log_level: str = "INFO"
    port: int = 8000
    rate_limit: str = "30/minute"
    secret_key: str = "change_this_in_prod"

    # ── CORS ───────────────────────────────────────────────
    cors_origins: str = "http://localhost:8000,http://localhost:8001"

    # ── JWT ────────────────────────────────────────────────
    # jwt_secret is read from JWT_SECRET env var; falls back to SECRET_KEY;
    # only generates randomly if neither is set (dev convenience, breaks on restart)
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 1440  # 24 hours

    # ── Encryption (Fernet key for project secrets) ───────
    encryption_key: str = ""  # auto-generated on first boot if blank

    # ── Bootstrap admin ───────────────────────────────────
    admin_email: str = ""
    admin_password: str = ""
    admin_username: str = "admin"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()

# ── Resolve jwt_secret: JWT_SECRET > SECRET_KEY > random (warn) ──────────────
if not settings.jwt_secret:
    _fallback = settings.secret_key
    if _fallback and _fallback != "change_this_in_prod":
        settings.jwt_secret = _fallback
    else:
        settings.jwt_secret = secrets.token_urlsafe(32)
        logging.getLogger("andavar.config").warning(
            "JWT_SECRET not set — generated random secret. "
            "All tokens will be invalidated on restart. "
            "Set JWT_SECRET in .env to fix."
        )

# Ensure GOOGLE_API_KEY is in os.environ for libraries that expect it there
if settings.google_api_key:
    os.environ["GOOGLE_API_KEY"] = settings.google_api_key
