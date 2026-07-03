import logging
from typing import Dict, Any, List
from tools.memory_store import get_connection

logger = logging.getLogger("andavar.neon_mcp")

def get_db_tables() -> List[str]:
    """Retrieves all table names in the public schema of the database."""
    conn = get_connection(project_aware=True)
    if not conn:
        return []
    tables = []
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
            tables = [row[0] for row in cur.fetchall()]
    except Exception as e:
        logger.error(f"Error fetching database tables: {e}")
    finally:
        conn.close()
    return tables

def describe_db_table(table_name: str) -> Dict[str, Any]:
    """Retrieves columns, types, constraints, and relationships for a table."""
    conn = get_connection(project_aware=True)
    if not conn:
        return {}
    
    table_desc = {
        "name": table_name,
        "columns": [],
        "foreign_keys": []
    }
    
    try:
        with conn.cursor() as cur:
            # 1. Get Columns and Primary Key info
            cur.execute("""
                SELECT 
                    c.column_name, 
                    c.data_type, 
                    c.is_nullable,
                    c.column_default,
                    (SELECT count(*) 
                     FROM information_schema.key_column_usage kcu
                     JOIN information_schema.table_constraints tc 
                       ON tc.constraint_name = kcu.constraint_name
                       AND tc.table_schema = kcu.table_schema
                     WHERE tc.constraint_type = 'PRIMARY KEY'
                       AND tc.table_name = c.table_name
                       AND kcu.column_name = c.column_name) > 0 as is_pk
                FROM information_schema.columns c
                WHERE c.table_schema = 'public' 
                  AND c.table_name = %s
                ORDER BY c.ordinal_position;
            """, (table_name,))
            
            for row in cur.fetchall():
                col_name, data_type, is_nullable, col_default, is_pk = row
                constraints = []
                if is_pk:
                    constraints.append("PRIMARY KEY")
                if is_nullable == 'NO':
                    constraints.append("NOT NULL")
                
                table_desc["columns"].append({
                    "name": col_name,
                    "type": data_type,
                    "constraints": constraints,
                    "default": col_default
                })

            # 2. Get Foreign Keys and Relationships
            cur.execute("""
                SELECT
                    kcu.column_name,
                    ccu.table_name AS foreign_table_name,
                    ccu.column_name AS foreign_column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                  AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage ccu
                  ON ccu.constraint_name = tc.constraint_name
                  AND ccu.table_schema = tc.table_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND tc.table_name = %s;
            """, (table_name,))
            
            for row in cur.fetchall():
                col, ref_table, ref_col = row
                table_desc["foreign_keys"].append({
                    "column": col,
                    "references_table": ref_table,
                    "references_column": ref_col
                })
    except Exception as e:
        logger.error(f"Error describing table {table_name}: {e}")
    finally:
        conn.close()
        
    return table_desc

def get_database_schema_introspection() -> Dict[str, Any]:
    """Retrieves the full database schema design from public schema."""
    tables = get_db_tables()
    schema_design = {
        "tables": []
    }
    for t in tables:
        schema_design["tables"].append(describe_db_table(t))
    return schema_design
