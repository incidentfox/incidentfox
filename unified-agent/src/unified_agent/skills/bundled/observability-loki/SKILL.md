---
name: observability-loki
description: Query and analyze logs from Grafana Loki using LogQL
category: observability
required_integrations:
  - loki
allowed-tools:
  - Bash
---

# Loki Log Analysis Skill

Query and analyze logs from Grafana Loki for incident investigation and debugging.

## Investigation Workflow

1. **List available labels** to understand what's queryable
2. **Get statistics** to understand log volume and error rates
3. **Sample logs** to see representative entries
4. **Query specific patterns** with LogQL

## LogQL Quick Reference

### Stream Selectors (required)
```logql
{app="frontend"}                    # Exact match
{namespace=~"prod-.*"}              # Regex match
{container!="sidecar"}              # Not equal
{pod=~".+"}                         # Any non-empty value
```

### Line Filters
```logql
{app="api"} |= "error"              # Contains "error"
{app="api"} != "debug"              # Does not contain
{app="api"} |~ "error|warn"         # Regex match
{app="api"} !~ "health|ready"       # Regex not match
```

### Parser & Label Extraction
```logql
{app="api"} | json                  # Parse JSON logs
{app="api"} | logfmt                # Parse logfmt
{app="api"} | pattern `<ip> - <_> [<timestamp>] "<method> <path>"`
{app="api"} | json | level="error"  # Filter on extracted labels
```

### Aggregations (Metric Queries)
```logql
# Count logs per second
rate({app="api"}[5m])

# Count errors per minute
sum(rate({app="api"} |= "error" [1m])) by (pod)

# Bytes processed
bytes_rate({app="api"}[5m])

# Unique values
count_over_time({app="api"} | json | __error__="" [1h])
```

## Available Scripts

### list_labels.py
List available labels and their values.
```bash
python scripts/list_labels.py
python scripts/list_labels.py --label app
python scripts/list_labels.py --label namespace --json
```

### get_statistics.py
Get log volume and error statistics.
```bash
python scripts/get_statistics.py --selector '{app="frontend"}'
python scripts/get_statistics.py --selector '{namespace="production"}' --lookback 2
python scripts/get_statistics.py --selector '{app=~"api.*"}' --json
```

### sample_logs.py
Get sample log entries.
```bash
python scripts/sample_logs.py --selector '{app="frontend"}'
python scripts/sample_logs.py --selector '{app="api"}' --filter "error"
python scripts/sample_logs.py --selector '{namespace="prod"}' --limit 50 --json
```

### query_logs.py
Execute raw LogQL queries.
```bash
python scripts/query_logs.py '{app="api"} |= "error" | json'
python scripts/query_logs.py 'rate({app="api"} |= "error" [5m])' --type metric
python scripts/query_logs.py '{app="api"}' --limit 100 --lookback 2 --json
```

## Environment Variables

- `LOKI_BASE_URL`: Proxy endpoint (production)
- `LOKI_URL`: Direct Loki URL (testing, e.g., http://loki:3100)

## Common Investigation Patterns

### Find errors in a service
```bash
python scripts/sample_logs.py --selector '{app="api"}' --filter "error|exception|fail"
```

### Compare error rates across pods
```bash
python scripts/query_logs.py 'sum(rate({app="api"} |= "error" [5m])) by (pod)' --type metric
```

### Find slow requests (if using JSON logs with duration)
```bash
python scripts/query_logs.py '{app="api"} | json | duration > 1000' --limit 20
```

### Correlate logs around a timestamp
```bash
python scripts/query_logs.py '{app="api"}' --start "2024-01-15T10:30:00Z" --end "2024-01-15T10:35:00Z"
```
