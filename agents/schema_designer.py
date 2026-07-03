from typing import List, Optional
from pydantic import BaseModel, Field
from google.adk.agents import Agent
from config import settings

class ColumnSchema(BaseModel):
    name: str = Field(..., description="Name of the column in snake_case")
    type: str = Field(..., description="PostgreSQL-compatible data type (e.g. UUID, TEXT, TIMESTAMPTZ, INTEGER, NUMERIC)")
    constraints: Optional[List[str]] = Field(default=[], description="List of constraints, e.g. ['PRIMARY KEY', 'NOT NULL', 'UNIQUE']")

class TableSchema(BaseModel):
    name: str = Field(..., description="Name of the table in snake_case")
    columns: List[ColumnSchema] = Field(..., description="List of columns in the table")

class RelationshipSchema(BaseModel):
    from_table: str = Field(..., description="Source table name")
    from_column: str = Field(..., description="Foreign key column name in source table")
    to_table: str = Field(..., description="Target table name")
    to_column: str = Field(..., description="Primary key column name in target table")
    on_delete: str = Field(..., description="Referential action, e.g., CASCADE, RESTRICT, SET NULL")

class DatabaseSchema(BaseModel):
    tables: List[TableSchema] = Field(..., description="List of tables in the database schema")
    relationships: List[RelationshipSchema] = Field(..., description="List of foreign key relationships between tables")

from tools.gemini_model import ProjectGemini

schema_designer = Agent(
    name="schema_designer",
    model=ProjectGemini(model=settings.gemini_model),
    output_schema=DatabaseSchema,
    instruction="""
You are an expert relational database schema designer.
Analyze the user's plain-English description and design a normalised relational schema.

Rules:
- Tables and columns: snake_case only.
- Every table must have a UUID primary key column named `id`.
- All timestamps: TIMESTAMPTZ type.
- Normalise to 3NF; define every foreign-key relationship explicitly.
- For each relationship state: from_table, from_column, to_table, to_column, on_delete.
"""
)
