"""Pydantic models for Andavar user management, projects, and reports."""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, EmailStr


# ── Auth ──────────────────────────────────────────────────────────────────────

class UserLogin(BaseModel):
    email: str = Field(..., description="User email")
    password: str = Field(..., min_length=6)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserResponse"


# ── Users ─────────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(..., description="User email address")
    password: str = Field(..., min_length=6)
    role: str = Field(default="guest", pattern="^(admin|manager|guest)$")


class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    role: str
    is_active: bool
    created_at: Optional[str] = None


class UserUpdate(BaseModel):
    role: Optional[str] = Field(None, pattern="^(admin|manager|guest)$")
    is_active: Optional[bool] = None


# ── Projects ──────────────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    database_url: str = Field(..., description="PostgreSQL connection string")
    api_key: str = Field(..., description="Gemini API key for this project")
    gemini_model: str = Field(default="gemini-2.5-flash-lite")


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    database_url: Optional[str] = None
    api_key: Optional[str] = None
    gemini_model: Optional[str] = None
    is_active: Optional[bool] = None


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    gemini_model: str
    is_active: bool
    created_by: Optional[str]
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    # Sensitive fields masked
    database_url_masked: Optional[str] = None
    has_api_key: bool = False


class ProjectDetail(ProjectResponse):
    """Full project detail — only for admin."""
    database_url: Optional[str] = None
    api_key: Optional[str] = None


# ── Reports ───────────────────────────────────────────────────────────────────

class ReportRequest(BaseModel):
    project_id: str
    report_type: str = Field(
        ..., pattern="^(schema_summary|version_history|full_export|prisma|sqlalchemy|mermaid_erd|standalone_sql)$"
    )
    title: Optional[str] = None


class ReportResponse(BaseModel):
    id: str
    project_id: str
    generated_by: Optional[str]
    title: str
    report_type: str
    content_markdown: Optional[str] = None
    created_at: Optional[str] = None


class ReportListItem(BaseModel):
    id: str
    title: str
    report_type: str
    created_at: Optional[str] = None


# Forward ref update
TokenResponse.model_rebuild()
