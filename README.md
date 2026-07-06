# Andavar — Multi-Agent SQL & Schema Assistant

Andavar is an intelligent, professional-grade, multi-agent database schema designer and management assistant. Powered by Google Gemini and integrated with the Neon Model Context Protocol (MCP) server, Andavar transforms natural language descriptions of data requirements into production-ready, fully-normalized relational schemas, DDL scripts, Python ORM models, Prisma files, Mermaid ERDs, and context-aware mock data.

---

## 📖 Table of Contents
1. [Core Concept & Value](#-core-concept--value)
2. [Problem Statement](#-problem-statement)
3. [The Solution](#-the-solution)
4. [Multi-Agent Architecture](#-multi-agent-architecture)
5. [Neon MCP Server & Database Migrations](#-neon-mcp-server--database-migrations)
6. [RFC 10008: Safe HTTP QUERY Method Integration](#-rfc-10008-safe-http-query-method-integration)
7. [🚀 Features](#-features)
8. [🛠️ Technical Setup & Installation](#%EF%B8%8F-technical-setup--installation)
9. [🔐 Security & Multi-Tenancy](#-security--multi-tenancy)

---

## 💡 Core Concept & Value

Database schema design is a highly specialized skill. Poor decisions early in a system's lifecycle—such as improper normalization, missing indexes, or weak foreign key constraints—lead to performance degradation, data corruption, and high maintenance costs.

Andavar solves this by orchestrating a **network of collaborative AI agents** that work together to act as a virtual principal database administrator. By breaking the design down into specialized tasks, Andavar achieves a level of schema consistency, normal form correctness, and security checking that single-agent LLM systems cannot match.

---

## ⚠️ Problem Statement

Modern software developers face three key bottlenecks when setting up databases:
1. **Design Friction:** Translating ambiguous business requirements into Third Normal Form (3NF) relational tables is error-prone.
2. **Infrastructure Disconnect:** Live databases quickly drift from design files, making incremental migrations (`ALTER TABLE`) difficult to manage without breaking existing records.
3. **Seed Data Shortage:** Testing schemas requires realistic, structurally valid mock insert statements that respect foreign key constraints.

---

## ⚡ The Solution

Andavar provides an integrated playground where developers can:
1. Speak to the assistant to design a database.
2. Auto-generate standard migration SQL or full initial DDL scripts.
3. Automatically generate context-aware, relationally-sound insert scripts (mock data).
4. Download developer-ready code artifacts (Prisma, SQLAlchemy, Mermaid ERDs).
5. Interactively compare live Neon databases and generate safe, zero-downtime migrations.

---

## 🏗️ Multi-Agent Architecture

Andavar uses a structured multi-agent paradigm:

```mermaid
graph TD
    User([Developer / Client]) -->|Natural Language Prompt| RootAgent[Root Orchestrator Agent]
    
    subgraph Multi-Agent pipeline
        RootAgent -->|1. Analyze & Structure| SchemaDesigner[Schema Designer Agent]
        SchemaDesigner -->|JSON Schema Design| SQLGenerator[SQL Generator Agent]
        SQLGenerator -->|Normalized SQL DDL / Migrations| Explainer[Explainer Agent]
        SQLGenerator -->|SQL Schema Structure| MockGenerator[Mock Data Agent]
    end
    
    Explainer -->|Plain-English Analysis| ResponseBuilder[Response Compiler]
    MockGenerator -->|Realistic SQL Inserts| ResponseBuilder
    ResponseBuilder -->|Interactive UI Result| User
    
    subgraph Integration Layer
        SQLGenerator -.->|Introspect & Compare| NeonMCP[Neon MCP Server]
        NeonMCP -.->|Generate Live Schema Diff| LiveDB[(PostgreSQL / Neon Live)]
    end
```

### The 4 Specialized Agents:
1. **Schema Designer (`agents/schema_designer.py`):** Acts as the data architect. It parses requirements, extracts entities, maps attributes, normalizes relations (up to 3NF), and defines precise relationships.
2. **SQL Generator (`agents/sql_generator.py`):** Acts as the database engineer. It converts the abstract JSON schema design into clean, dialect-specific PostgreSQL DDL. If a previous schema exists, it runs in **Incremental Migration Mode** to output precise `ALTER TABLE` operations.
3. **Explainer (`agents/explainer.py`):** Acts as the code reviewer. It explains the table structures, indexes, foreign keys, and the reasoning behind each choice in plain English.
4. **Mock Data Generator (`agents/mock_data_generator.py`):** Acts as the QA engineer. It reads the generated DDL and creates realistic, compliant SQL insert statements that strictly adhere to table data types and foreign key relationships.

---

## 🔌 Neon MCP Server & Database Migrations

Andavar integrates directly with the **Neon Model Context Protocol (MCP) server** to bridge the gap between design and running infrastructure:
- **Introspection:** The system uses Neon MCP to introspect the schema of target databases.
- **Schema Compare:** It compares the introspected live schema state with the target AI-designed schema state using Neon database schema comparison tools.
- **Safe Migrations:** It translates the diff into zero-downtime migration scripts (like adding columns nullable first, validating constraints concurrently, and setting defaults safely).

---

## 🌐 RFC 10008: Safe HTTP QUERY Method Integration

To follow modern web standards, Andavar is built using the newly standardized **HTTP QUERY method (RFC 10008)**.

### Why QUERY?
Traditional web applications had to choose between two non-ideal options for complex, read-only search/export payloads:
1. **GET:** Safe and idempotent, but payloads had to be serialized into long, fragile URL query parameters (which often exceed browser/proxy size limits).
2. **POST:** Allowed structured request bodies, but lacked safe, idempotent, and cacheable semantics (triggering browser resubmission warnings).

Andavar uses `QUERY` for its **Schema Reports & Exports API** (`/api/reports/generate`), allowing the client to send a structured configuration JSON (specifying target project, formats like Prisma/SQLAlchemy, and titles) in the request body while guaranteeing the operation is entirely safe and idempotent.

---

## 🚀 Features

- **Multi-Format Exports:** Download schemas as:
  - Prisma Schema (`.prisma`)
  - SQLAlchemy Models (`.py`)
  - Mermaid ERD Markup (`.mmd`)
  - Raw PostgreSQL Script (`.sql`)
- **Interactive Mock Data Generator:** Context-aware insert statements are saved alongside every schema version.
- **Glassmorphism Visual Style:** Dark-themed responsive interface (`#0b0f19` background, `#8b5cf6` accents, and custom monochrome SVGs).
- **Multi-Tenant Project Isolation:** Configure database connection URLs, API keys, and models independently per project.
- **Robust Error Recovery:** Integrated exponential backoff for Gemini API calls to prevent 429 quota errors.
- **Local & Secure DB Execution:** All schemas and data are securely managed in a local Dockerized PostgreSQL instance (`devx-postgres`).
- **Role-Based Access Control:** `Admin` (full control), `Manager` (project management), `Guest` (read-only).

---

## 🛠️ Technical Setup & Installation

### 📦 Running via Docker (Recommended)

Andavar is built with Docker in mind and continuously published to GitHub Container Registry (GHCR).

```bash
# 1. Pull the image from GHCR
docker pull ghcr.io/malinir1995/andavar:main

# 2. Run the application
docker run --name andavar \
  -p 8000:8000 \
  -v andavar_pgdata:/app/postgres_data \
  ghcr.io/malinir1995/andavar:main
```

No `.env` file is required for the default Docker image. The container creates
its own local PostgreSQL database for Andavar system data, and it stores generated
JWT/encryption secrets inside the `andavar_pgdata` volume so auth survives
container restarts.

Open `http://localhost:8000`, create the first admin user, then use Settings in
the dashboard to add projects. Each project stores its own Gemini API key and
target PostgreSQL/Neon database URL.

Keep the `andavar_pgdata` volume when upgrading or replacing the container. If
you delete that volume, the local Andavar database, admin account, sessions, and
encrypted project settings are reset.

Or run with the bundled PostgreSQL instance via Docker Compose:

```bash
docker-compose up --build
```

This launches Andavar and maps PostgreSQL securely to your local machine.

### 💻 Local Development Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Malinir1995/andavar.git
   cd andavar
   ```

2. **Configure Environment:**
   Copy the example environment file:
   ```bash
   cp .env.example .env
   ```
   Set up your system database URL (SQLite is used if `SYSTEM_DATABASE_URL` is omitted):
   ```env
   SYSTEM_DATABASE_URL=postgresql://devx:dev_password_123@localhost:5432/andavar_system
   ```

3. **Install Dependencies:**
   Ensure Python 3.10+ is installed:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

4. **Run the Application:**
   ```bash
   uvicorn app:app --reload --port 8000
   ```
   Open `http://localhost:8000` in your browser.

---

## 🔐 Security & Multi-Tenancy

For maximum security, Andavar does not ship with a hardcoded default admin account.

**Option 1: Web Interface Setup (Interactive)**
If the system database is empty, the first user to navigate to the web interface will be presented with a `/setup` screen. From there, you can define your custom admin username, email, and password.

**Option 2: Environment Variables (Automated)**
You can pre-configure the initial admin by setting the following variables in your `.env` or Docker environment. The app will automatically bootstrap this account on startup:
```env
ADMIN_EMAIL=your_email@example.com
ADMIN_USERNAME=your_admin_name
ADMIN_PASSWORD=your_secure_password
```
*(Once an admin exists, these variables are ignored.)*

- **No Default Credentials:** Zero hardcoded default credentials.
- **Context Isolation:** Active project settings are managed using asynchronous context variables (`ContextVar`), guaranteeing that developers in one project never accidentally access the schema or connection details of another.

---

## 📚 Usage Workflow

1. **Create a Project**: Log in as an Admin/Manager and create a new project. You can define a specific `DATABASE_URL` and Gemini model just for this project.
2. **Chat with Andavar**: Use the chat interface to describe your system (e.g., "Design a schema for a SaaS billing platform").
3. **Review & Iterate**: Andavar will output the Schema Design, PostgreSQL syntax, and an Explanation.
4. **Execute**: Once satisfied, apply the SQL directly to the project's target database.
