"""Project management routes — CRUD, test connection, per-project config."""

import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException

from auth import get_current_user, require_role
from models import ProjectCreate, ProjectUpdate, ProjectResponse, ProjectDetail
from tools.memory_store import get_connection
from tools.crypto import encrypt, decrypt, mask_url

logger = logging.getLogger("andavar.routes.projects")
router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=List[ProjectResponse])
def list_projects(user: dict = Depends(get_current_user)):
    conn = get_connection()
    if not conn:
        raise HTTPException(500, "Database not available")
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, name, description, database_url, api_key,
                          gemini_model, is_active, created_by, created_at, updated_at
                   FROM av_projects ORDER BY created_at DESC"""
            )
            rows = cur.fetchall()
        return [
            ProjectResponse(
                id=str(r[0]), name=r[1], description=r[2],
                gemini_model=r[5], is_active=r[6],
                created_by=str(r[7]) if r[7] else None,
                created_at=str(r[8]) if r[8] else None,
                updated_at=str(r[9]) if r[9] else None,
                database_url_masked=mask_url(decrypt(r[3]) if r[3] else ""),
                has_api_key=bool(r[4]),
            )
            for r in rows
        ]
    finally:
        conn.close()


@router.get("/{project_id}")
def get_project(project_id: str, user: dict = Depends(get_current_user)):
    conn = get_connection()
    if not conn:
        raise HTTPException(500, "Database not available")
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, name, description, database_url, api_key,
                          gemini_model, is_active, created_by, created_at, updated_at
                   FROM av_projects WHERE id = %s::uuid""",
                (project_id,),
            )
            r = cur.fetchone()
        if not r:
            raise HTTPException(404, "Project not found")

        # Admin gets full detail, others get masked
        if user["role"] == "admin":
            return ProjectDetail(
                id=str(r[0]), name=r[1], description=r[2],
                database_url=decrypt(r[3]) if r[3] else None,
                api_key=decrypt(r[4]) if r[4] else None,
                gemini_model=r[5], is_active=r[6],
                created_by=str(r[7]) if r[7] else None,
                created_at=str(r[8]) if r[8] else None,
                updated_at=str(r[9]) if r[9] else None,
                database_url_masked=mask_url(decrypt(r[3]) if r[3] else ""),
                has_api_key=bool(r[4]),
            )
        return ProjectResponse(
            id=str(r[0]), name=r[1], description=r[2],
            gemini_model=r[5], is_active=r[6],
            created_by=str(r[7]) if r[7] else None,
            created_at=str(r[8]) if r[8] else None,
            updated_at=str(r[9]) if r[9] else None,
            database_url_masked=mask_url(decrypt(r[3]) if r[3] else ""),
            has_api_key=bool(r[4]),
        )
    finally:
        conn.close()


@router.post("", response_model=ProjectResponse, status_code=201)
def create_project(req: ProjectCreate, user: dict = Depends(require_role("admin"))):
    conn = get_connection()
    if not conn:
        raise HTTPException(500, "Database not available")
    try:
        enc_url = encrypt(req.database_url)
        enc_key = encrypt(req.api_key)
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO av_projects (name, description, database_url, api_key, gemini_model, created_by)
                   VALUES (%s, %s, %s, %s, %s, %s::uuid)
                   RETURNING id, created_at""",
                (req.name, req.description, enc_url, enc_key, req.gemini_model, user["id"]),
            )
            new_id, created_at = cur.fetchone()
            conn.commit()
        return ProjectResponse(
            id=str(new_id), name=req.name, description=req.description,
            gemini_model=req.gemini_model, is_active=True,
            created_by=user["id"],
            created_at=str(created_at) if created_at else None,
            database_url_masked=mask_url(req.database_url),
            has_api_key=True,
        )
    except Exception as e:
        conn.rollback()
        logger.error(f"create_project: {e}")
        raise HTTPException(500, str(e))
    finally:
        conn.close()


@router.patch("/{project_id}", response_model=ProjectResponse)
def update_project(project_id: str, req: ProjectUpdate, user: dict = Depends(require_role("admin"))):
    conn = get_connection()
    if not conn:
        raise HTTPException(500, "Database not available")
    try:
        updates = []
        params = []
        if req.name is not None:
            updates.append("name = %s")
            params.append(req.name)
        if req.description is not None:
            updates.append("description = %s")
            params.append(req.description)
        if req.database_url is not None:
            updates.append("database_url = %s")
            params.append(encrypt(req.database_url))
        if req.api_key is not None:
            updates.append("api_key = %s")
            params.append(encrypt(req.api_key))
        if req.gemini_model is not None:
            updates.append("gemini_model = %s")
            params.append(req.gemini_model)
        if req.is_active is not None:
            updates.append("is_active = %s")
            params.append(req.is_active)
        if not updates:
            raise HTTPException(400, "No fields to update")

        updates.append("updated_at = NOW()")
        params.append(project_id)

        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE av_projects SET {', '.join(updates)} WHERE id = %s::uuid "
                f"RETURNING id, name, description, database_url, api_key, gemini_model, is_active, created_by, created_at, updated_at",
                params,
            )
            r = cur.fetchone()
            if not r:
                raise HTTPException(404, "Project not found")
            conn.commit()
        return ProjectResponse(
            id=str(r[0]), name=r[1], description=r[2],
            gemini_model=r[5], is_active=r[6],
            created_by=str(r[7]) if r[7] else None,
            created_at=str(r[8]) if r[8] else None,
            updated_at=str(r[9]) if r[9] else None,
            database_url_masked=mask_url(decrypt(r[3]) if r[3] else ""),
            has_api_key=bool(r[4]),
        )
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        conn.close()


@router.delete("/{project_id}")
def delete_project(project_id: str, user: dict = Depends(require_role("admin"))):
    conn = get_connection()
    if not conn:
        raise HTTPException(500, "Database not available")
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM av_projects WHERE id = %s::uuid RETURNING id", (project_id,))
            if not cur.fetchone():
                raise HTTPException(404, "Project not found")
            conn.commit()
        return {"deleted": True}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        conn.close()


@router.post("/{project_id}/test-connection")
def test_connection(project_id: str, user: dict = Depends(require_role("admin"))):
    """Test if the project's database URL is reachable."""
    import psycopg2
    import re

    conn = get_connection()
    if not conn:
        raise HTTPException(500, "Database not available")
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT database_url FROM av_projects WHERE id = %s::uuid", (project_id,))
            row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Project not found")

        db_url = decrypt(row[0])
        # Clean URL for psycopg2
        clean_url = re.sub(r"[&?]channel_binding=[^&]*", "", db_url)
        test_conn = psycopg2.connect(clean_url, connect_timeout=5)
        with test_conn.cursor() as cur:
            cur.execute("SELECT 1")
        test_conn.close()
        return {"connected": True, "message": "Connection successful"}
    except psycopg2.Error as e:
        return {"connected": False, "message": str(e)}
    except Exception as e:
        return {"connected": False, "message": str(e)}
    finally:
        conn.close()
