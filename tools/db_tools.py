import logging
from decimal import Decimal
from datetime import date, datetime
from typing import Any, Dict, List

from tools.memory_store import get_connection

logger = logging.getLogger("andavar.db_tools")


def _safe(v: Any) -> Any:
    """Convert non-JSON-serialisable DB values to safe primitives."""
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, memoryview):
        return v.tobytes().hex()
    return v


def list_tables() -> Dict[str, Any]:
    """
    Lists all user-created tables in the connected PostgreSQL database.
    Call this to understand what tables exist before querying them.
    """
    conn = get_connection(project_aware=True)
    if not conn:
        return {"error": "No database connection. Check DATABASE_URL in .env"}
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_type = 'BASE TABLE'
                  AND table_name != 'schema_versions'
                ORDER BY table_name;
            """)
            tables = [r[0] for r in cur.fetchall()]
        return {"tables": tables, "count": len(tables)}
    except Exception as e:
        logger.error(f"list_tables: {e}")
        return {"error": str(e)}
    finally:
        conn.close()


def describe_table(table_name: str) -> Dict[str, Any]:
    """
    Returns the full schema of a specific table: columns, data types,
    nullable flags, defaults, primary keys, foreign keys, and row count.

    Args:
        table_name: Name of the table to describe.
    """
    conn = get_connection(project_aware=True)
    if not conn:
        return {"error": "No database connection."}
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    c.column_name,
                    c.data_type,
                    c.is_nullable,
                    c.column_default,
                    EXISTS (
                        SELECT 1
                        FROM information_schema.table_constraints tc
                        JOIN information_schema.key_column_usage kcu
                            ON tc.constraint_name = kcu.constraint_name
                            AND tc.table_schema  = kcu.table_schema
                        WHERE tc.constraint_type = 'PRIMARY KEY'
                          AND tc.table_name      = c.table_name
                          AND kcu.column_name    = c.column_name
                    ) AS is_pk
                FROM information_schema.columns c
                WHERE c.table_schema = 'public'
                  AND c.table_name   = %s
                ORDER BY c.ordinal_position;
            """, (table_name,))
            columns = [
                {
                    "name": row[0],
                    "type": row[1],
                    "nullable": row[2] == "YES",
                    "default": row[3],
                    "primary_key": row[4],
                }
                for row in cur.fetchall()
            ]

            cur.execute("""
                SELECT kcu.column_name, ccu.table_name, ccu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema   = kcu.table_schema
                JOIN information_schema.constraint_column_usage ccu
                    ON ccu.constraint_name = tc.constraint_name
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND tc.table_name = %s;
            """, (table_name,))
            fks = [
                {"column": r[0], "references": f"{r[1]}.{r[2]}"}
                for r in cur.fetchall()
            ]

            try:
                cur.execute(f'SELECT COUNT(*) FROM "{table_name}";')
                row_count = cur.fetchone()[0]
            except Exception:
                row_count = None

        return {
            "table": table_name,
            "columns": columns,
            "foreign_keys": fks,
            "row_count": row_count,
        }
    except Exception as e:
        logger.error(f"describe_table({table_name}): {e}")
        return {"error": str(e)}
    finally:
        conn.close()


def execute_sql(sql: str) -> Dict[str, Any]:
    """
    Executes a SELECT query and returns the results as rows.
    Results are capped at 200 rows. Do NOT use this for writes.

    Args:
        sql: A SELECT (or WITH … SELECT) SQL statement.
    """
    stripped = sql.strip().lstrip("(").upper()
    if not (stripped.startswith("SELECT") or stripped.startswith("WITH")):
        return {
            "error": (
                "execute_sql is for SELECT queries only. "
                "Use execute_write_sql for INSERT / UPDATE / DELETE / DDL."
            )
        }

    conn = get_connection(project_aware=True)
    if not conn:
        return {"error": "No database connection."}
    try:
        with conn.cursor() as cur:
            safe_sql = sql.rstrip(";")
            if "LIMIT" not in sql.upper():
                safe_sql += " LIMIT 200"
            safe_sql += ";"
            cur.execute(safe_sql)
            cols = [d[0] for d in cur.description]
            rows = [[_safe(v) for v in r] for r in cur.fetchall()]
        return {"columns": cols, "rows": rows, "row_count": len(rows), "sql_executed": safe_sql}
    except Exception as e:
        logger.error(f"execute_sql: {e}")
        return {"error": str(e)}
    finally:
        conn.close()


def execute_write_sql(sql: str) -> Dict[str, Any]:
    """
    Executes a write SQL statement: INSERT, UPDATE, DELETE, CREATE TABLE,
    ALTER TABLE, DROP TABLE, etc. Commits automatically.

    Args:
        sql: A write SQL statement to execute against the database.
    """
    from tools.memory_store import current_user_role
    role = current_user_role.get()
    if role == "guest":
        return {"error": "Permission denied: Guest user cannot execute write queries."}

    conn = get_connection(project_aware=True)
    if not conn:
        return {"error": "No database connection."}
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            affected = cur.rowcount
        conn.commit()
        return {"success": True, "rows_affected": affected, "sql_executed": sql}
    except Exception as e:
        conn.rollback()
        logger.error(f"execute_write_sql: {e}")
        return {"error": str(e)}
    finally:
        conn.close()
