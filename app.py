import os
import logging
from typing import Optional
from fastapi import FastAPI, HTTPException, Request, Depends, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from rate_limit import limiter

logging.basicConfig(
    level=logging.WARNING,  # Suppress INFO noise; only show warnings+
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("andavar.app")

from tools.validator import validate_input_request
from agents.root_agent import generate_schema_workflow, run_chat_async
from tools.memory_store import get_history, get_version, get_schema_diff, bootstrap_admin, get_connection
from tools.neon_mcp import get_database_schema_introspection, get_db_tables
from auth import get_current_user, require_role, get_optional_user
from config import settings

# ── Import route modules ──────────────────────────────────────────────────────
from routes.users import router as auth_router, user_router
from routes.projects import router as project_router
from routes.reports import router as report_router

# ── Rate limiter ──────────────────────────────────────────────────────────────
# limiter imported from rate_limit.py (shared instance)

app = FastAPI(
    title="Andavar SQL Assistant",
    description="Conversational AI database assistant powered by Google ADK",
    version="2.0.0",
)

# Attach limiter to app
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS — explicit origin allowlist ──────────────────────────────────────────
_cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Metrics & Instrumentation ────────────────────────────────────────────────
import time
from collections import defaultdict
from fastapi.responses import PlainTextResponse

HTTP_REQUESTS_TOTAL = defaultdict(int)
HTTP_REQUEST_DURATION_SUM = defaultdict(float)
ACTIVE_REQUESTS = 0

@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    global ACTIVE_REQUESTS
    path = request.url.path
    if path == "/metrics":
        return await call_next(request)
    
    method = request.method
    ACTIVE_REQUESTS += 1
    start_time = time.time()
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    except Exception as e:
        status = 500
        raise e
    finally:
        ACTIVE_REQUESTS -= 1
        duration = time.time() - start_time
        HTTP_REQUESTS_TOTAL[(method, path, status)] += 1
        HTTP_REQUEST_DURATION_SUM[(method, path)] += duration

@app.get("/metrics", response_class=PlainTextResponse)
def get_metrics():
    lines = []
    lines.append("# HELP andavar_http_requests_total Total HTTP requests processed.")
    lines.append("# TYPE andavar_http_requests_total counter")
    for (method, path, status), count in HTTP_REQUESTS_TOTAL.items():
        lines.append(f'andavar_http_requests_total{{method="{method}",path="{path}",status="{status}"}} {count}')
        
    lines.append("# HELP andavar_http_request_duration_seconds_sum Sum of HTTP request durations in seconds.")
    lines.append("# TYPE andavar_http_request_duration_seconds_sum counter")
    for (method, path), duration in HTTP_REQUEST_DURATION_SUM.items():
        lines.append(f'andavar_http_request_duration_seconds_sum{{method="{method}",path="{path}"}} {duration:.6f}')
        
    lines.append("# HELP andavar_active_requests Number of concurrent active requests.")
    lines.append("# TYPE andavar_active_requests gauge")
    lines.append(f'andavar_active_requests {ACTIVE_REQUESTS}')
    
    from tools.memory_store import AGENT_RUNS
    lines.append("# HELP andavar_agent_runs_total Total count of specialized agent executions.")
    lines.append("# TYPE andavar_agent_runs_total counter")
    for agent_name, count in AGENT_RUNS.items():
        lines.append(f'andavar_agent_runs_total{{agent="{agent_name}"}} {count}')
        
    conn = None
    try:
        conn = get_connection()
        if conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM av_projects")
                project_count = cur.fetchone()[0]
                lines.append("# HELP andavar_projects_total Total projects managed by Andavar.")
                lines.append("# TYPE andavar_projects_total gauge")
                lines.append(f'andavar_projects_total {project_count}')
                
                cur.execute("SELECT COUNT(*) FROM schema_versions")
                schema_versions = cur.fetchone()[0]
                lines.append("# HELP andavar_schema_versions_total Total schema versions saved.")
                lines.append("# TYPE andavar_schema_versions_total gauge")
                lines.append(f'andavar_schema_versions_total {schema_versions}')
    except Exception:
        pass
    finally:
        if conn:
            conn.close()
            
    return "\n".join(lines) + "\n"

# ── Register routers ──────────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(user_router)
app.include_router(project_router)
app.include_router(report_router)


# ── Startup: bootstrap admin ──────────────────────────────────────────────────
@app.on_event("startup")
def on_startup():
    bootstrap_admin()


# ── Request / Response models ──────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str = Field(..., description="User's message to the assistant")
    session_id: str = Field(..., description="Session identifier for conversation memory")
    project_id: Optional[str] = Field(default=None, description="Active project identifier")


class GenerateRequest(BaseModel):
    prompt: str
    session_id: str
    label: Optional[str] = None
    project_id: Optional[str] = None


class SetupRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: str
    password: str = Field(..., min_length=6)


class ConfirmSqlRequest(BaseModel):
    confirmation_token: str = Field(..., description="Token from execute_write_sql for destructive ops")


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/")
def serve_index():
    frontend_path = os.path.join(os.path.dirname(__file__), "frontend", "index.html")
    if os.path.exists(frontend_path):
        return FileResponse(frontend_path)
    return JSONResponse(status_code=404, content={"error": "frontend/index.html not found"})


@app.get("/api/auth/needs-setup")
def needs_setup():
    """Check if initial admin setup is required."""
    conn = get_connection()
    if not conn:
        return {"needs_setup": True, "reason": "no_database"}
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM av_users")
            count = cur.fetchone()[0]
        return {"needs_setup": count == 0}
    except Exception:
        return {"needs_setup": True, "reason": "table_missing"}
    finally:
        conn.close()


@app.post("/api/auth/setup")
def initial_setup(req: SetupRequest):
    """Create the first admin user (only works when no users exist)."""
    from auth import hash_password, create_token

    conn = get_connection()
    if not conn:
        raise HTTPException(500, "Database not available")
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM av_users")
            if cur.fetchone()[0] > 0:
                raise HTTPException(400, "Setup already completed — users exist")

            pw_hash = hash_password(req.password)
            cur.execute(
                """INSERT INTO av_users (username, email, password_hash, role)
                   VALUES (%s, %s, %s, 'admin') RETURNING id""",
                (req.username, req.email, pw_hash),
            )
            user_id = str(cur.fetchone()[0])
            conn.commit()

        token = create_token(user_id, "admin", req.username)
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": {
                "id": user_id,
                "username": req.username,
                "email": req.email,
                "role": "admin",
                "is_active": True,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        conn.close()


@app.post("/api/chat")
@limiter.limit(settings.rate_limit)
async def chat(request: Request, req: ChatRequest, user: dict = Depends(get_current_user)):
    """Main conversational endpoint — handles all user messages."""
    from tools.memory_store import current_user_role, set_active_project_context
    current_user_role.set(user["role"])
    if req.project_id:
        set_active_project_context(req.project_id)
        
    val = validate_input_request(req.message)
    if val["status"] == "error":
        raise HTTPException(status_code=400, detail=val["error"])
    try:
        reply = await run_chat_async(val["data"], req.session_id)
        return {"reply": reply, "session_id": req.session_id}
    except Exception as e:
        logger.exception("chat endpoint error")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/db/tables")
def db_tables(project_id: Optional[str] = None, user: dict = Depends(get_current_user)):
    """Returns all table names in the connected database (for sidebar)."""
    from tools.memory_store import set_active_project_context
    if project_id:
        set_active_project_context(project_id)
    try:
        tables = get_db_tables()
        return {"tables": tables}
    except Exception as e:
        logger.error(f"db_tables: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/db/status")
def db_status(project_id: Optional[str] = None, user: dict = Depends(get_optional_user)):
    """Returns whether the database is reachable."""
    from tools.memory_store import set_active_project_context
    if project_id:
        set_active_project_context(project_id)
    try:
        tables = get_db_tables()
        return {"connected": True, "table_count": len(tables)}
    except Exception as e:
        return {"connected": False, "error": str(e)}


# ── Destructive SQL confirmation endpoint ─────────────────────────────────────

@app.post("/api/sql/confirm")
def confirm_sql(req: ConfirmSqlRequest, user: dict = Depends(require_role("manager"))):
    """Confirm and execute a previously gated destructive SQL operation.

    This is the REST endpoint counterpart of the confirm_destructive_sql tool.
    The frontend can call this directly with the confirmation_token returned by
    execute_write_sql when it detects a destructive operation.
    """
    from tools.db_tools import confirm_destructive_sql
    result = confirm_destructive_sql(req.confirmation_token)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


# ── Legacy schema endpoints (kept for backward compat) ─────────────────────────

@app.post("/api/schema/generate")
@limiter.limit(settings.rate_limit)
async def generate_schema(request: Request, req: GenerateRequest, user: dict = Depends(require_role("manager"))):
    from tools.memory_store import set_active_project_context
    if req.project_id:
        set_active_project_context(req.project_id)
        
    val = validate_input_request(req.prompt)
    if val["status"] == "error":
        raise HTTPException(status_code=400, detail=val["error"])
    try:
        result = await generate_schema_workflow(val["data"], req.session_id, req.label)
        return result
    except Exception as e:
        logger.exception("generate_schema error")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/schema/history/{session_id}")
def get_schema_history(session_id: str, user: dict = Depends(get_current_user)):
    try:
        return {"session_id": session_id, "history": get_history(session_id)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/db/introspection")
def introspect_database(project_id: Optional[str] = None, user: dict = Depends(get_current_user)):
    from tools.memory_store import set_active_project_context
    if project_id:
        set_active_project_context(project_id)
    try:
        schema_info = get_database_schema_introspection()
        return {"status": "success", "schema": schema_info}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8001))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
