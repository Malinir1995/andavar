# Andavar

Andavar is an intelligent, multi-agent PostgreSQL schema designer and management platform. Powered by Google Gemini, it allows developers to describe their database needs in plain English, while specialized AI agents automatically normalize the requirements, generate robust PostgreSQL DDL queries, and explain the design decisions.

## 🚀 Features

- **Multi-Agent Architecture**: 
  - `Schema Designer`: Analyzes requirements and models entities.
  - `SQL Generator`: Outputs robust, normalized PostgreSQL DDL.
  - `Explainer`: Provides plain-English rationale for the schema.
- **Local & Secure DB Execution**: All schemas and data are securely managed in a local Dockerized PostgreSQL instance (`devx-postgres`).
- **Role-Based Access Control**:
  - `Admin`: Full control over the platform, users, and projects.
  - `Manager`: Project management capabilities.
  - `Guest`: Read-only views.
- **Multi-Tenant Projects**: Isolate database connections, API keys, and model configurations on a per-project basis.
- **Secure Setup**: Zero hardcoded default credentials. Admin account is uniquely initialized upon first launch.

## 📦 Running via Docker (Recommended)

Andavar is built with Docker in mind and continuously published to GitHub Container Registry (GHCR).

```bash
# 1. Pull the image from GHCR
docker pull ghcr.io/malinir1995/andavar:latest

# 2. Run the application (ensure a PostgreSQL instance is accessible)
docker run -p 8000:8000 --env-file .env ghcr.io/malinir1995/andavar:latest
```

## 🛠️ Local Development Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/Malinir1995/andavar.git
   cd andavar
   ```

2. **Configure Environment**
   Copy the example config and adjust the `DATABASE_URL`:
   ```bash
   cp .env.example .env
   ```
   Ensure `DATABASE_URL` points to your local PostgreSQL instance:
   ```env
   DATABASE_URL=postgresql://devx:dev_password_123@localhost:5432/andavar_system
   ```

3. **Install Dependencies**
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

4. **Start the Application**
   ```bash
   uvicorn app:app --reload
   ```

## 🔐 Admin Setup & Security

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

## 📚 Usage Workflow

1. **Create a Project**: Log in as an Admin/Manager and create a new project. You can define a specific `DATABASE_URL` and Gemini model just for this project.
2. **Chat with Andavar**: Use the chat interface to describe your system (e.g., "Design a schema for a SaaS billing platform").
3. **Review & Iterate**: Andavar will output the Schema Design, PostgreSQL syntax, and an Explanation.
4. **Execute**: Once satisfied, apply the SQL directly to the project's target database.
