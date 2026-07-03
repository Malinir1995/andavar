"""Report generation routes — schema summaries, version history, full exports."""

import json
import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from auth import get_current_user, require_role
from models import ReportRequest, ReportResponse, ReportListItem
from tools.memory_store import get_connection
from tools.crypto import decrypt

logger = logging.getLogger("andavar.routes.reports")
router = APIRouter(prefix="/api/reports", tags=["reports"])


def _generate_schema_summary(project_id: str, conn) -> dict:
    """Generate a schema summary report from the project's target DB."""
    import psycopg2
    import re

    # Get project DB URL
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


def _generate_full_export(project_id: str, conn) -> dict:
    """Combine schema summary + version history."""
    summary = _generate_schema_summary(project_id, conn)
    history = _generate_version_history(project_id, conn)
    return {
        "project": summary.get("project", ""),
        "schema_summary": summary,
        "version_history": history,
    }


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
        lines.append(_to_markdown("schema_summary", content.get("schema_summary", {})))
        lines.append("\n---\n## Version History\n")
        lines.append(_to_markdown("version_history", content.get("version_history", {})))

    return "\n".join(lines)


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/generate", response_model=ReportResponse, status_code=201)
def generate_report(req: ReportRequest, user: dict = Depends(require_role("manager"))):
    conn = get_connection()
    if not conn:
        raise HTTPException(500, "Database not available")
    try:
        generators = {
            "schema_summary": _generate_schema_summary,
            "version_history": _generate_version_history,
            "full_export": _generate_full_export,
        }
        gen = generators.get(req.report_type)
        if not gen:
            raise HTTPException(400, f"Unknown report type: {req.report_type}")

        content = gen(req.project_id, conn)
        md = _to_markdown(req.report_type, content)
        title = req.title or f"{content.get('project', 'Andavar')} — {req.report_type.replace('_', ' ').title()}"

        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO av_reports (project_id, generated_by, title, report_type, content_json, content_markdown)
                   VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s) RETURNING id, created_at""",
                (req.project_id, user["id"], title, req.report_type, json.dumps(content), md),
            )
            rid, created_at = cur.fetchone()
            conn.commit()

        return ReportResponse(
            id=str(rid), project_id=req.project_id,
            generated_by=user["id"], title=title,
            report_type=req.report_type,
            content_markdown=md,
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
                "SELECT title, content_markdown FROM av_reports WHERE id = %s::uuid",
                (report_id,),
            )
            r = cur.fetchone()
        if not r:
            raise HTTPException(404, "Report not found")
        return PlainTextResponse(
            content=r[1] or "",
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{r[0]}.md"'},
        )
    finally:
        conn.close()
