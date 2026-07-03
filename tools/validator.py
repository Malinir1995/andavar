import re
from typing import Dict, Any

# ── Prompt injection detection (defense-in-depth) ─────────────────────────────
# These catch common jailbreak/role-override patterns in the user's chat message.
# They are NOT the primary security boundary — the tool-level guards in db_tools.py are.
INJECTION_PATTERNS = [
    r"ignore previous instructions",
    r"system prompt",
    r"you are now",
    r"acting as",
    r"jailbreak",
    r"bypass safety",
]


def sanitize_input(prompt: str) -> str:
    """Basic sanitization of input string."""
    if not prompt:
        return ""
    # Strip any potential harmful controls/null bytes
    cleaned = prompt.replace("\x00", "")
    return cleaned.strip()


def detect_prompt_injection(prompt: str) -> bool:
    """Detect potential prompt injection attempts."""
    if not prompt:
        return False
    prompt_lower = prompt.lower()
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, prompt_lower):
            return True
    return False


def strip_sql_comments(sql: str) -> str:
    """Remove comments from SQL statement to avoid bypasses."""
    # Remove single line comments starting with --
    sql = re.sub(r'--.*?\n', '\n', sql)
    # Remove multi-line comments starting with /* and ending with */
    sql = re.sub(r'/\*.*?\*/', '', sql, flags=re.DOTALL)
    return sql


def validate_ddl_only(sql: str) -> Dict[str, Any]:
    """Validates that a SQL string contains DDL only (no DML: INSERT, UPDATE, DELETE)."""
    if not sql:
        return {"status": "success", "data": "", "error": None}

    clean_sql = strip_sql_comments(sql).strip()
    if not clean_sql:
        return {"status": "success", "data": "", "error": None}

    # Normalize whitespace
    normalized = re.sub(r'\s+', ' ', clean_sql).upper()

    # Block destructive/DML words as words (using boundary \b)
    blocked_patterns = [
        r"\bINSERT\b",
        r"\bUPDATE\b",
        r"\bDELETE\b",
        r"\bTRUNCATE\b",
        r"\bDROP\s+DATABASE\b",
        r"\bGRANT\b",
        r"\bREVOKE\b",
    ]

    for pattern in blocked_patterns:
        if re.search(pattern, normalized):
            keyword = pattern.replace(r"\b", "").replace(r"\s+", " ")
            return {
                "status": "error",
                "data": None,
                "error": f"Security violation: Blocked SQL keyword/command detected: {keyword}"
            }

    # Verify we have at least one valid DDL starter
    # Typical DDL commands: CREATE, ALTER, DROP (except database), COMMENT
    valid_ddl_patterns = [
        r"\bCREATE\b",
        r"\bALTER\b",
        r"\bDROP\b",
        r"\bCOMMENT\b",
    ]

    has_valid_ddl = False
    for pattern in valid_ddl_patterns:
        if re.search(pattern, normalized):
            has_valid_ddl = True
            break

    if not has_valid_ddl:
        return {
            "status": "error",
            "data": None,
            "error": "Invalid SQL: Statements must contain valid DDL (CREATE, ALTER, DROP, COMMENT)."
        }

    return {"status": "success", "data": sql, "error": None}


def validate_input_request(prompt: str) -> Dict[str, Any]:
    """Validates the incoming prompt for safety and sanitization.

    NOTE: SQL injection detection on the chat prompt has been intentionally
    removed. It produced false positives for legitimate schema discussions
    (e.g. "explain DROP TABLE semantics") and gave a false sense of security
    since it never guarded the actual SQL execution paths. The real security
    boundaries are:
    - describe_table: whitelist validation + psycopg2.sql.Identifier
    - execute_sql: single-statement enforcement + SELECT-only check
    - execute_write_sql: destructive-op confirmation gate
    """
    sanitized = sanitize_input(prompt)
    if not sanitized:
        return {"status": "error", "data": None, "error": "Prompt cannot be empty"}

    if detect_prompt_injection(sanitized):
        return {
            "status": "error",
            "data": None,
            "error": "Potential security/jailbreak attempt detected in input"
        }

    return {"status": "success", "data": sanitized, "error": None}
