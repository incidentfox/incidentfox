---
name: honeycomb-analysis
description: Honeycomb observability analysis. Use when querying Honeycomb datasets, traces, or metrics. Provides scripts and query syntax reference for high-cardinality exploration.
allowed-tools: Bash(python *)
---

# Honeycomb Analysis

## Authentication

**IMPORTANT**: Credentials are injected automatically by a proxy layer. Do NOT check for `HONEYCOMB_API_KEY` in environment variables - it won't be visible to you. Just run the scripts directly; authentication is handled transparently.

Configuration environment variables you CAN check (non-secret):
- `HONEYCOMB_API_ENDPOINT` - Honeycomb API endpoint (default: `https://api.honeycomb.io`)

---

## MANDATORY: Statistics-First Investigation

**NEVER dump raw events.** Always follow this pattern:

```
STATISTICS → SAMPLE → PATTERNS → CORRELATE
```

1. **Statistics First** - Know volume, error rate, and top patterns before sampling
2. **Strategic Sampling** - Choose the right strategy based on statistics
3. **Pattern Extraction** - Cluster similar errors to find root causes
4. **Context Correlation** - Investigate around anomaly timestamps

## Available Scripts

All scripts are in `.claude/skills/observability-honeycomb/scripts/`

### PRIMARY INVESTIGATION SCRIPTS

#### get_statistics.py - ALWAYS START HERE
Comprehensive statistics with pattern extraction.
```bash
python .claude/skills/observability-honeycomb/scripts/get_statistics.py DATASET [--time-range SECONDS] [--filter FILTER]

# Examples:
python .claude/skills/observability-honeycomb/scripts/get_statistics.py production --time-range 3600
python .claude/skills/observability-honeycomb/scripts/get_statistics.py api-requests --filter "http.status_code >= 500"
```

Output includes:
- Total event count
- Error distribution by status code
- Top services/endpoints
- **Top error patterns** (crucial for quick triage)
- Actionable recommendation

#### run_query.py - Custom Queries
Run custom analytics queries with aggregations.
```bash
python .claude/skills/observability-honeycomb/scripts/run_query.py DATASET --calc CALCULATION [--breakdown FIELD] [--filter FILTER]

# Calculations: COUNT, SUM, AVG, MAX, MIN, P50, P75, P90, P95, P99, HEATMAP, COUNT_DISTINCT
# Examples:
python .claude/skills/observability-honeycomb/scripts/run_query.py production --calc COUNT
python .claude/skills/observability-honeycomb/scripts/run_query.py production --calc P99 --column duration_ms --breakdown service.name
python .claude/skills/observability-honeycomb/scripts/run_query.py production --calc COUNT --filter "http.status_code >= 500" --breakdown error.message
```

#### list_datasets.py - Dataset Discovery
List available datasets in the environment.
```bash
python .claude/skills/observability-honeycomb/scripts/list_datasets.py

# Output: List of datasets with names and last write times
```

---

## Honeycomb Query Concepts

### Calculations (Aggregations)

| Calculation | Description | Example |
|-------------|-------------|---------|
| `COUNT` | Count events | Total requests |
| `SUM` | Sum a column | Total bytes transferred |
| `AVG` | Average value | Average duration |
| `MAX` / `MIN` | Extremes | Peak latency |
| `P50`, `P75`, `P90`, `P95`, `P99` | Percentiles | P99 latency |
| `HEATMAP` | Distribution | Latency heatmap |
| `COUNT_DISTINCT` | Unique values | Unique users |
| `RATE_AVG`, `RATE_SUM`, `RATE_MAX` | Rate per second | Requests/second |

### Filters

Filters use operators to narrow results:
```
column = value          # Exact match
column != value         # Not equal
column > value          # Greater than
column >= value         # Greater or equal
column < value          # Less than
column <= value         # Less or equal
column exists           # Field exists
column does-not-exist   # Field missing
column contains "str"   # Contains substring
column starts-with "s"  # Starts with prefix
column in (a, b, c)     # In set
```

### Breakdowns (Group By)

Breakdowns split results by field values:
```bash
# Group by service
--breakdown service.name

# Multiple breakdowns
--breakdown service.name --breakdown http.method
```

### Common Fields

Honeycomb typically has these fields (varies by instrumentation):
```
# Trace fields
trace.trace_id
trace.span_id
trace.parent_id
duration_ms
name

# HTTP fields
http.method
http.url
http.status_code
http.host

# Service fields
service.name
service.version

# Error fields
error
error.message
exception.type
exception.message
```

---

## Investigation Workflow

### Standard Incident Investigation

```
┌─────────────────────────────────────────────────────────────┐
│ 1. STATISTICS FIRST (mandatory)                              │
│    python get_statistics.py <dataset>                        │
│    → Know volume, error rate, top patterns                   │
└─────────────────────────────────────────────────────────────┘
                             │
                             ▼
                     High Error Rate?
               ┌─────────────┴─────────────┐
               │                           │
       YES (>5%)                           NO
               │                           │
               ▼                           ▼
┌─────────────────────────────┐  ┌───────────────────────────────────────────┐
│ 2. FAST PATH                │  │ 2. TARGETED INVESTIGATION                 │
│    Query errors directly    │  │    Filter by specific criteria            │
│    python run_query.py      │  │    python run_query.py dataset            │
│    --filter "error=true"    │  │    --filter "duration_ms > 1000"          │
│    --breakdown error.message│  │    → Look for anomalies                   │
└─────────────────────────────┘  └───────────────────────────────────────────┘
```

### Quick Commands Reference

| Goal | Command |
|------|---------|
| Start investigation | `get_statistics.py <dataset>` |
| Count errors | `run_query.py <dataset> --calc COUNT --filter "error=true"` |
| P99 latency by service | `run_query.py <dataset> --calc P99 --column duration_ms --breakdown service.name` |
| Error distribution | `run_query.py <dataset> --calc COUNT --filter "error=true" --breakdown error.message` |
| List datasets | `list_datasets.py` |

---

## SLOs and Triggers

### Checking SLOs
```bash
python .claude/skills/observability-honeycomb/scripts/run_query.py <dataset> --list-slos
```

### Checking Triggers (Alerts)
```bash
python .claude/skills/observability-honeycomb/scripts/run_query.py <dataset> --list-triggers
```

---

## Anti-Patterns to Avoid

1. **NEVER skip statistics** - `get_statistics.py` is MANDATORY first step
2. **Unbounded queries** - Always specify time ranges (default: 1 hour)
3. **Fetching all events** - Use aggregations, not raw event dumps
4. **Ignoring error rate** - High error rate means immediate investigation
5. **Missing service filter** - For multi-service datasets, always filter by service

## Key Differences from Other Platforms

- **High cardinality native** - Honeycomb excels at high-cardinality fields (user IDs, request IDs)
- **No pre-aggregation** - Queries run on raw events, enabling ad-hoc exploration
- **Trace-first** - Designed for distributed tracing, not just logs
- **BubbleUp** - Use breakdowns to identify anomalous dimensions automatically
