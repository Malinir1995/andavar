"""Report and developer-friendly export generation routes."""

import json
import logging
import re
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from auth import get_current_user, require_role
from models import ReportRequest, ReportResponse, ReportListItem
from tools.memory_store import get_connection
from tools.crypto import decrypt

logger = logging.getLogger("andavar.routes.reports")
router = APIRouter(prefix="/api/reports", tags=["reports"])


def _get_latest_schema_json(project_id: str, conn) -> dict:
    """Gets the latest schema_json from schema_versions for the project."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT schema_json FROM schema_versions
               WHERE project_id = %s::uuid
               ORDER BY version_number DESC LIMIT 1""",
            (project_id,)
        )
        row = cur.fetchone()
        if row:
            if isinstance(row[0], str):
                return json.loads(row[0])
            return row[0]
    return {}


def _db_summary_to_schema_json(summary: dict) -> dict:
    """Converts a database summary dict into DatabaseSchema structure."""
    tables_list = []
    for t in summary.get("tables", []):
        columns = []
        for c in t.get("columns", []):
            constraints = []
            if c["name"] == "id":
                constraints.append("PRIMARY KEY")
            if not c["nullable"]:
                constraints.append("NOT NULL")
            columns.append({
                "name": c["name"],
                "type": c["type"].upper(),
                "constraints": constraints
            })
        tables_list.append({
            "name": t["table"],
            "columns": columns
        })
    return {
        "tables": tables_list,
        "relationships": []
    }


