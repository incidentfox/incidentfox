---
name: database-bigquery
description: Google BigQuery data warehouse queries and schema inspection. Use when running SQL queries, listing datasets/tables, or inspecting table schemas in BigQuery.
allowed-tools: Bash(python *)
---

# BigQuery Data Warehouse

## Authentication

**IMPORTANT**: Credentials are injected automatically by a proxy layer. Do NOT check for `BIGQUERY_SERVICE_ACCOUNT_KEY` in environment variables - it won't be visible to you. Just run the scripts directly; authentication is handled transparently.

Configuration environment variables you CAN check (non-secret):
- `BIGQUERY_PROJECT_ID` - GCP project ID
- `BIGQUERY_DATASET` - Default dataset

---

## MANDATORY: Schema-First Investigation

**List datasets and tables before writing queries.**

```
LIST DATASETS → LIST TABLES → GET TABLE SCHEMA → QUERY
```

## Safety Constraints

- **Read-only**: Only SELECT, SHOW, DESCRIBE, WITH are allowed. DML/DDL (INSERT, UPDATE, DELETE, DROP, etc.) is blocked.
- **Cost control**: Queries are capped at 10 GB bytes billed by default. Override with `--max-bytes-billed` only when justified.
- **ALWAYS add LIMIT**: BigQuery scans entire partitions. Never run `SELECT *` without LIMIT and a WHERE clause on the partition key.
- **Use partition filters**: For time-partitioned tables, always filter on `_PARTITIONTIME` or the partition column to avoid full-table scans.
- **Start small**: Use `--max-results 100` first, increase only if the initial results are insufficient.

## Available Scripts

All scripts are in `.claude/skills/database-bigquery/scripts/`

### list_datasets.py - List Datasets (START HERE)
```bash
python .claude/skills/database-bigquery/scripts/list_datasets.py
```

### list_tables.py - List Tables in Dataset
```bash
python .claude/skills/database-bigquery/scripts/list_tables.py --dataset DATASET_ID
```

### get_table_schema.py - Table Schema Details
```bash
python .claude/skills/database-bigquery/scripts/get_table_schema.py --dataset DATASET_ID --table TABLE_ID
```

### query.py - Run SQL Queries (read-only)
```bash
python .claude/skills/database-bigquery/scripts/query.py --query "SELECT * FROM dataset.table WHERE _PARTITIONTIME >= TIMESTAMP('2026-03-01') LIMIT 10" [--dataset DEFAULT_DATASET] [--max-results 1000] [--max-bytes-billed 10737418240]
```

**IMPORTANT**: Always include LIMIT and partition filters. Queries without these on large tables will be expensive.

---

## BigQuery SQL Reference

```sql
-- Standard SQL (default) — ALWAYS include LIMIT
SELECT * FROM `project.dataset.table` LIMIT 10

-- Aggregate with time — use partition filter to control cost
SELECT DATE(timestamp), COUNT(*) as events
FROM `dataset.events`
WHERE timestamp > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY 1 ORDER BY 1 DESC

-- Partitioned table query (cost-efficient) — MANDATORY for large tables
SELECT * FROM `dataset.events`
WHERE _PARTITIONTIME >= TIMESTAMP('2026-01-01')
LIMIT 100
```

---

## Anti-Patterns to Avoid

1. ❌ **`SELECT * FROM table`** without LIMIT — scans entire table, potentially TBs
2. ❌ **Missing partition filter** — on partitioned tables, always filter by partition key
3. ❌ **`COUNT(*)` on huge tables** without WHERE — use approximate: `APPROX_COUNT_DISTINCT()`
4. ❌ **Skipping schema inspection** — always run `get_table_schema.py` first to understand columns and partitioning

---

## Investigation Workflow

### Data Analysis
```
1. list_datasets.py (find available datasets)
2. list_tables.py --dataset <dataset> (find tables)
3. get_table_schema.py --dataset <dataset> --table <table>
4. query.py --query "SELECT ..."
```
