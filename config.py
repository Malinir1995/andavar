import os
import secrets
import base64
import logging
from pydantic_settings import BaseSettings, SettingsConfigDict


logger = logging.getLogger("andavar.config")


def _data_dir() -> str:
    return os.getenv("ANDAVAR_DATA_DIR", os.path.join(os.getcwd(), ".andavar"))


def _secret_file_path() -> str:
    return os.getenv("ANDAVAR_SECRET_FILE", os.path.join(_data_dir(), "secrets.env"))


def _read_secret_file() -> dict[str, str]:
    path = _secret_file_path()
    if not os.path.exists(path):
        return {}

    values: dict[str, str] = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def _write_secret_file(values: dict[str, str]) -> None:
    path = _secret_file_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for key, value in values.items():
            f.write(f"{key}={value}\n")
    os.chmod(path, 0o600)


def _fernet_key() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


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

_persisted = _read_secret_file()
_changed = False

if not settings.secret_key or settings.secret_key == "change_this_in_prod":
    settings.secret_key = _persisted.get("SECRET_KEY") or secrets.token_hex(32)
    if _persisted.get("SECRET_KEY") != settings.secret_key:
        _persisted["SECRET_KEY"] = settings.secret_key
        _changed = True

if not settings.jwt_secret:
    settings.jwt_secret = _persisted.get("JWT_SECRET") or secrets.token_urlsafe(48)
    if _persisted.get("JWT_SECRET") != settings.jwt_secret:
        _persisted["JWT_SECRET"] = settings.jwt_secret
        _changed = True

if not settings.encryption_key:
    settings.encryption_key = _persisted.get("ENCRYPTION_KEY") or _fernet_key()
    if _persisted.get("ENCRYPTION_KEY") != settings.encryption_key:
        _persisted["ENCRYPTION_KEY"] = settings.encryption_key
        _changed = True

if _changed:
    _write_secret_file(_persisted)
    logger.warning(
        "Generated persistent application secrets at %s. "
        "Keep ANDAVAR_DATA_DIR or ANDAVAR_SECRET_FILE on persistent storage.",
        _secret_file_path(),
    )

# Ensure GOOGLE_API_KEY is in os.environ for libraries that expect it there
if settings.google_api_key:
    os.environ["GOOGLE_API_KEY"] = settings.google_api_key
