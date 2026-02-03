---
name: metrics-analysis
description: Prometheus/Grafana metrics analysis and PromQL queries. Use when investigating latency, error rates, resource usage, or any time-series metrics.
---

# Metrics Analysis

## Core Principle: USE & RED Methods

**USE Method** (for infrastructure):
- **U**tilization - How busy is the resource?
- **S**aturation - How much work is queued?
- **E**rrors - Are there error events?

**RED Method** (for services):
- **R**ate - Requests per second
- **E**rrors - Error rate
- **D**uration - Latency distribution

## Available Tools

| Tool | Purpose |
|------|---------|
| `grafana_query_prometheus` | Execute PromQL queries |
| `grafana_list_dashboards` | Find relevant dashboards |
| `grafana_get_dashboard` | Get dashboard panels and queries |
| `grafana_list_datasources` | Discover metric sources |
| `grafana_get_annotations` | Find deployment/incident markers |
| `grafana_get_alerts` | Check firing alerts |

---

## PromQL Quick Reference

### Basic Queries

```promql
# Instant vector - current value
http_requests_total{service="api"}

# Range vector - values over time (for rate calculations)
http_requests_total{service="api"}[5m]

# Rate of increase per second
rate(http_requests_total{service="api"}[5m])
```

### Common Operators

```promql
# Rate (counter → gauge, per second)
rate(http_requests_total[5m])

# Increase (total increase over time range)
increase(http_requests_total[1h])

# Average over time
avg_over_time(cpu_usage[5m])

# Histogram quantile (p95, p99)
histogram_quantile(0.95, rate(http_request_duration_bucket[5m]))
```

### Aggregations

```promql
# Sum across all instances
sum(rate(http_requests_total[5m]))

# Group by label
sum by (service) (rate(http_requests_total[5m]))

# Average by label
avg by (instance) (cpu_usage)

# Top 5 by value
topk(5, sum by (service) (rate(http_requests_total[5m])))
```

### Label Matching

```promql
# Exact match
http_requests_total{status="500"}

# Regex match
http_requests_total{status=~"5.."}

# Not equal
http_requests_total{status!="200"}

# Multiple labels
http_requests_total{service="api", status=~"5.."}
```

---

## Investigation Workflows

### 1. Latency Investigation

```python
# Step 1: Check overall latency trend
grafana_query_prometheus(
    query='histogram_quantile(0.95, rate(http_request_duration_seconds_bucket{service="api"}[5m]))',
    time_range="1h"
)

# Step 2: Compare p50 vs p99 (is it a few slow requests or systemic?)
grafana_query_prometheus(
    query='histogram_quantile(0.50, rate(http_request_duration_seconds_bucket{service="api"}[5m]))',
    time_range="1h"
)

# Step 3: Break down by endpoint
grafana_query_prometheus(
    query='histogram_quantile(0.95, sum by (endpoint) (rate(http_request_duration_seconds_bucket{service="api"}[5m])))',
    time_range="1h"
)
```

### 2. Error Rate Investigation

```python
# Step 1: Overall error rate
grafana_query_prometheus(
    query='sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m]))',
    time_range="1h"
)

# Step 2: Errors by status code
grafana_query_prometheus(
    query='sum by (status) (rate(http_requests_total{status=~"[45].."}[5m]))',
    time_range="1h"
)

# Step 3: Errors by service
grafana_query_prometheus(
    query='sum by (service) (rate(http_requests_total{status=~"5.."}[5m]))',
    time_range="1h"
)
```

### 3. Resource Investigation (CPU/Memory)

```python
# CPU usage
grafana_query_prometheus(
    query='avg by (instance) (rate(container_cpu_usage_seconds_total{pod=~"api-.*"}[5m]))',
    time_range="1h"
)

# Memory usage
grafana_query_prometheus(
    query='container_memory_usage_bytes{pod=~"api-.*"} / container_spec_memory_limit_bytes{pod=~"api-.*"}',
    time_range="1h"
)

# Memory trend (is it growing?)
grafana_query_prometheus(
    query='deriv(container_memory_usage_bytes{pod=~"api-.*"}[30m])',
    time_range="2h"
)
```