def _generate_schema_summary(project_id: str, conn) -> dict:
    """Generate a schema summary report from the project's target DB."""
    import psycopg2

    with conn.cursor() as cur:
        cur.execute("SELECT database_url, name FROM av_projects WHERE id = %s::uuid", (project_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "Project not found")

    db_url = decrypt(row[0])
    project_name = row[1]
    clean_url = re.sub(r"[&?]channel_binding=[^&]*", "", db_url)

    try:
        target = psycopg2.connect(clean_url, connect_timeout=5)
    except Exception as e:
        return {
            "project": project_name,
            "error": f"Cannot connect to project database: {e}",
            "tables": [],
        }

    try:
        with target.cursor() as cur:
            cur.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                ORDER BY table_name
            """)
            tables = [r[0] for r in cur.fetchall()]

            table_details = []
            for t in tables:
                cur.execute("""
                    SELECT column_name, data_type, is_nullable, column_default
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = %s
                    ORDER BY ordinal_position
                """, (t,))
                cols = [
                    {"name": r[0], "type": r[1], "nullable": r[2] == "YES", "default": r[3]}
                    for r in cur.fetchall()
                ]
                try:
                    cur.execute(f'SELECT COUNT(*) FROM "{t}"')
                    count = cur.fetchone()[0]
                except Exception:
                    count = None
                table_details.append({"table": t, "columns": cols, "row_count": count})

        return {"project": project_name, "tables": table_details, "table_count": len(tables)}
    finally:
        target.close()


def _generate_version_history(project_id: str, conn) -> dict:
    """Pull all schema versions linked to this project."""
    with conn.cursor() as cur:
        cur.execute("SELECT name FROM av_projects WHERE id = %s::uuid", (project_id,))
        proj = cur.fetchone()
        if not proj:
            raise HTTPException(404, "Project not found")

        cur.execute(
            """SELECT version_number, label, sql_output, explanation, created_at
               FROM schema_versions WHERE project_id = %s::uuid
               ORDER BY version_number ASC""",
            (project_id,),
        )
        rows = cur.fetchall()

    versions = [
        {
            "version": r[0], "label": r[1],
            "sql": r[2], "explanation": r[3],
            "created_at": str(r[4]) if r[4] else None,
        }
        for r in rows
    ]
    return {"project": proj[0], "versions": versions, "total": len(versions)}


def _generate_prisma(schema_json: dict) -> str:
    """Generate schema.prisma representation."""
    if not schema_json or not schema_json.get("tables"):
        return "// No schema tables defined yet."
    
    lines = [
        'datasource db {',
        '  provider = "postgresql"',
        '  url      = env("DATABASE_URL")',
        '}',
        ''
    ]
    
    type_map = {
        "UUID": "String",
        "TEXT": "String",
        "VARCHAR": "String",
        "CHARACTER VARYING": "String",
        "TIMESTAMPTZ": "DateTime",
        "TIMESTAMP": "DateTime",
        "INTEGER": "Int",
        "INT": "Int",
        "BIGINT": "BigInt",
        "NUMERIC": "Decimal",
        "DECIMAL": "Decimal",
        "BOOLEAN": "Boolean",
        "BOOL": "Boolean",
    }
    
    relations = schema_json.get("relationships", [])
    
    for table in schema_json.get("tables", []):
        tname = table["name"]
        model_name = "".join(part.capitalize() for part in tname.split("_"))
        lines.append(f"model {model_name} {{")
        
        for col in table["columns"]:
            cname = col["name"]
            ptype = type_map.get(col["type"].upper(), "String")
            
            c_str = ""
            is_pk = False
            for constraint in col.get("constraints", []):
                if "PRIMARY KEY" in constraint.upper():
                    c_str += " @id"
                    is_pk = True
                if "UNIQUE" in constraint.upper():
                    c_str += " @unique"
            
            is_nullable = True
            for constraint in col.get("constraints", []):
                if "NOT NULL" in constraint.upper():
                    is_nullable = False
            if is_pk:
                is_nullable = False
            
            if is_nullable:
                ptype += "?"
                
            lines.append(f"  {cname} {ptype}{c_str}")
        
        # Add relations
        for rel in relations:
            if rel["from_table"] == tname:
                fcol = rel["from_column"]
                ttable = rel["to_table"]
                tcol = rel["to_column"]
                
                relation_field = ttable.lower()
                target_model = "".join(part.capitalize() for part in ttable.split("_"))
                lines.append(f"  {relation_field} {target_model} @relation(fields: [{fcol}], references: [{tcol}])")
            elif rel["to_table"] == tname:
                ftable = rel["from_table"]
                source_model = "".join(part.capitalize() for part in ftable.split("_"))
                relation_field = ftable.lower() + "s"
                lines.append(f"  {relation_field} {source_model}[]")
                
        lines.append("}")
        lines.append("")
        
    return "\n".join(lines)


def _generate_sqlalchemy(schema_json: dict) -> str:
    """Generate sqlalchemy models.py representation."""
    if not schema_json or not schema_json.get("tables"):
        return "# No schema tables defined yet."
        
    lines = [
        "from sqlalchemy import Column, String, Integer, DateTime, Boolean, ForeignKey, Numeric",
        "from sqlalchemy.orm import relationship, declarative_base",
        "",
        "Base = declarative_base()",
        ""
    ]
    
    type_map = {
        "UUID": "String",
        "TEXT": "String",
        "VARCHAR": "String",
        "CHARACTER VARYING": "String",
        "TIMESTAMPTZ": "DateTime(timezone=True)",
        "TIMESTAMP": "DateTime",
        "INTEGER": "Integer",
        "INT": "Integer",
        "BIGINT": "Integer",
        "NUMERIC": "Numeric",
        "DECIMAL": "Numeric",
        "BOOLEAN": "Boolean",
        "BOOL": "Boolean",
    }
    
    relations = schema_json.get("relationships", [])
    
    for table in schema_json.get("tables", []):
        tname = table["name"]
        class_name = "".join(part.capitalize() for part in tname.split("_"))
        lines.append(f"class {class_name}(Base):")
        lines.append(f"    __tablename__ = '{tname}'")
        lines.append("")
        
        for col in table["columns"]:
            cname = col["name"]
            col_type = type_map.get(col["type"].upper(), "String")
            
            args = []
            is_pk = False
            for constraint in col.get("constraints", []):
                if "PRIMARY KEY" in constraint.upper():
                    args.append("primary_key=True")
                    is_pk = True
                if "UNIQUE" in constraint.upper():
                    args.append("unique=True")
                    
            is_nullable = True
            for constraint in col.get("constraints", []):
                if "NOT NULL" in constraint.upper():
                    is_nullable = False
            if is_pk:
                is_nullable = False
            if not is_nullable:
                args.append("nullable=False")
                
            fk_str = ""
            for rel in relations:
                if rel["from_table"] == tname and rel["from_column"] == cname:
                    fk_str = f"ForeignKey('{rel['to_table']}.{rel['to_column']}', ondelete='{rel['on_delete']}')"
                    break
            
            if fk_str:
                lines.append(f"    {cname} = Column({col_type}, {fk_str}, {', '.join(args)})" if args else f"    {cname} = Column({col_type}, {fk_str})")
            else:
                lines.append(f"    {cname} = Column({col_type}, {', '.join(args)})" if args else f"    {cname} = Column({col_type})")
                
        for rel in relations:
            if rel["from_table"] == tname:
                target_class = "".join(part.capitalize() for part in rel["to_table"].split("_"))
                lines.append(f"    {rel['to_table'].lower()} = relationship('{target_class}')")
            elif rel["to_table"] == tname:
                source_class = "".join(part.capitalize() for part in rel["from_table"].split("_"))
                lines.append(f"    {rel['from_table'].lower()}s = relationship('{source_class}')")
                
        lines.append("")
        
    return "\n".join(lines)


def _generate_mermaid_erd(schema_json: dict) -> str:
    """Generate mermaid ER diagram."""
    if not schema_json or not schema_json.get("tables"):
        return "%% No schema tables defined yet."
        
    lines = [
        "erDiagram",
        ""
    ]
    
    for table in schema_json.get("tables", []):
        tname = table["name"]
        lines.append(f"    {tname} {{")
        for col in table["columns"]:
            cname = col["name"]
            ctype = col["type"].lower().replace(" ", "_")
            pk_fk = ""
            for c in col.get("constraints", []):
                if "PRIMARY KEY" in c.upper():
                    pk_fk = "PK"
            for rel in schema_json.get("relationships", []):
                if rel["from_table"] == tname and rel["from_column"] == cname:
                    pk_fk = "FK" if not pk_fk else "PK, FK"
            
            lines.append(f"        {ctype} {cname} {pk_fk}")
        lines.append("    }")
        lines.append("")
        
    for rel in schema_json.get("relationships", []):
        lines.append(f"    {rel['to_table']} ||--o{{ {rel['from_table']} : \"{rel['from_column']}\"")
        
    return "\n".join(lines)


def _to_markdown(report_type: str, content: dict) -> str:
    """Convert report JSON to readable markdown."""
    lines = [f"# {content.get('project', 'Andavar')} — Report\n"]

    if report_type == "schema_summary":
        lines.append(f"**Tables:** {content.get('table_count', 0)}\n")
        for t in content.get("tables", []):
            lines.append(f"## {t['table']}")
            if t.get("row_count") is not None:
                lines.append(f"*Rows: {t['row_count']}*\n")
            lines.append("| Column | Type | Nullable | Default |")
            lines.append("|--------|------|----------|---------|")
            for c in t.get("columns", []):
                lines.append(
                    f"| {c['name']} | {c['type']} | {'✓' if c['nullable'] else '✗'} | {c['default'] or '—'} |"
                )
            lines.append("")

    elif report_type == "version_history":
        lines.append(f"**Total versions:** {content.get('total', 0)}\n")
        for v in content.get("versions", []):
            lines.append(f"## Version {v['version']} — {v.get('label', '')}")
            lines.append(f"*Created: {v.get('created_at', 'N/A')}*\n")
            if v.get("explanation"):
                lines.append(v["explanation"])
            if v.get("sql"):
                lines.append(f"\n```sql\n{v['sql']}\n```\n")

    elif report_type == "full_export":
        lines.append("## Schema Summary\n")
        # Reuse to_markdown but pass nested dicts
        lines.append(_to_markdown("schema_summary", content.get("schema_summary", {})))
        lines.append("\n---\n## Version History\n")
        lines.append(_to_markdown("version_history", content.get("version_history", {})))

    return "\n".join(lines)


# ── Routes ────────────────────────────────────────────────────────────────────

@router.api_route("/generate", methods=["POST", "QUERY"], response_model=ReportResponse, status_code=201)
def generate_report(req: ReportRequest, user: dict = Depends(require_role("manager"))):
    conn = get_connection()
    if not conn:
        raise HTTPException(500, "Database not available")
    try:
        # Load latest schema JSON or fallback
        schema_json = _get_latest_schema_json(req.project_id, conn)
        
        # If schema_json is empty, attempt target DB introspection to build one
        if not schema_json:
            db_summary = _generate_schema_summary(req.project_id, conn)
            schema_json = _db_summary_to_schema_json(db_summary)

        # Handle new export types
        if req.report_type == "prisma":
            content_str = _generate_prisma(schema_json)
            content_json = {"prisma": content_str}
        elif req.report_type == "sqlalchemy":
            content_str = _generate_sqlalchemy(schema_json)
            content_json = {"sqlalchemy": content_str}
        elif req.report_type == "mermaid_erd":
            content_str = _generate_mermaid_erd(schema_json)
            content_json = {"mermaid_erd": content_str}
        elif req.report_type == "standalone_sql":
            # standalone sql is just the latest sql output from schema_versions
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT sql_output FROM schema_versions
                       WHERE project_id = %s::uuid
                       ORDER BY version_number DESC LIMIT 1""",
                    (req.project_id,)
                )
                row = cur.fetchone()
                content_str = row[0] if row else "-- No SQL generated yet."
            content_json = {"standalone_sql": content_str}
        else:
            # Traditional report types
            generators = {
                "schema_summary": _generate_schema_summary,
                "version_history": _generate_version_history,
                "full_export": lambda pid, c: {
                    "project": _generate_schema_summary(pid, c).get("project", ""),
                    "schema_summary": _generate_schema_summary(pid, c),
                    "version_history": _generate_version_history(pid, c),
                }
            }
            gen = generators.get(req.report_type)
            if not gen:
                raise HTTPException(400, f"Unknown report type: {req.report_type}")
            
            content_json = gen(req.project_id, conn)
            content_str = _to_markdown(req.report_type, content_json)

        # Get project name
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM av_projects WHERE id = %s::uuid", (req.project_id,))
            p_row = cur.fetchone()
        project_name = p_row[0] if p_row else "Andavar"

        title = req.title or f"{project_name} — {req.report_type.replace('_', ' ').title()}"

        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO av_reports (project_id, generated_by, title, report_type, content_json, content_markdown)
                   VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s) RETURNING id, created_at""",
                (req.project_id, user["id"], title, req.report_type, json.dumps(content_json), content_str),
            )
            rid, created_at = cur.fetchone()
            conn.commit()

        return ReportResponse(
            id=str(rid), project_id=req.project_id,
            generated_by=user["id"], title=title,
            report_type=req.report_type,
            content_markdown=content_str,
            created_at=str(created_at) if created_at else None,
        )
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"generate_report: {e}")
        raise HTTPException(500, str(e))
    finally:
        conn.close()


@router.get("", response_model=List[ReportListItem])
def list_reports(project_id: str, user: dict = Depends(get_current_user)):
    conn = get_connection()
    if not conn:
        raise HTTPException(500, "Database not available")
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, title, report_type, created_at
                   FROM av_reports WHERE project_id = %s::uuid
                   ORDER BY created_at DESC""",
                (project_id,),
            )
            rows = cur.fetchall()
        return [
            ReportListItem(
                id=str(r[0]), title=r[1], report_type=r[2],
                created_at=str(r[3]) if r[3] else None,
            )
            for r in rows
        ]
    finally:
        conn.close()


