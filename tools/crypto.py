"""Fernet-based encryption for sensitive project fields (DB URL, API key)."""

import base64
import logging
from cryptography.fernet import Fernet
from config import settings

logger = logging.getLogger("andavar.crypto")

_fernet = None


def _get_fernet() -> Fernet:
    """Lazy-init Fernet cipher. Auto-generates key if missing."""
    global _fernet
    if _fernet is not None:
        return _fernet

    key = settings.encryption_key
    if not key:
        raise RuntimeError("ENCRYPTION_KEY was not initialized")

    # Fernet expects url-safe base64; if user provides raw string, pad it
    try:
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    except Exception:
        # Key might be a plain string — derive a valid Fernet key from it
        import hashlib
        derived = base64.urlsafe_b64encode(
            hashlib.sha256(key.encode()).digest()
        )
        _fernet = Fernet(derived)

    return _fernet


def encrypt(plaintext: str) -> str:
    """Encrypt a string, returns base64 token."""
    if not plaintext:
        return ""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    """Decrypt a Fernet token back to plaintext."""
    if not token:
        return ""
    return _get_fernet().decrypt(token.encode()).decode()


def mask_url(url: str) -> str:
    """Mask a database URL for display: show host, hide password."""
    if not url:
        return ""
    try:
        # postgresql://user:pass@host:port/db
        at_idx = url.index("@")
        proto_end = url.index("://") + 3
        return url[:proto_end] + "***:***@" + url[at_idx + 1:]
    except (ValueError, IndexError):
        return url[:20] + "…"
