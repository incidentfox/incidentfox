---
name: elasticsearch-analysis
description: Elasticsearch/OpenSearch log analysis using Lucene query syntax and Query DSL. Use when investigating issues via ELK stack, OpenSearch, or any Elasticsearch-based logging.
---

# Elasticsearch Analysis

## Core Principle: Statistics Before Samples

**NEVER start by reading raw logs.** Always begin with aggregated statistics:

1. **Volume**: How many documents in the time window?
2. **Distribution**: Which services/levels/error types?
3. **Trends**: Is it increasing, stable, or decreasing?
4. **THEN sample**: Get specific entries after understanding the landscape

---

## Available Tools

| Tool | Purpose |
|------|---------|
| `search_logs` | Simple Lucene query search |
| `search_elasticsearch` | Full Query DSL search |
| `aggregate_errors_by_field` | Group errors by a field |
| `elasticsearch_list_indices` | List available indices |
| `elasticsearch_get_mapping` | Get index schema/fields |
| `get_elasticsearch_stats` | Cluster and index stats |

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

### Step 1: Discover Available Data

```python
# List indices
elasticsearch_list_indices(pattern="logs-*")

# Check index mapping (what fields exist)
elasticsearch_get_mapping(index="logs-production")

# Get cluster health and stats
get_elasticsearch_stats(index="logs-*")
```

### Step 2: Get Statistics

```python
# Count errors by service
aggregate_errors_by_field(
    field="service.keyword",
    index="logs-*",
    time_range="1h",
    min_level="error"
)

# Or with full Query DSL
search_elasticsearch(
    index="logs-*",
    query={
        "size": 0,
        "query": {"term": {"level": "ERROR"}},
        "aggs": {
            "by_service": {"terms": {"field": "service.keyword", "size": 20}}
        }
    },
    time_range="1h"
)
```

### Step 3: Analyze Error Patterns

```python
# Search for errors with Lucene syntax
search_logs(
    query="level:ERROR AND service:api-gateway",
    index="logs-*",
    time_range="1h",
    size=50
)

# Or with Query DSL for more control
search_elasticsearch(
    index="logs-*",
    query={
        "query": {
            "bool": {
                "must": [
                    {"term": {"level": "ERROR"}},
                    {"term": {"service.keyword": "api-gateway"}}
                ]
            }
        }
    },
    time_range="1h",
    size=50
)
```

### Step 4: Sample Specific Errors

```python
# Get sample error messages
search_logs(
    query='level:ERROR AND message:"connection refused"',
    index="logs-*",
    time_range="1h",
    size=10
)
```

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

### Percentile Latencies

```json
{
  "size": 0,
  "aggs": {
    "latency_percentiles": {
      "percentiles": {
        "field": "duration_ms",
        "percents": [50, 90, 95, 99]
      }
    }
  }
}
```

---

## Index Patterns

### Common Index Naming

```
# Date-based indices
logs-2024.01.15
logs-production-2024.01.15

# Patterns for searching
logs-*              # All logs
logs-production-*   # Production logs
logs-*-2024.01.*    # January 2024
```

### Discovering Indices

```python
# List all log indices
elasticsearch_list_indices(pattern="logs-*")

# Returns: name, doc_count, size, health, status
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

### Getting Field Info

```python
# Check what fields exist and their types
elasticsearch_get_mapping(index="logs-production")
```

---

## Output Format

```markdown
## Elasticsearch Analysis Summary

### Time Window
- **Start**: [timestamp]
- **End**: [timestamp]
- **Duration**: X hours

### Index Statistics
- **Indices searched**: [list of indices]
- **Total documents**: X events
- **Error count**: Y events (Z%)
- **Cluster health**: [green/yellow/red]

### Error Distribution
| Service | Error Count |
|---------|-------------|
| [service1] | N |
| [service2] | M |

### Error Timeline
[When errors started, peaked, etc.]

### Top Error Messages
1. [message]: N occurrences
2. [message]: M occurrences

### Sample Errors
[Quote 2-3 representative error messages with stack traces if available]

### Root Cause Hypothesis
[Based on patterns observed]
```

---

## Performance Tips

### Use Filters for Exact Matches

```json
// GOOD - filter is cached and faster
"bool": {
  "filter": [
    {"term": {"level": "ERROR"}}
  ]
}

// LESS OPTIMAL - must clauses calculate score
"bool": {
  "must": [
    {"term": {"level": "ERROR"}}
  ]
}
```

### Limit Result Size

```python
# GOOD - only get what you need
search_logs(..., size=50)

# BAD - retrieving too many documents
search_logs(..., size=10000)
```

### Use Aggregations Instead of Large Results

```python
# GOOD - aggregate in Elasticsearch
search_elasticsearch(
    query={"size": 0, "aggs": {"by_service": ...}},
    ...
)

# BAD - retrieve all docs and aggregate in Python
search_logs(..., size=10000)  # Then group manually
```

### Specify Source Fields

```json
// Only return needed fields
{
  "_source": ["@timestamp", "level", "message", "service"],
  "query": {...}
}
```

---

## Anti-Patterns

1. **Searching without index pattern** - Always specify `index="logs-*"` or narrower
2. **Large size without aggregation** - Use `size: 0` with aggs for stats
3. **Text field in aggregation** - Use `.keyword` suffix for terms aggs
4. **Wildcard prefix** - `*error` is expensive, prefer `error*` or exact match
5. **Unbounded time ranges** - Always specify `time_range` parameter

---

## Pro Tips

**Field discovery:**
```python
# Run this first to understand available fields
elasticsearch_get_mapping(index="logs-production")
```

**Keyword suffix:**
Most text fields have a `.keyword` subfield for exact matches:
- `message` → full-text search
- `message.keyword` → exact match, aggregation

**Date math in ranges:**
```json
"range": {
  "@timestamp": {
    "gte": "now-1h",
    "lte": "now"
  }
}
```

**Index lifecycle:**
Indices are often rotated daily. Search recent indices for faster queries:
```python
elasticsearch_list_indices(pattern="logs-*")  # Check date-based names
```
