import json
import logging
import contextvars
from typing import Dict, Any, List, Optional
import psycopg2
from psycopg2.extras import RealDictCursor
from config import settings
from tools.schema_diff import diff_schemas, format_diff_markdown

logger = logging.getLogger("andavar.memory_store")

# ── ContextVars for per-request isolation ──────────────────────────────────────
active_project_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("active_project_id", default=None)
active_project_api_key: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("active_project_api_key", default=None)
active_project_model: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("active_project_model", default=None)
current_user_role: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("current_user_role", default=None)

# In-memory storage fallback for local development or connection failures
_in_memory_db: Dict[str, List[Dict[str, Any]]] = {}

# Metrics tracker for specialized agent executions
AGENT_RUNS: Dict[str, int] = {
    "schema_designer": 0,
    "sql_generator": 0,
    "explainer": 0,
    "mock_data_generator": 0,
    "andavar_chat": 0
}

def _clean_db_url(url: str) -> str:
    """Remove parameters unsupported by psycopg2 (e.g. channel_binding)."""
    import re
    return re.sub(r"[&?]channel_binding=[^&]*", "", url)

def set_active_project_context(project_id: str):
    """Fetch project details from main DB and set ContextVars for database, api_key and model."""
    from tools.crypto import decrypt
    active_project_id.set(project_id)
    
    conn = get_connection(project_aware=False)
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT database_url, api_key, gemini_model FROM av_projects WHERE id = %s::uuid",
                    (project_id,)
                )
                row = cur.fetchone()
                if row:
                    active_project_api_key.set(decrypt(row[1]))
                    active_project_model.set(row[2])
        except Exception as e:
            logger.error(f"Error setting project context for {project_id}: {e}")
        finally:
            conn.close()

def get_connection(project_aware: bool = False):
    """Returns a PostgreSQL connection if DATABASE_URL is configured, else None.
    If project_aware=True and active_project_id is set, returns connection to the project's DB URL.
    """
    if project_aware:
        from tools.crypto import decrypt
        p_id = active_project_id.get()
        if p_id:
            main_conn = get_connection(project_aware=False)
            if main_conn:
                try:
                    with main_conn.cursor() as cur:
                        cur.execute(
                            "SELECT database_url, api_key, gemini_model FROM av_projects WHERE id = %s::uuid",
                            (p_id,)
                        )
                        row = cur.fetchone()
                        if row:
                            db_url = decrypt(row[0])
                            if not active_project_api_key.get():
                                active_project_api_key.set(decrypt(row[1]))
                            if not active_project_model.get():
                                active_project_model.set(row[2])
                            
                            clean_url = _clean_db_url(db_url)
                            conn = psycopg2.connect(clean_url, connect_timeout=5)
                            return conn
                except Exception as e:
                    logger.error(f"Failed to connect to project database {p_id}: {e}")
                    return None
                finally:
                    main_conn.close()

    raw_url = settings.database_url or ""
    if not raw_url or ("postgres://" not in raw_url and "postgresql://" not in raw_url):
        return None
    url = _clean_db_url(raw_url)
    try:
        conn = psycopg2.connect(url, connect_timeout=5)
        return conn
    except Exception as e:
        logger.warning(
            f"Failed to connect to database: {e}. Falling back to in-memory store."
        )
        return None

