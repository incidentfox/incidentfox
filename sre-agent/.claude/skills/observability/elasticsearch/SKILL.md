---
name: elasticsearch-analysis
description: Elasticsearch/OpenSearch log analysis using Lucene query syntax and Query DSL. Use when investigating issues via ELK stack, OpenSearch, or any Elasticsearch-based logging.
---

# Elasticsearch Analysis

## Authentication

**IMPORTANT**: Credentials are injected automatically by a proxy layer. Do NOT check for `ELASTICSEARCH_URL`, `ES_USER`, or `ES_PASSWORD` in environment variables - they won't be visible to you. Just run the scripts directly; authentication is handled transparently.

---

## MANDATORY: Statistics-First Investigation

**NEVER dump raw logs.** Always follow this pattern:

```
STATISTICS → SAMPLE → PATTERNS → CORRELATE
```

1. **Statistics First** - Know volume, error rate, and top patterns before sampling
2. **Strategic Sampling** - Choose the right strategy based on statistics
3. **Pattern Extraction** - Cluster similar errors to find root causes
4. **Context Correlation** - Investigate around anomaly timestamps

## Available Scripts

All scripts are in `.claude/skills/observability/elasticsearch/scripts/`

### PRIMARY INVESTIGATION SCRIPTS

#### get_statistics.py - ALWAYS START HERE
Comprehensive statistics with pattern extraction.
```bash
python .claude/skills/observability/elasticsearch/scripts/get_statistics.py [--index INDEX] [--time-range MINUTES]

# Examples:
python .claude/skills/observability/elasticsearch/scripts/get_statistics.py --time-range 60
python .claude/skills/observability/elasticsearch/scripts/get_statistics.py --index logs-production
```

Output includes:
- Total count, error count, error rate percentage
- Status distribution (info, warn, error)
- Top services/sources by log volume
- **Top error patterns** (crucial for quick triage)
- Actionable recommendation

#### sample_logs.py - Strategic Sampling
Choose the right sampling strategy based on statistics.
```bash
python .claude/skills/observability/elasticsearch/scripts/sample_logs.py --strategy STRATEGY [--index INDEX] [--limit N]

# Strategies:
#   errors_only   - Only error logs (default for incidents)
#   warnings_up   - Warning and error logs
#   around_time   - Logs around a specific timestamp
#   all           - All log levels

# Examples:
python .claude/skills/observability/elasticsearch/scripts/sample_logs.py --strategy errors_only --index logs-production
python .claude/skills/observability/elasticsearch/scripts/sample_logs.py --strategy around_time --timestamp "2026-01-27T05:00:00Z" --window 5
```

---

## Lucene Query Syntax

### Basic Searches

```lucene
# Simple term
error

# Phrase
"connection refused"

# Field search
level:ERROR

# Wildcard
message:timeout*

# Multiple terms (implicit OR)
error warning

# Required term (AND)
+error +timeout
```

### Field Queries

```lucene
# Exact match
level:ERROR

# Wildcard
host:web-*

# Range (numeric)
status:[400 TO 599]

# Range (dates)
@timestamp:[2024-01-15T10:00:00 TO 2024-01-15T11:00:00]

# Exists
_exists_:error.stack_trace
```

### Boolean Operators

```lucene
# AND
error AND timeout

# OR
error OR warning

# NOT
error NOT debug

# Grouping
(error OR warning) AND service:api
```

---

## Query DSL (JSON)

### Match Query

```json
{
  "query": {
    "match": {
      "message": "connection error"
    }
  }
}
```

### Term Query (Exact Match)

```json
{
  "query": {
    "term": {
      "level": "ERROR"
    }
  }
}
```

### Bool Query (Compound)

```json
{
  "query": {
    "bool": {
      "must": [
        {"term": {"level": "ERROR"}},
        {"match": {"message": "timeout"}}
      ],
      "must_not": [
        {"term": {"service": "healthcheck"}}
      ],
      "filter": [
        {"range": {"@timestamp": {"gte": "now-1h"}}}
      ]
    }
  }
}
```

### Aggregations

```json
{
  "size": 0,
  "aggs": {
    "errors_by_service": {
      "terms": {
        "field": "service.keyword",
        "size": 10
      }
    }
  }
}
```

---

## Investigation Workflow

### Standard Incident Investigation

```
┌─────────────────────────────────────────────────────────────┐
│ 1. STATISTICS FIRST (mandatory)                              │
│    python get_statistics.py --index <index>                  │
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
│    Sample errors directly   │  │    Filter by specific criteria            │
│    python sample_logs.py    │  │    python sample_logs.py --strategy all   │
│    --strategy errors_only   │  │    → Look for anomalies                   │
└─────────────────────────────┘  └───────────────────────────────────────────┘
```

### Quick Commands Reference

| Goal | Command |
|------|---------|
| Start investigation | `get_statistics.py --index X` |
| Sample errors only | `sample_logs.py --strategy errors_only --index X` |
| Investigate spike | `sample_logs.py --strategy around_time --timestamp T` |
| All logs | `sample_logs.py --strategy all --index X --limit 20` |

---

## Common Aggregation Patterns

### Errors Over Time

```json
{
  "size": 0,
  "query": {"term": {"level": "ERROR"}},
  "aggs": {
    "errors_over_time": {
      "date_histogram": {
        "field": "@timestamp",
        "fixed_interval": "5m"
      }
    }
  }
}
```

### Top Error Messages

```json
{
  "size": 0,
  "query": {"term": {"level": "ERROR"}},
  "aggs": {
    "top_errors": {
      "terms": {
        "field": "message.keyword",
        "size": 10
      }
    }
  }
}
```

### Nested Aggregation (Errors by Service, then by Message)

```json
{
  "size": 0,
  "aggs": {
    "by_service": {
      "terms": {"field": "service.keyword", "size": 10},
      "aggs": {
        "by_message": {
          "terms": {"field": "message.keyword", "size": 5}
        }
      }
    }
  }
}
```

---

## Field Types

### Keyword vs Text

- **keyword**: Exact match, aggregatable (`service.keyword`)
- **text**: Full-text search, not aggregatable (`message`)

```json
// For aggregation, use .keyword suffix
"terms": {"field": "service.keyword"}

// For full-text search, use text field
"match": {"message": "connection error"}
```

---

## Anti-Patterns to Avoid

1. ❌ **NEVER skip statistics** - `get_statistics.py` is MANDATORY first step
2. ❌ **Unbounded queries** - Always specify time ranges and limits
3. ❌ **Fetching all logs** - Use sampling strategies, not unbounded searches
4. ❌ **Ignoring error rate** - High error rate means immediate investigation
5. ❌ **Text field in aggregation** - Use `.keyword` suffix for terms aggs
6. ❌ **Wildcard prefix** - `*error` is expensive, prefer `error*` or exact match
