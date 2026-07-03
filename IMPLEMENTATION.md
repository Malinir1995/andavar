# Andavar — Implementation Reference

> **Capstone Track:** Agents for Business
> **Kaggle Course:** 5-Day AI Agents: Intensive Vibe Coding Course with Google (2026)
> **Deadline:** July 6, 2026

---

## 1. Project Overview

Andavar is a multi-agent AI system that converts plain-English system descriptions
into production-ready PostgreSQL schemas. It targets developers, architects, and
students who need to rapidly design and iterate on relational database schemas
without writing DDL by hand.

The name **Andavar** (Tamil: "the one who governs / the lord") reflects the
agent's role as the authoritative designer of data structure.

---

## 2. Capstone Criteria Coverage

| Criterion | How Andavar covers it |
|---|---|
| Multi-agent systems (ADK) | Root agent orchestrates 3 specialist agents |
| Agent Memory / Sessions | Schema version history stored per session |
| MCP Servers | NeonDB MCP for live schema introspection |
| Security Features | Input validation, prompt injection detection, DDL-only guardrail |
| Production Deployment | Docker + docker-compose, NeonDB cloud, configurable env |
| Agent Skills | Antigravity SKILL.md for IDE integration |

---

## 3. System Architecture

```
┌─────────────────────────────────────────────┐
│                  Frontend                   │
│         (Vanilla JS + HTML — dark UI)       │
└─────────────────┬───────────────────────────┘
                  │ HTTP (REST)
┌─────────────────▼───────────────────────────┐
│              FastAPI Backend                │
│                  app.py                     │
│   /generate  /history  /validate  /health   │
└─────────────────┬───────────────────────────┘
                  │ ADK Runner
┌─────────────────▼───────────────────────────┐
│              Root Agent                     │
│           (Orchestrator — ADK)              │
└──────┬──────────┬──────────────┬────────────┘
       │          │              │
┌──────▼───┐ ┌────▼──────┐ ┌────▼──────────┐
│ Schema   │ │ SQL       │ │ Explainer     │
│ Designer │ │ Generator │ │ Agent         │
│ Agent    │ │ Agent     │ │               │
└──────┬───┘ └────┬──────┘ └────┬──────────┘
       │          │              │
┌──────▼──────────▼──────────────▼──────────┐
│                  Tools                     │
│  validator.py  │  memory_store.py          │
│  neon_mcp.py   │  schema_diff.py           │
└────────────────────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────┐
│           Database Layer                    │
│   NeonDB (cloud) ←→ PostgreSQL (local)      │
└─────────────────────────────────────────────┘
```

---

## 4. Agent Definitions

### 4.1 Root Agent (`root_agent.py`)
- **Model:** `gemini-2.5-flash`
- **Role:** Receives user input, routes to specialist agents in sequence, assembles final response
- **Tools:** `AgentTool(schema_designer)`, `AgentTool(sql_generator)`, `AgentTool(explainer)`, `validate_input`
- **Memory:** Maintains schema version list per session via `InMemorySessionService`

### 4.2 Schema Designer Agent (`schema_designer.py`)
- **Model:** `gemini-2.5-flash`
- **Role:** Parses natural language, identifies entities and relationships, proposes normalised schema
- **Output:** Structured JSON — tables, columns, types, constraints, relationships

### 4.3 SQL Generator Agent (`sql_generator.py`)
- **Model:** `gemini-2.5-flash`
- **Role:** Converts schema JSON to PostgreSQL DDL
- **Rules enforced:**
  - UUID primary keys (`gen_random_uuid()`)
  - `TIMESTAMPTZ` for all timestamps
  - Explicit `ON DELETE` on all foreign keys
  - Index on all foreign key columns
  - Snake_case naming

### 4.4 Explainer Agent (`explainer.py`)
- **Model:** `gemini-2.5-flash`
- **Role:** Produces plain-English rationale — why each table, what each relationship means, trade-offs
- **Output:** Markdown formatted explanation

---

## 5. Tools

### 5.1 `validator.py`
- Sanitises user input before LLM processing
- Detects prompt injection patterns (role overrides, jailbreak attempts)
- Validates generated SQL is DDL-only (blocks DML)
- Returns structured `{status, data, error}` dict

