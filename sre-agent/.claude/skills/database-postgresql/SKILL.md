---
name: database-postgresql
description: PostgreSQL database inspection and queries. Use when investigating table schemas, running queries, checking locks, replication status, or long-running queries.
allowed-tools: Bash(python *)
---

# PostgreSQL Database

## Authentication

**IMPORTANT**: Credentials are injected automatically by a proxy layer. Do NOT check for `POSTGRES_PASSWORD` in environment variables - it won't be visible to you. Just run the scripts directly; authentication is handled transparently.

Configuration environment variables you CAN check (non-secret):
- `POSTGRES_HOST` - Database host
- `POSTGRES_PORT` - Database port (default: 5432)
- `POSTGRES_DATABASE` - Database name
- `POSTGRES_SCHEMA` - Default schema (default: public)

---

## MANDATORY: Schema-First Investigation

**Understand the schema before running queries.**

```
LIST TABLES → DESCRIBE TABLE → EXECUTE QUERY → CHECK HEALTH
```

## Available Scripts

All scripts are in `.claude/skills/database-postgresql/scripts/`

### list_tables.py - List Tables (START HERE)
```bash
python .claude/skills/database-postgresql/scripts/list_tables.py [--schema public]
```

### describe_table.py - Table Schema Details
```bash
python .claude/skills/database-postgresql/scripts/describe_table.py --table TABLE_NAME [--schema public]
```

### execute_query.py - Run SQL Queries
```bash
python .claude/skills/database-postgresql/scripts/execute_query.py --query "SELECT * FROM users WHERE created_at > now() - interval '1 hour'" [--limit 100]
```

### list_indexes.py - Index Information
```bash
python .claude/skills/database-postgresql/scripts/list_indexes.py [--table TABLE_NAME] [--schema public]
```

### get_table_sizes.py - Table Size Analysis
```bash
python .claude/skills/database-postgresql/scripts/get_table_sizes.py [--table TABLE_NAME] [--schema public]
```

### get_locks.py - Current Locks & Blocking Queries
```bash
python .claude/skills/database-postgresql/scripts/get_locks.py
```

### get_replication_status.py - Replication Health
```bash
python .claude/skills/database-postgresql/scripts/get_replication_status.py
```

### get_long_running_queries.py - Long-Running Queries
```bash
python .claude/skills/database-postgresql/scripts/get_long_running_queries.py [--min-duration 60]
```

---

## Investigation Workflow

### Lock Contention
```
1. get_locks.py (find blocking relationships)
2. get_long_running_queries.py --min-duration 30
3. execute_query.py --query "SELECT * FROM pg_stat_activity WHERE state = 'active'"
```

### Replication Lag
```
1. get_replication_status.py (check lag_bytes/lag_seconds)
2. get_long_running_queries.py (queries blocking replication)
```

### Table Growth Investigation
```
1. get_table_sizes.py (find largest tables)
2. list_indexes.py --table <table> (check index health)
3. describe_table.py --table <table>
```