def init_db():
    """Initializes all required tables in the database if connected."""
    conn = get_connection()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            # ── Andavar Users (av_ prefix to avoid clash with existing tables) ──
            cur.execute("""
                CREATE TABLE IF NOT EXISTS av_users (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    username VARCHAR(50) UNIQUE NOT NULL,
                    email VARCHAR(255) UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role VARCHAR(20) NOT NULL DEFAULT 'guest'
                        CHECK (role IN ('admin', 'manager', 'guest')),
                    is_active BOOLEAN DEFAULT true,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)

            # ── Projects ──────────────────────────────────────
            cur.execute("""
                CREATE TABLE IF NOT EXISTS av_projects (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    name VARCHAR(100) NOT NULL,
                    description TEXT,
                    database_url TEXT NOT NULL,
                    api_key TEXT NOT NULL,
                    gemini_model VARCHAR(50) DEFAULT 'gemini-2.5-flash-lite',
                    created_by UUID REFERENCES av_users(id) ON DELETE SET NULL,
                    is_active BOOLEAN DEFAULT true,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)

            # ── Schema versions (keep original name, add project FK) ──────────
            cur.execute("""
                CREATE TABLE IF NOT EXISTS schema_versions (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    session_id UUID NOT NULL,
                    version_number INTEGER NOT NULL,
                    label TEXT,
                    schema_json JSONB NOT NULL,
                    sql_output TEXT NOT NULL,
                    explanation TEXT NOT NULL,
                    mock_data_sql TEXT,
                    project_id UUID REFERENCES av_projects(id) ON DELETE CASCADE,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_schema_versions_session ON schema_versions(session_id);")

            # Add project_id column if missing (migration for existing DBs)
            cur.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'schema_versions' AND column_name = 'project_id'
                    ) THEN
                        ALTER TABLE schema_versions
                            ADD COLUMN project_id UUID REFERENCES av_projects(id) ON DELETE CASCADE;
                    END IF;
                END $$;
            """)

            # Add mock_data_sql column if missing
            cur.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'schema_versions' AND column_name = 'mock_data_sql'
                    ) THEN
                        ALTER TABLE schema_versions
                            ADD COLUMN mock_data_sql TEXT;
                    END IF;
                END $$;
            """)

            # ── Reports ───────────────────────────────────────
            cur.execute("""
                CREATE TABLE IF NOT EXISTS av_reports (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    project_id UUID REFERENCES av_projects(id) ON DELETE CASCADE,
                    generated_by UUID REFERENCES av_users(id) ON DELETE SET NULL,
                    title VARCHAR(200) NOT NULL,
                    report_type VARCHAR(50) NOT NULL,
                    content_json JSONB NOT NULL,
                    content_markdown TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)

            # Drop check constraint to support new report/export types dynamically
            cur.execute("""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.constraint_column_usage
                        WHERE table_name = 'av_reports' AND constraint_name = 'av_reports_report_type_check'
                    ) THEN
                        ALTER TABLE av_reports DROP CONSTRAINT av_reports_report_type_check;
                    END IF;
                END $$;
            """)

            conn.commit()
            logger.info("Database initialized successfully (all tables).")
    except Exception as e:
        logger.error(f"Error initializing database tables: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

# Initialize DB tables on module import
init_db()

def save_version(
    session_id: str,
    schema_json: Dict[str, Any],
    sql_output: str,
    explanation: str,
    label: Optional[str] = None,
    project_id: Optional[str] = None,
    mock_data_sql: Optional[str] = None,
) -> int:
    conn = get_connection()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COALESCE(MAX(version_number), 0) FROM schema_versions WHERE session_id = %s",
                    (session_id,)
                )
                max_ver = cur.fetchone()[0]
                next_ver = max_ver + 1
                cur.execute(
                    """INSERT INTO schema_versions (session_id, version_number, label, schema_json, sql_output, explanation, project_id, mock_data_sql)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (session_id, next_ver, label, json.dumps(schema_json), sql_output, explanation,
                     project_id if project_id else None, mock_data_sql)
                )
                conn.commit()
                return next_ver
        except Exception as e:
            logger.error(f"Error saving version to DB: {e}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()

    # In-memory fallback
    if session_id not in _in_memory_db:
        _in_memory_db[session_id] = []
    next_ver = len(_in_memory_db[session_id]) + 1
    _in_memory_db[session_id].append({
        "session_id": session_id, "version_number": next_ver,
        "label": label or f"v{next_ver}", "schema_json": schema_json,
        "sql_output": sql_output, "explanation": explanation,
        "mock_data_sql": mock_data_sql,
    })
    return next_ver

def get_history(session_id: str) -> List[Dict[str, Any]]:
    conn = get_connection()
    if conn:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT version_number, label, created_at FROM schema_versions WHERE session_id = %s ORDER BY version_number ASC",
                    (session_id,)
                )
                return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            logger.error(f"Error reading history from DB: {e}")
        finally:
            if conn:
                conn.close()
    versions = _in_memory_db.get(session_id, [])
    return [{"version_number": v["version_number"], "label": v["label"], "created_at": "in-memory"} for v in versions]

def get_version(session_id: str, version_number: int) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    if conn:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT version_number, label, schema_json, sql_output, explanation, mock_data_sql, created_at FROM schema_versions WHERE session_id = %s AND version_number = %s",
                    (session_id, version_number)
                )
                row = cur.fetchone()
                if row:
                    res = dict(row)
                    if isinstance(res["schema_json"], str):
                        res["schema_json"] = json.loads(res["schema_json"])
                    return res
        except Exception as e:
            logger.error(f"Error getting version from DB: {e}")
        finally:
            if conn:
                conn.close()
    versions = _in_memory_db.get(session_id, [])
    for v in versions:
        if v["version_number"] == version_number:
            return v
    return None

def get_latest_version(session_id: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    if conn:
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT version_number, label, schema_json, sql_output, explanation, mock_data_sql, created_at FROM schema_versions WHERE session_id = %s ORDER BY version_number DESC LIMIT 1",
                    (session_id,)
                )
                row = cur.fetchone()
                if row:
                    res = dict(row)
                    if isinstance(res["schema_json"], str):
                        res["schema_json"] = json.loads(res["schema_json"])
                    return res
        except Exception as e:
            logger.error(f"Error getting latest version from DB: {e}")
        finally:
            if conn:
                conn.close()
    versions = _in_memory_db.get(session_id, [])
    return versions[-1] if versions else None

def get_schema_diff(session_id: str, v1: int, v2: int) -> Dict[str, Any]:
    ver1 = get_version(session_id, v1)
    ver2 = get_version(session_id, v2)
    if not ver1 or not ver2:
        return {"error": "One or both versions not found"}
    diff_data = diff_schemas(ver1["schema_json"], ver2["schema_json"])
    return {"v1": v1, "v2": v2, "diff": diff_data, "markdown": format_diff_markdown(diff_data)}


def bootstrap_admin():
    """Create the first admin user from env vars if no users exist."""
    from auth import hash_password

    conn = get_connection()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM av_users")
            count = cur.fetchone()[0]
            if count > 0:
                return

            email = settings.admin_email
            password = settings.admin_password
            username = settings.admin_username

            if not email or not password:
                logger.info(
                    "No users exist and ADMIN_EMAIL/ADMIN_PASSWORD not set. "
                    "First login via /setup will create the admin account."
                )
                return

            pw_hash = hash_password(password)
            cur.execute(
                """INSERT INTO av_users (username, email, password_hash, role)
                   VALUES (%s, %s, %s, 'admin') ON CONFLICT (email) DO NOTHING""",
                (username, email, pw_hash),
            )
            conn.commit()
            logger.info(f"Bootstrap admin created: {email}")
    except Exception as e:
        logger.error(f"bootstrap_admin: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()
