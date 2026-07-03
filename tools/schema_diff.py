from typing import Dict, Any, List

def diff_schemas(schema_v1: Dict[str, Any], schema_v2: Dict[str, Any]) -> Dict[str, Any]:
    """
    Computes diff between schema_v1 (old) and schema_v2 (new).
    Returns structural differences: added, removed, and modified tables/columns.
    """
    # Initialize differences dictionary
    diff = {
        "added_tables": [],
        "removed_tables": [],
        "modified_tables": {}
    }

    # Ensure valid inputs, fall back to empty list of tables if not present
    tables_v1 = {t["name"]: t for t in schema_v1.get("tables", [])}
    tables_v2 = {t["name"]: t for t in schema_v2.get("tables", [])}

    # 1. Added Tables
    for t_name in tables_v2:
        if t_name not in tables_v1:
            diff["added_tables"].append(t_name)

    # 2. Removed Tables
    for t_name in tables_v1:
        if t_name not in tables_v2:
            diff["removed_tables"].append(t_name)

    # 3. Modified Tables
    for t_name in tables_v2:
        if t_name in tables_v1:
            table_mod = diff_table(tables_v1[t_name], tables_v2[t_name])
            if table_mod:
                diff["modified_tables"][t_name] = table_mod

    return diff

def diff_table(table_v1: Dict[str, Any], table_v2: Dict[str, Any]) -> Dict[str, Any]:
    """Compares columns and constraints between two versions of a table."""
    modifications = {
        "added_columns": [],
        "removed_columns": [],
        "modified_columns": {}
    }

    cols_v1 = {c["name"]: c for c in table_v1.get("columns", [])}
    cols_v2 = {c["name"]: c for c in table_v2.get("columns", [])}

    # Added columns
    for c_name in cols_v2:
        if c_name not in cols_v1:
            modifications["added_columns"].append(cols_v2[c_name])

    # Removed columns
    for c_name in cols_v1:
        if c_name not in cols_v2:
            modifications["removed_columns"].append(c_name)

    # Modified columns (type, constraints etc)
    for c_name in cols_v2:
        if c_name in cols_v1:
            col_1 = cols_v1[c_name]
            col_2 = cols_v2[c_name]
            col_changes = {}

            if col_1.get("type") != col_2.get("type"):
                col_changes["type"] = {
                    "old": col_1.get("type"),
                    "new": col_2.get("type")
                }

            # Constraints comparison
            constraints_1 = sorted(col_1.get("constraints") or [])
            constraints_2 = sorted(col_2.get("constraints") or [])
            if constraints_1 != constraints_2:
                col_changes["constraints"] = {
                    "old": constraints_1,
                    "new": constraints_2
                }

            if col_changes:
                modifications["modified_columns"][c_name] = col_changes

    # Clean up empty modification categories
    result = {k: v for k, v in modifications.items() if v}
    return result if result else None

def format_diff_markdown(diff: Dict[str, Any]) -> str:
    """Formats the JSON diff object into a clean human-readable Markdown string."""
    lines = []
    
    if diff.get("added_tables"):
        lines.append("### ➕ Added Tables")
        for table in diff["added_tables"]:
            lines.append(f"- **{table}**")
        lines.append("")

    if diff.get("removed_tables"):
        lines.append("### ➖ Removed Tables")
        for table in diff["removed_tables"]:
            lines.append(f"- **{table}**")
        lines.append("")

    if diff.get("modified_tables"):
        lines.append("### 🛠 Modified Tables")
        for table, mods in diff["modified_tables"].items():
            lines.append(f"#### Table: `{table}`")
            
            if mods.get("added_columns"):
                lines.append("  *Added columns:*")
                for col in mods["added_columns"]:
                    constraints_str = f" ({', '.join(col.get('constraints') or [])})" if col.get("constraints") else ""
                    lines.append(f"    - `{col['name']}`: {col['type']}{constraints_str}")
                    
            if mods.get("removed_columns"):
                lines.append("  *Removed columns:*")
                for col_name in mods["removed_columns"]:
                    lines.append(f"    - `{col_name}`")
                    
            if mods.get("modified_columns"):
                lines.append("  *Modified columns:*")
                for col_name, changes in mods["modified_columns"].items():
                    change_details = []
                    if "type" in changes:
                        change_details.append(f"type: `{changes['type']['old']}` ➡️ `{changes['type']['new']}`")
                    if "constraints" in changes:
                        old_c = ", ".join(changes['constraints']['old']) or "None"
                        new_c = ", ".join(changes['constraints']['new']) or "None"
                        change_details.append(f"constraints: `{old_c}` ➡️ `{new_c}`")
                    lines.append(f"    - `{col_name}`: {'; '.join(change_details)}")
            lines.append("")

    if not lines:
        return "No structural differences found between versions."

    return "\n".join(lines)
