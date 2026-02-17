---
name: database-snowflake
description: Snowflake data warehouse queries and schema inspection. Use when running SQL queries against Snowflake, listing tables, or inspecting schemas.
allowed-tools: Bash(python *)
---

# Snowflake Data Warehouse

## Authentication

**IMPORTANT**: Credentials are injected automatically by a proxy layer. Do NOT check for `SNOWFLAKE_PASSWORD` in environment variables - it won't be visible to you. Just run the scripts directly; authentication is handled transparently.

Configuration environment variables you CAN check (non-secret):
- `SNOWFLAKE_ACCOUNT` - Snowflake account identifier
- `SNOWFLAKE_WAREHOUSE` - Compute warehouse
- `SNOWFLAKE_DATABASE` - Default database
- `SNOWFLAKE_SCHEMA` - Default schema

---

## MANDATORY: Schema-First Investigation

**Always get the schema before writing queries.**

```
GET SCHEMA / LIST TABLES → DESCRIBE TABLE → EXECUTE QUERY
```

## Available Scripts

All scripts are in `.claude/skills/database-snowflake/scripts/`

### get_schema.py - Get Database Schema (START HERE)
```bash
python .claude/skills/database-snowflake/scripts/get_schema.py
```

### list_tables.py - List Tables
```bash
python .claude/skills/database-snowflake/scripts/list_tables.py [--database DB] [--schema SCHEMA]
```

### describe_table.py - Table Column Details
```bash
python .claude/skills/database-snowflake/scripts/describe_table.py --table TABLE_NAME [--database DB] [--schema SCHEMA]
```

### execute_query.py - Run SQL Queries
```bash
python .claude/skills/database-snowflake/scripts/execute_query.py --query "SELECT * FROM fact_incident ORDER BY started_at DESC LIMIT 10" [--limit 100]
```

---

## Investigation Workflow

### Incident Data Analysis
```
1. get_schema.py (understand available tables)
2. execute_query.py --query "SELECT * FROM fact_incident WHERE sev = 'SEV-1' ORDER BY started_at DESC LIMIT 10"
3. execute_query.py --query "SELECT c.customer_name, ic.estimated_arr_at_risk_usd FROM fact_incident_customer_impact ic JOIN dim_customer c ON ic.customer_id = c.customer_id WHERE ic.incident_id = '<id>'"
```
