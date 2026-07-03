"""User management routes — registration, login, user CRUD."""

import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException

from auth import (
    get_current_user,
    require_role,
    hash_password,
    verify_password,
    create_token,
)
from models import UserCreate, UserLogin, UserResponse, UserUpdate, TokenResponse
from tools.memory_store import get_connection

logger = logging.getLogger("andavar.routes.users")
router = APIRouter(prefix="/api/auth", tags=["auth"])
user_router = APIRouter(prefix="/api/users", tags=["users"])


# ── Auth ──────────────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
def login(req: UserLogin):
    conn = get_connection()
    if not conn:
        raise HTTPException(500, "Database not available")
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, username, email, password_hash, role, is_active FROM av_users WHERE email = %s",
                (req.email,),
            )
            row = cur.fetchone()
        if not row:
            raise HTTPException(401, "Invalid credentials")
        uid, username, email, pw_hash, role, is_active = row
        if not is_active:
            raise HTTPException(403, "Account deactivated")
        if not verify_password(req.password, pw_hash):
            raise HTTPException(401, "Invalid credentials")

        token = create_token(str(uid), role, username)
        return TokenResponse(
            access_token=token,
            user=UserResponse(
                id=str(uid), username=username, email=email,
                role=role, is_active=is_active,
            ),
        )
    finally:
        conn.close()


@router.get("/me", response_model=UserResponse)
def get_me(user: dict = Depends(get_current_user)):
    conn = get_connection()
    if not conn:
        raise HTTPException(500, "Database not available")
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, username, email, role, is_active, created_at FROM av_users WHERE id = %s::uuid",
                (user["id"],),
            )
            row = cur.fetchone()
        if not row:
            raise HTTPException(404, "User not found")
        return UserResponse(
            id=str(row[0]), username=row[1], email=row[2],
            role=row[3], is_active=row[4],
            created_at=str(row[5]) if row[5] else None,
        )
    finally:
        conn.close()


# ── User Management (admin only) ─────────────────────────────────────────────

@user_router.get("", response_model=List[UserResponse])
def list_users(user: dict = Depends(require_role("admin"))):
    conn = get_connection()
    if not conn:
        raise HTTPException(500, "Database not available")
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, username, email, role, is_active, created_at FROM av_users ORDER BY created_at"
            )
            rows = cur.fetchall()
        return [
            UserResponse(
                id=str(r[0]), username=r[1], email=r[2],
                role=r[3], is_active=r[4],
                created_at=str(r[5]) if r[5] else None,
            )
            for r in rows
        ]
    finally:
        conn.close()


@user_router.post("", response_model=UserResponse, status_code=201)
def create_user(req: UserCreate, user: dict = Depends(require_role("admin"))):
    conn = get_connection()
    if not conn:
        raise HTTPException(500, "Database not available")
    try:
        pw_hash = hash_password(req.password)
        with conn.cursor() as cur:
            # Check uniqueness
            cur.execute(
                "SELECT id FROM av_users WHERE email = %s OR username = %s",
                (req.email, req.username),
            )
            if cur.fetchone():
                raise HTTPException(409, "User with that email or username already exists")
            cur.execute(
                """INSERT INTO av_users (username, email, password_hash, role)
                   VALUES (%s, %s, %s, %s) RETURNING id, created_at""",
                (req.username, req.email, pw_hash, req.role),
            )
            new_id, created_at = cur.fetchone()
            conn.commit()
        return UserResponse(
            id=str(new_id), username=req.username, email=req.email,
            role=req.role, is_active=True,
            created_at=str(created_at) if created_at else None,
        )
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"create_user: {e}")
        raise HTTPException(500, str(e))
    finally:
        conn.close()


@user_router.patch("/{user_id}", response_model=UserResponse)
def update_user(user_id: str, req: UserUpdate, user: dict = Depends(require_role("admin"))):
    conn = get_connection()
    if not conn:
        raise HTTPException(500, "Database not available")
    try:
        updates = []
        params = []
        if req.role is not None:
            updates.append("role = %s")
            params.append(req.role)
        if req.is_active is not None:
            updates.append("is_active = %s")
            params.append(req.is_active)
        if not updates:
            raise HTTPException(400, "No fields to update")

        updates.append("updated_at = NOW()")
        params.append(user_id)

        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE av_users SET {', '.join(updates)} WHERE id = %s::uuid "
                f"RETURNING id, username, email, role, is_active, created_at",
                params,
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "User not found")
            conn.commit()
        return UserResponse(
            id=str(row[0]), username=row[1], email=row[2],
            role=row[3], is_active=row[4],
            created_at=str(row[5]) if row[5] else None,
        )
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        conn.close()


@user_router.delete("/{user_id}")
def delete_user(user_id: str, user: dict = Depends(require_role("admin"))):
    if user_id == user["id"]:
        raise HTTPException(400, "Cannot delete yourself")
    conn = get_connection()
    if not conn:
        raise HTTPException(500, "Database not available")
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM av_users WHERE id = %s::uuid RETURNING id", (user_id,))
            if not cur.fetchone():
                raise HTTPException(404, "User not found")
            conn.commit()
        return {"deleted": True}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        conn.close()