### 5.2 `memory_store.py`
- Stores schema versions per session ID
- Supports: `save_version`, `get_history`, `get_version(n)`, `diff(v1, v2)`
- Backend: in-memory dict (dev) → NeonDB table `schema_versions` (prod)

### 5.3 `neon_mcp.py`
- Wraps NeonDB MCP server for live schema introspection
- Allows agent to read existing tables and suggest migrations
- Configurable: `DATABASE_URL` env var switches between local PG and NeonDB

### 5.4 `schema_diff.py`
- Computes diff between two schema versions
- Returns added/removed/modified tables and columns

---

## 6. API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| POST | `/generate` | Main: takes user prompt, returns schema + SQL + explanation |
| GET | `/history/{session_id}` | Returns list of schema versions for session |
| GET | `/version/{session_id}/{n}` | Returns specific schema version |
| POST | `/validate` | Validates a schema JSON or SQL string |
| GET | `/health` | Health check |

### Request Schema (`/generate`)
```json
{
  "prompt": "Design a schema for a multi-tenant SaaS billing platform",
  "session_id": "uuid-string",
  "version_label": "v1"
}
```

### Response Schema
```json
{
  "session_id": "uuid-string",
  "version": 1,
  "schema_design": { ... },
  "sql": "CREATE TABLE ...",
  "explanation": "markdown string",
  "timestamp": "2026-06-20T10:00:00Z"
}
```

---

## 7. Database Configuration

### Local (Docker)
```env
DATABASE_URL=postgresql://andavar:andavar@postgres:5432/andavar
```

### NeonDB (Cloud)
```env
DATABASE_URL=postgresql://user:pass@ep-xxx.neon.tech/andavar?sslmode=require
```

Switching is handled by a single `DATABASE_URL` env var — no code changes needed.

### NeonDB Tables (used by Andavar itself)
```sql
CREATE TABLE schema_versions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID NOT NULL,
  version_number INTEGER NOT NULL,
  label TEXT,
  schema_json JSONB NOT NULL,
  sql_output TEXT NOT NULL,
  explanation TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_schema_versions_session ON schema_versions(session_id);
```

---

## 8. Security Implementation

| Layer | Control |
|---|---|
| Input | Regex + LLM-based prompt injection detection |
| Agent | DDL-only guardrail — SQL generator blocked from producing DML |
| API | Rate limiting via `slowapi` |
| DB | Read-only NeonDB role for introspection MCP |
| Secrets | All via env vars, never hardcoded |
| Docker | Non-root user in container |

---

## 9. Tech Stack

| Component | Technology |
|---|---|
| Agent Framework | Google ADK (`google-adk`) |
| LLM | Gemini 2.5 Flash |
| Backend | FastAPI + uvicorn |
| Frontend | Vanilla JS + HTML (single file, dark terminal aesthetic) |
| Database | PostgreSQL (local) / NeonDB (cloud) |
| Package Manager | uv |
| Containerisation | Docker + docker-compose |
| MCP | NeonDB MCP server |
| Retry | `types.HttpRetryOptions` (ADK) |

---

## 10. Project Structure

```
andavar/
├── agents/
│   ├── __init__.py
│   ├── root_agent.py
│   ├── schema_designer.py
│   ├── sql_generator.py
│   └── explainer.py
├── tools/
│   ├── __init__.py
│   ├── validator.py
│   ├── memory_store.py
│   ├── neon_mcp.py
│   └── schema_diff.py
├── frontend/
│   └── index.html
├── app.py
├── config.py
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── .env.example
├── SKILL.md
├── IMPLEMENTATION.md
└── README.md
```

---

## 11. Deployment

### Docker (local/self-hosted)
```bash
docker compose up --build
# UI: http://localhost:8000
```

### Environment Variables
```env
GOOGLE_API_KEY=your_gemini_key
DATABASE_URL=postgresql://...
ENVIRONMENT=development   # or production
LOG_LEVEL=INFO
```

---

## 12. Configuration Reference

