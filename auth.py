"""JWT authentication and role-based access control for Andavar."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from functools import wraps

import jwt
import bcrypt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from config import settings

logger = logging.getLogger("andavar.auth")

security = HTTPBearer(auto_error=False)

# Role hierarchy: admin > manager > guest
ROLE_HIERARCHY = {"admin": 3, "manager": 2, "guest": 1}


def hash_password(password: str) -> str:
    pw_bytes = password.encode('utf-8')
    # Limit password to 72 bytes to prevent bcrypt overflow/error
    if len(pw_bytes) > 72:
        pw_bytes = pw_bytes[:72]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pw_bytes, salt).decode('utf-8')


def verify_password(plain: str, hashed: str) -> bool:
    try:
        plain_bytes = plain.encode('utf-8')
        if len(plain_bytes) > 72:
            plain_bytes = plain_bytes[:72]
        return bcrypt.checkpw(plain_bytes, hashed.encode('utf-8'))
    except Exception:
        return False


def create_token(user_id: str, role: str, username: str) -> str:
    payload = {
        "sub": user_id,
        "role": role,
        "username": username,
        "exp": datetime.now(timezone.utc)
        + timedelta(minutes=settings.jwt_expiry_minutes),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict:
    """Extract and validate user from JWT bearer token."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(credentials.credentials)
    return {
        "id": payload["sub"],
        "role": payload["role"],
        "username": payload.get("username", ""),
    }


def require_role(min_role: str):
    """Dependency factory: require user has at least `min_role` level."""
    min_level = ROLE_HIERARCHY.get(min_role, 0)

    async def _check(user: dict = Depends(get_current_user)):
        user_level = ROLE_HIERARCHY.get(user["role"], 0)
        if user_level < min_level:
            raise HTTPException(
                status_code=403,
                detail=f"Requires {min_role} role or higher",
            )
        return user

    return _check


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[dict]:
    """Like get_current_user but returns None if no token (for public routes)."""
    if not credentials:
        return None
    try:
        payload = decode_token(credentials.credentials)
        return {
            "id": payload["sub"],
            "role": payload["role"],
            "username": payload.get("username", ""),
        }
    except HTTPException:
        return None
