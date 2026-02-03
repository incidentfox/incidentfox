---
name: datadog-analysis
description: Datadog log and metric analysis using DQL (Datadog Query Language). Use when investigating issues via Datadog logs, APM traces, or metrics.
---

# Datadog Analysis

## Core Principle: Statistics Before Samples

**NEVER start by reading raw logs.** Always begin with aggregated statistics:

1. **Volume**: How many logs in the time window?
2. **Distribution**: Which services/levels/error types?
3. **Trends**: Is it increasing, stable, or decreasing?
4. **THEN sample**: Get specific entries after understanding the landscape

---

## Available Tools

| Tool | Purpose |
|------|---------|
| `search_datadog_logs` | Search logs with DQL |
| `query_datadog_metrics` | Query metrics |
| `get_service_apm_metrics` | APM latency/errors/throughput |
| `datadog_get_monitors` | List alert monitors |
| `datadog_get_monitor_history` | Monitor state history |

---

## Datadog Query Language (DQL)

### Basic Log Search

```
# Simple text search
error

# Service filter
service:api-gateway

# Status filter
status:error

# Combined filters
service:api-gateway status:error
```

### Field Filters

```
# Exact match
@http.status_code:500

# Numeric comparison
@http.status_code:>=400

# Wildcard
@http.url:*/api/users/*

# Exists
@error.message:*

# NOT operator
-status:info
```

### Facet Search

```
# Standard facets
host:web-01
env:production
service:payment-service

# Custom facets (@ prefix)
@customer_id:12345
@request_id:abc-123
```

### Time-Based

```
# Natural language (in search bar)
service:api last 15 minutes

# Specific range
service:api @timestamp:[2024-01-15T10:00:00 TO 2024-01-15T11:00:00]
```

---

## Investigation Workflow

### Step 1: Get Statistics

```python
# Search for errors with count
search_datadog_logs(
    query="service:api-gateway status:error",
    time_range="1h",
    limit=0  # Just count
)

# Break down by error type
search_datadog_logs(
    query="service:api-gateway status:error",
    time_range="1h",
    limit=10
)
```

### Step 2: Identify Top Errors

```python
# Get errors grouped by message (manual analysis of results)
search_datadog_logs(
    query="service:api-gateway status:error @error.message:*",
    time_range="1h",
    limit=50
)
```

### Step 3: Check APM Metrics

```python
# Get latency, errors, throughput for a service
get_service_apm_metrics(
    service_name="api-gateway",
    time_range="1h"
)
```

### Step 4: Query Custom Metrics

```python
# CPU usage
query_datadog_metrics(
    query="avg:system.cpu.user{service:api-gateway}",
    time_range="1h"
)

# Error rate
query_datadog_metrics(
    query="sum:trace.servlet.request.errors{service:api-gateway}.as_rate()",
    time_range="1h"
)
```

---

## Metrics Query Syntax

### Basic Structure

```
aggregation:metric_name{tag_filters}
```

### Aggregations

```
avg:   - Average across series
sum:   - Sum across series
min:   - Minimum value
max:   - Maximum value
count: - Count of series
```

### Tag Filters

```
# Single tag
{service:api-gateway}

# Multiple tags (AND)
{service:api-gateway,env:production}

# Wildcard
{host:web-*}

# Negation
{!env:staging}
```

### Functions

```
# Rate of change
.as_rate()

# Per second derivative
.per_second()

# Moving average
.rollup(avg, 60)

# Fill missing data
.fill(zero)
```

### Common Metrics

```
# System
avg:system.cpu.user{service:X}
avg:system.mem.used{service:X}
avg:system.disk.used{service:X}

# Network
sum:system.net.bytes_rcvd{service:X}
sum:system.net.bytes_sent{service:X}

# APM (traces)
avg:trace.servlet.request{service:X}
sum:trace.servlet.request.errors{service:X}
sum:trace.servlet.request.hits{service:X}

# Custom metrics
avg:myapp.queue.depth{env:production}
```

---

## Monitor (Alert) Analysis

### Check Firing Monitors

```python
# Get all monitors in alert state
datadog_get_monitors(max_results=50)

# Filter by tags
datadog_get_monitors(
    monitor_tags=["env:production", "team:backend"],
    max_results=50
)

# Search by name
datadog_get_monitors(name="API Gateway")
```

### Understand Monitor History

```python
# Get history for a specific monitor
datadog_get_monitor_history(
    monitor_id=12345,
    time_range="7d"
)
```

---

## Common Patterns

### Pattern 1: Error Spike Investigation

```python
# 1. Confirm error rate increase
query_datadog_metrics(
    query="sum:trace.servlet.request.errors{service:api-gateway}.as_rate()",
    time_range="2h"
)

# 2. Get sample errors
search_datadog_logs(
    query="service:api-gateway status:error",
    time_range="1h",
    limit=20
)

# 3. Group by error message (manual analysis)
# Look for common patterns in the returned logs
```

### Pattern 2: Latency Investigation

```python
# 1. Check APM metrics
get_service_apm_metrics(service_name="api-gateway", time_range="1h")

# 2. Look for slow traces
search_datadog_logs(
    query="service:api-gateway @duration:>1000000000",  # > 1 second in nanoseconds
    time_range="1h",
    limit=20
)
```

### Pattern 3: Resource Exhaustion

```python
# 1. Check CPU
query_datadog_metrics(
    query="avg:system.cpu.user{service:api-gateway} by {host}",
    time_range="2h"
)

# 2. Check memory
query_datadog_metrics(
    query="avg:system.mem.used{service:api-gateway} by {host}",
    time_range="2h"
)

# 3. Check for OOM or resource errors in logs
search_datadog_logs(
    query="service:api-gateway (OutOfMemory OR OOM OR killed)",
    time_range="24h",
    limit=20
)
```

---

## Output Format

```markdown
## Datadog Analysis Summary

### Time Window
- **Start**: [timestamp]
- **End**: [timestamp]
- **Duration**: X hours

### Log Statistics
- **Total logs**: X events
- **Error count**: Y events (Z%)
- **Services affected**: N services
- **Error rate trend**: [increasing/stable/decreasing]

### Top Error Types
1. [error_type]: N occurrences
2. [error_type]: M occurrences

### APM Metrics
- **Request rate**: X req/s
- **Error rate**: Y%
- **p95 latency**: Z ms

### Monitors
- **Firing alerts**: N monitors
- **Most critical**: [monitor_name]

### Sample Errors
[Quote 2-3 representative error messages]

### Root Cause Hypothesis
[Based on patterns observed]
```

---

## Anti-Patterns

1. **Unbounded log searches** - Always specify `time_range` and `limit`
2. **Ignoring APM data** - APM traces often have more context than logs
3. **Missing tag filters** - `service:X` and `env:production` are essential
4. **Treating monitors as logs** - Monitors show alert state, not raw events
5. **Ignoring rate calculations** - Use `.as_rate()` for counters

---

## Pro Tips

**Efficient searching:**
- Start with short time ranges (15m), expand if needed
- Use `status:error` to focus on problems
- Combine service + environment filters

**APM insights:**
- APM traces include span-level detail
- Resource names (endpoints) help isolate issues
- Trace IDs connect distributed requests

**Monitor analysis:**
- Monitor `overall_state` shows current health
- Tags like `team:X` help filter relevant monitors
- Check `query` field to understand what's being monitored