### `.env` File (copy from `.env.example`, never commit)
```env
# ── LLM ──────────────────────────────────────────────
GOOGLE_API_KEY=your_gemini_api_key_here

# ── Database ──────────────────────────────────────────
# Local PostgreSQL (Docker):
DATABASE_URL=postgresql://andavar:andavar@postgres:5432/andavar

# NeonDB (Cloud — replace with your Neon connection string):
# DATABASE_URL=postgresql://user:pass@ep-xxx-yyy.us-east-2.aws.neon.tech/andavar?sslmode=require

# ── App ───────────────────────────────────────────────
ENVIRONMENT=development        # development | production
LOG_LEVEL=INFO
PORT=8000

# ── Security ──────────────────────────────────────────
RATE_LIMIT=30/minute           # requests per IP
SECRET_KEY=change_this_in_prod # used for session signing
```

### Where Each Value Comes From

| Variable | Where to get it |
|---|---|
| `GOOGLE_API_KEY` | [Google AI Studio](https://aistudio.google.com) → API Keys |
| `DATABASE_URL` (NeonDB) | [Neon Console](https://console.neon.tech) → Project → Connection string → select **Python** |
| `DATABASE_URL` (local) | Pre-filled in `docker-compose.yml`, no action needed |
| `SECRET_KEY` | Run `python -c "import secrets; print(secrets.token_hex(32))"` |

### Switching Between Local and NeonDB
Only one line changes — the `DATABASE_URL` in `.env`. Everything else (agents, tools, API) stays identical.

```bash
# Use local PostgreSQL (default for dev)
DATABASE_URL=postgresql://andavar:andavar@postgres:5432/andavar

# Use NeonDB (production / Kaggle demo)
DATABASE_URL=postgresql://user:pass@ep-xxx.neon.tech/andavar?sslmode=require
```

### `config.py` (loads all env vars in one place)
```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    google_api_key: str
    database_url: str
    environment: str = "development"
    log_level: str = "INFO"
    port: int = 8000
    rate_limit: str = "30/minute"
    secret_key: str = "change_this"

    class Config:
        env_file = ".env"

settings = Settings()
```

Every agent and tool imports from `config.py` — never reads env vars directly.

---

## 13. Submission Checklist



- [ ] All 3 agents implemented and tested
- [ ] Memory/session versioning working
- [ ] NeonDB MCP integration live
- [ ] Security guardrails tested (prompt injection, DDL-only)
- [ ] Docker compose running end-to-end
- [ ] Frontend functional
- [ ] Kaggle notebook writeup complete
- [ ] Video walkthrough recorded
- [ ] GitHub repo public with README
- [ ] Submitted before July 6, 2026 11:59 PM PT

---

## 14. Phase 2 Features (Planned)

The following features have been spec'd for Phase 2 to upgrade the application to a pro-tier developer tool:

### 14.1 UI & Aesthetics Overhaul
- **Remove Emojis:** Strip emojis globally. Use custom monochrome SVG icons (e.g., Lucide or Heroicons).
- **Premium Design:** Enforce glassmorphism, precise typography (Outfit/Inter), and consistent dark mode (`#0f172a` backgrounds with `#8b5cf6` accents) across both the Website and Dashboard UI.

### 14.2 Export Module (Replacing Reports)
The static PDF/Markdown report feature (`/api/reports`) will be replaced with developer-ready exports:
- **ORM Models:** Generate `schema.prisma` or SQLAlchemy `models.py`.
- **Mermaid ERD:** Output interactive Entity-Relationship Diagrams based on the schema JSON.
- **Standalone SQL:** Clean `migration_init.sql` downloads.

### 14.3 Synthetic Data Agent ("Mock Agent")
- **Role:** A 4th agent (`mock_data_generator.py`) that generates context-aware, realistic `INSERT` statements for the finalized schema.
- **Execution:** Runs post-SQL generation to provide instant test data.

### 14.4 Schema Migrations (ALTER TABLE)
- **Role:** Upgrades `sql_generator.py` to handle incremental diffs.
- **Workflow:** 
  1. Fetch live schema via Neon MCP.
  2. Compare against new user prompt (e.g., "Add stripe_id to users").
  3. Output precise `ALTER TABLE` statements rather than full `CREATE TABLE` scripts.
