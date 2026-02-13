---
name: victorialogs-analysis
description: VictoriaLogs log analysis using LogsQL. Use when querying logs stored in VictoriaLogs. Provides statistics-first investigation with server-side aggregation.
allowed-tools: Bash(python *)
---

# VictoriaLogs Analysis

Query and analyze logs from VictoriaLogs for incident investigation and debugging.

## Authentication

**IMPORTANT**: Credentials are injected automatically by a proxy layer. Do NOT check for `VICTORIALOGS_TOKEN` in environment variables - they won't be visible to you. Just run the scripts directly; authentication is handled transparently.

---

## MANDATORY: Statistics-First Investigation

**NEVER dump raw logs.** Always follow this pattern:

```
STATISTICS → FIELDS → SAMPLE → QUERY
```

1. **Statistics First** — Know volume, error rate, top streams before looking at logs
2. **Field Discovery** — Understand what fields exist (helps build targeted queries)
3. **Strategic Sampling** — See representative errors only (max 20 entries)
4. **Targeted Query** — Only if needed, always with `| stats` or `| limit`

## Available Scripts

All scripts are in `.claude/skills/observability-victorialogs/scripts/`

### PRIMARY INVESTIGATION SCRIPTS

#### get_statistics.py — ALWAYS START HERE
Comprehensive statistics using server-side LogsQL aggregation.
```bash
python .claude/skills/observability-victorialogs/scripts/get_statistics.py
python .claude/skills/observability-victorialogs/scripts/get_statistics.py --query '_stream:{app="api"}'
python .claude/skills/observability-victorialogs/scripts/get_statistics.py --time-range 120 --json
```

Output includes:
- Total count, error count, error rate percentage
- Logs per minute
- Top 10 streams by volume
- Top error patterns (normalized and deduplicated)
- Actionable recommendation

#### sample_logs.py — Strategic Sampling
Choose the right sampling strategy based on statistics.
```bash
python .claude/skills/observability-victorialogs/scripts/sample_logs.py --strategy errors_only
python .claude/skills/observability-victorialogs/scripts/sample_logs.py --query '_stream:{app="api"}' --strategy errors_only
python .claude/skills/observability-victorialogs/scripts/sample_logs.py --strategy around_time --timestamp "2026-01-27T05:00:00Z" --window 5
python .claude/skills/observability-victorialogs/scripts/sample_logs.py --strategy all --limit 20
```

Strategies:
- `errors_only` — Only error/exception/fail logs (default)
- `warnings_up` — Warning and error logs
- `around_time` — Logs around a specific timestamp
- `all` — All log levels

#### list_fields.py — Metadata Discovery
Discover available fields before building queries.
```bash
python .claude/skills/observability-victorialogs/scripts/list_fields.py
python .claude/skills/observability-victorialogs/scripts/list_fields.py --query '_stream:{app="api"}'
python .claude/skills/observability-victorialogs/scripts/list_fields.py --field level
python .claude/skills/observability-victorialogs/scripts/list_fields.py --field service --limit 20 --json
```

#### query_logs.py — Raw LogsQL (escape hatch)
Execute raw LogsQL queries. Safety limit auto-appended if missing.
```bash
python .claude/skills/observability-victorialogs/scripts/query_logs.py --query 'error | stats by (service) count() hits | sort by (hits) desc'
python .claude/skills/observability-victorialogs/scripts/query_logs.py --query '_stream:{app="api"} AND timeout' --limit 10
python .claude/skills/observability-victorialogs/scripts/query_logs.py --query 'status:>=500 | stats count() total' --json
```

---

## LogsQL Quick Reference

### Filters (what logs to select)

```logsql
# Word search (searches _msg field by default)
error
"connection timeout"

# Field-specific match
level:error
service:payment
status:500

# Stream selector (efficient — uses indexed stream labels)
_stream:{app="api"}
_stream:{app="api", namespace="production"}

# Negation
NOT error
NOT level:debug

# Logical operators
error AND timeout
error OR exception OR fatal

# Numeric comparison
status:>=500
duration:>1000

# Regex
_msg:~"timeout.*connection"
service:~"payment-.*"
```

### Pipes (post-processing)

```logsql
# Limit results (ALWAYS use this or | stats)
error | limit 20

# Select specific fields
error | fields _time, _msg, service, level

# Sort
error | sort by (_time) desc

# Deduplicate
error | uniq by (service, _msg)

# Statistics (server-side aggregation — most context-efficient)
error | stats count() total
error | stats by (service) count() hits | sort by (hits) desc | limit 10
* | stats by (level) count() hits

# Available stats functions:
#   count(), sum(field), avg(field), min(field), max(field),
#   count_uniq(field), uniq_values(field)
```

### Common Patterns

```logsql
# Count errors by service
error OR exception | stats by (service) count() errors | sort by (errors) desc

# Find unique error messages
error | stats by (_msg) count() hits | sort by (hits) desc | limit 10

# Errors in a specific time window (use --start/--end in scripts)
_stream:{app="api"} AND error | limit 20

# HTTP 5xx errors
status:>=500 | stats by (path) count() hits | sort by (hits) desc

# Slow requests
duration:>1000 | stats by (service) count() slow | sort by (slow) desc
```

---

## Investigation Workflows

### Standard Incident Investigation

```
┌───────────────────────────────────────────────────┐
│ 1. STATISTICS FIRST (mandatory)                   │
│    python get_statistics.py                       │
│    → Know volume, error rate, top streams         │
└───────────────────────────────────────────────────┘
                         │
                         ▼
                 High Error Rate?
           ┌─────────────┴─────────────┐
           │                           │
   YES (>5%)                           NO
           │                           │
           ▼                           ▼
┌───────────────────────┐  ┌────────────────────────┐
│ 2. FAST PATH          │  │ 2. DISCOVER FIELDS     │
│    sample_logs.py     │  │    list_fields.py      │
│    --strategy         │  │    → Understand schema │
│    errors_only        │  │    → Build targeted    │
│                       │  │      query             │
└───────────────────────┘  └────────────────────────┘
```

### Quick Commands Reference

| Goal | Command |
|------|---------|
| Start investigation | `get_statistics.py` |
| Discover fields | `list_fields.py --query '_stream:{app="X"}'` |
| Sample errors | `sample_logs.py --strategy errors_only` |
| Investigate spike | `sample_logs.py --strategy around_time --timestamp T` |
| Count by service | `query_logs.py --query 'error \| stats by (service) count() hits'` |

---

## Anti-Patterns to Avoid

1. **NEVER run a bare query without `| limit` or `| stats`** — Scripts auto-append limits as safety net, but write efficient queries
2. **NEVER skip `get_statistics.py`** — It's the mandatory first step
3. **NEVER fetch all logs** — Use sampling strategies and aggregation
4. **NEVER ignore error rate** — High error rate means investigate patterns, not dump logs
5. **NEVER query without time bounds** — Always specify `--time-range` or use defaults