@router.get("/{report_id}", response_model=ReportResponse)
def get_report(report_id: str, user: dict = Depends(get_current_user)):
    conn = get_connection()
    if not conn:
        raise HTTPException(500, "Database not available")
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, project_id, generated_by, title, report_type, content_markdown, created_at
                   FROM av_reports WHERE id = %s::uuid""",
                (report_id,),
            )
            r = cur.fetchone()
        if not r:
            raise HTTPException(404, "Report not found")
        return ReportResponse(
            id=str(r[0]), project_id=str(r[1]),
            generated_by=str(r[2]) if r[2] else None,
            title=r[3], report_type=r[4],
            content_markdown=r[5],
            created_at=str(r[6]) if r[6] else None,
        )
    finally:
        conn.close()


@router.get("/{report_id}/download")
def download_report(report_id: str, user: dict = Depends(get_current_user)):
    conn = get_connection()
    if not conn:
        raise HTTPException(500, "Database not available")
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT title, content_markdown, report_type FROM av_reports WHERE id = %s::uuid",
                (report_id,),
            )
            r = cur.fetchone()
        if not r:
            raise HTTPException(404, "Report not found")
        
        title, content, rtype = r
        
        # Determine file extension based on type
        ext_map = {
            "prisma": "prisma",
            "sqlalchemy": "py",
            "mermaid_erd": "mmd",
            "standalone_sql": "sql"
        }
        ext = ext_map.get(rtype, "md")
        filename = f"{title.replace(' ', '_').lower()}.{ext}"
        
        return PlainTextResponse(
            content=content or "",
            media_type="text/plain",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    finally:
        conn.close()
