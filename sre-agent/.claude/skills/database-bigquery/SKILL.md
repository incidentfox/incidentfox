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

### query.py - Run SQL Queries
```bash
python .claude/skills/database-bigquery/scripts/query.py --query "SELECT * FROM dataset.table LIMIT 10" [--dataset DEFAULT_DATASET] [--max-results 1000]
```

---

## BigQuery SQL Reference

```sql
-- Standard SQL (default)
SELECT * FROM `project.dataset.table` LIMIT 10

-- Aggregate with time
SELECT DATE(timestamp), COUNT(*) as events
FROM `dataset.events`
WHERE timestamp > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY 1 ORDER BY 1 DESC

-- Partitioned table query (cost-efficient)
SELECT * FROM `dataset.events`
WHERE _PARTITIONTIME >= TIMESTAMP('2026-01-01')
```

---

## Investigation Workflow

### Data Analysis
```
1. list_datasets.py (find available datasets)
2. list_tables.py --dataset <dataset> (find tables)
3. get_table_schema.py --dataset <dataset> --table <table>
4. query.py --query "SELECT ..."
```
