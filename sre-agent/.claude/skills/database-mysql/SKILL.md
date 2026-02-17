---
name: database-mysql
description: MySQL/MariaDB database inspection and queries. Use when investigating table schemas, running queries, checking processlist, replication status, InnoDB engine status, or lock contention.
allowed-tools: Bash(python *)
---

# MySQL Database

## Authentication

**IMPORTANT**: Credentials are injected automatically by a proxy layer. Do NOT check for `MYSQL_PASSWORD` in environment variables - it won't be visible to you. Just run the scripts directly; authentication is handled transparently.

Configuration environment variables you CAN check (non-secret):
- `MYSQL_HOST` - Database host
- `MYSQL_PORT` - Database port (default: 3306)
- `MYSQL_DATABASE` - Database name

---

## MANDATORY: Schema-First Investigation

**Understand the schema before running queries.**

```
LIST TABLES → DESCRIBE TABLE → EXECUTE QUERY → CHECK HEALTH
```

## Available Scripts

All scripts are in `.claude/skills/database-mysql/scripts/`

### list_tables.py - List Tables (START HERE)
```bash
python .claude/skills/database-mysql/scripts/list_tables.py [--database DB]
```

### describe_table.py - Table Schema Details
```bash
python .claude/skills/database-mysql/scripts/describe_table.py --table TABLE_NAME [--database DB]
```

### execute_query.py - Run SQL Queries
```bash
python .claude/skills/database-mysql/scripts/execute_query.py --query "SELECT * FROM users LIMIT 10" [--limit 100]
```

### show_processlist.py - Active Connections
```bash
python .claude/skills/database-mysql/scripts/show_processlist.py [--full]
```

### show_replica_status.py - Replication Health
```bash
python .claude/skills/database-mysql/scripts/show_replica_status.py
```

### show_engine_status.py - InnoDB Engine Status
```bash
python .claude/skills/database-mysql/scripts/show_engine_status.py [--engine innodb]
```

### get_table_locks.py - Lock Contention
```bash
python .claude/skills/database-mysql/scripts/get_table_locks.py
```

---

## Investigation Workflow

### Slow Query Investigation
```
1. show_processlist.py --full (find active/long queries)
2. show_engine_status.py (check InnoDB lock waits, deadlocks)
3. get_table_locks.py (find lock contention)
```

### Replication Lag
```
1. show_replica_status.py (check Seconds_Behind_Master)
2. show_processlist.py (check for blocking queries)
```