### 4. Saturation/Queue Investigation

```python
# Connection pool saturation
grafana_query_prometheus(
    query='db_connections_active / db_connections_max',
    time_range="1h"
)

# Pending requests (queued work)
grafana_query_prometheus(
    query='sum(http_requests_pending{service="api"})',
    time_range="1h"
)

# Thread pool usage
grafana_query_prometheus(
    query='executor_active_threads / executor_pool_size',
    time_range="1h"
)
```

---

## Finding Existing Dashboards

```python
# Search for dashboards by name
grafana_list_dashboards(query="api")
grafana_list_dashboards(query="kubernetes")

# Get dashboard details (see what queries are used)
grafana_get_dashboard(dashboard_uid="abc123")
```

**Pro tip**: Look at existing dashboards to find the correct metric names and labels.

---

## Correlating with Events

```python
# Check for deployment annotations around the issue time
grafana_get_annotations(time_range="24h", tags="deployment")

# Check what alerts fired
grafana_get_alerts(state="alerting")
```

---

## Common Metric Patterns

### Request Metrics (Prometheus naming conventions)

```promql
# Total requests (counter)
http_requests_total

# Request duration histogram
http_request_duration_seconds_bucket
http_request_duration_seconds_count
http_request_duration_seconds_sum

# Active requests (gauge)
http_requests_in_flight
```

### Kubernetes Metrics

```promql
# CPU usage
container_cpu_usage_seconds_total
node_cpu_seconds_total

# Memory
container_memory_usage_bytes
container_memory_working_set_bytes
node_memory_MemTotal_bytes

# Pod restarts
kube_pod_container_status_restarts_total

# Pod status
kube_pod_status_phase
```

### Database Metrics

```promql
# Connection pool
db_connections_active
db_connections_idle
db_connections_max

# Query latency
db_query_duration_seconds_bucket

# Errors
db_errors_total
```

---

## Output Format

```markdown
## Metrics Analysis Summary

### Time Window
- **Start**: [timestamp]
- **End**: [timestamp]
- **Duration**: X hours

### Key Metrics

#### Request Rate
- **Current**: X req/s
- **Peak**: Y req/s at [timestamp]
- **Trend**: [increasing/stable/decreasing]

#### Error Rate
- **Current**: X%
- **Peak**: Y% at [timestamp]
- **Primary error type**: [status code or error]

#### Latency (p95)
- **Current**: X ms
- **Peak**: Y ms at [timestamp]
- **p50 vs p99 gap**: [normal/wide - indicates tail latency]

#### Resource Utilization
- **CPU**: X% (peak Y%)
- **Memory**: X% (peak Y%)
- **Trend**: [stable/growing/spiky]

### Anomalies Detected
1. [Metric spike/drop] at [timestamp]
2. [Unusual pattern] observed

### Correlation
- Deployment at [timestamp] - [coincides/doesn't coincide] with anomaly
- Alert [name] fired at [timestamp]

### Hypothesis
Based on metrics: [what the data suggests is happening]
```

---

## Anti-Patterns

1. **Using `rate()` without range vector** - Always include `[5m]` or similar
2. **Comparing counters directly** - Use `rate()` or `increase()` first
3. **Wrong quantile math** - `histogram_quantile` requires `_bucket` metrics
4. **Missing label filters** - Queries without filters return all series
5. **Too-short time ranges** - Use at least 2x your scrape interval for `rate()`

---

## Pro Tips

**Choosing time ranges:**
- `rate(...[5m])` for real-time monitoring
- `rate(...[15m])` for smoother trends
- Longer ranges smooth out noise but hide spikes

**Debugging empty results:**
- Check metric names: `grafana_list_datasources()` then explore
- Verify labels exist in your environment
- Try broader filters first, then narrow down

**Performance:**
- Avoid `{job=~".*"}` (matches everything)
- Use `topk()` instead of returning all series
- Shorter time ranges = faster queries
