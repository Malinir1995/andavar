---
name: andavar-schema-agent
description: >
  Andavar is a multi-agent PostgreSQL schema designer. Use this skill when the
  user asks to design a database schema, generate SQL, explain table
  relationships, validate a schema, or iterate on an existing design. Triggers
  include: "design a schema", "create tables for", "generate SQL for",
  "what tables do I need", "normalise this", "add a relationship", or any
  natural-language description of a system that implies data storage.
---

# Andavar — Schema Agent Skill

## What Andavar Does
Andavar takes a plain-English description of a system and produces:
1. A normalised relational schema (tables, columns, types, constraints)
2. PostgreSQL-compatible `CREATE TABLE` SQL
3. A plain-English explanation of every design decision

## Agent Architecture
Andavar runs three specialist agents orchestrated by a root agent:

| Agent | Role |
|---|---|
| `schema_designer` | Analyses the requirement, identifies entities, attributes, and relationships, and proposes a normalised schema |
| `sql_generator` | Converts the schema design into valid PostgreSQL DDL (`CREATE TABLE`, primary keys, foreign keys, indexes) |
| `explainer` | Writes a plain-English breakdown of the schema: why each table exists, what each relationship means, and any trade-offs made |

## How to Invoke
Describe the system you want to model. Be as vague or as detailed as you like.

**Examples:**
- "Design a schema for a university course registration system"
- "I need tables for a multi-tenant SaaS billing platform"
- "Add soft-delete support to the existing users table"
- "Normalise this: orders have customer name, email, item name, item price"

## Output Format
Andavar always returns three sections in order:

```
### Schema Design
<entity-relationship summary>

### SQL
<PostgreSQL CREATE TABLE statements>

### Explanation
<plain-English rationale>
```

## Constraints the Skill Enforces
- All tables must have a primary key
- Foreign keys must be explicit with `ON DELETE` behaviour stated
- No `SELECT *` in generated queries
- UUIDs preferred over serial integers for primary keys
- All timestamps as `TIMESTAMPTZ`
- Snake_case naming throughout

## Memory Behaviour
Andavar remembers prior schema iterations within a session. You can say:
- "Add a field for profile pictures to the previous schema"
- "Show me the diff from the last version"
- "Revert to version 1"

## Security Guardrails
- Input is validated before reaching the LLM
- SQL output is DDL only — no DML (`INSERT`, `UPDATE`, `DELETE`) is generated
- No credentials, connection strings, or secrets are accepted as input
- Prompt injection patterns are detected and blocked

## Files of Interest
```
andavar/
├── agents/
│   ├── root_agent.py        ← orchestrator
│   ├── schema_designer.py   ← entity analysis
│   ├── sql_generator.py     ← DDL generation
│   └── explainer.py         ← plain-English rationale
├── tools/
│   ├── validator.py         ← input + schema validation
│   └── memory_store.py      ← session schema history
├── app.py                   ← FastAPI entry point
├── frontend/index.html      ← single-file UI
├── Dockerfile
└── docker-compose.yml
```
