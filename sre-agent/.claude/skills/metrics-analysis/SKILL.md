---
name: metrics-analysis
description: Prometheus/Grafana metrics analysis and PromQL queries. Use when investigating latency, error rates, resource usage, or any time-series metrics.
allowed-tools: Bash(python *)
---

# Metrics Analysis

## Authentication

**IMPORTANT**: Credentials are injected automatically by a proxy layer. Do NOT check for `GRAFANA_API_KEY` or `PROMETHEUS_URL` in environment variables - they won't be visible to you. Just run the scripts directly; authentication is handled transparently.

---

## Core Principle: USE & RED Methods

**USE Method** (for infrastructure):
- **U**tilization - How busy is the resource?
- **S**aturation - How much work is queued?
- **E**rrors - Are there error events?

**RED Method** (for services):
- **R**ate - Requests per second
- **E**rrors - Error rate
- **D**uration - Latency distribution

## Available Scripts

All scripts are in `.claude/skills/metrics-analysis/scripts/`

### query_prometheus.py - Execute PromQL Queries
```bash
python .claude/skills/metrics-analysis/scripts/query_prometheus.py --query PROMQL [--time-range MINUTES] [--step STEP]

# Examples:
python .claude/skills/metrics-analysis/scripts/query_prometheus.py --query "up"
python .claude/skills/metrics-analysis/scripts/query_prometheus.py --query "rate(http_requests_total[5m])" --time-range 60
python .claude/skills/metrics-analysis/scripts/query_prometheus.py --query "histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))"
```

### list_dashboards.py - Find Grafana Dashboards
```bash
python .claude/skills/metrics-analysis/scripts/list_dashboards.py [--query SEARCH_TERM]

# Examples:
python .claude/skills/metrics-analysis/scripts/list_dashboards.py
python .claude/skills/metrics-analysis/scripts/list_dashboards.py --query "api"
```

### get_alerts.py - Check Firing Alerts
```bash
python .claude/skills/metrics-analysis/scripts/get_alerts.py [--state STATE]

# Examples:
python .claude/skills/metrics-analysis/scripts/get_alerts.py
python .claude/skills/metrics-analysis/scripts/get_alerts.py --state alerting
```

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

```bash
# Step 1: Check overall latency trend
python query_prometheus.py --query 'histogram_quantile(0.95, rate(http_request_duration_seconds_bucket{service="api"}[5m]))' --time-range 60

# Step 2: Compare p50 vs p99
python query_prometheus.py --query 'histogram_quantile(0.50, rate(http_request_duration_seconds_bucket{service="api"}[5m]))'

# Step 3: Break down by endpoint
python query_prometheus.py --query 'histogram_quantile(0.95, sum by (endpoint) (rate(http_request_duration_seconds_bucket{service="api"}[5m])))'
```

### 2. Error Rate Investigation

```bash
# Step 1: Overall error rate
python query_prometheus.py --query 'sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m]))'

# Step 2: Errors by status code
python query_prometheus.py --query 'sum by (status) (rate(http_requests_total{status=~"[45].."}[5m]))'

# Step 3: Errors by service
python query_prometheus.py --query 'sum by (service) (rate(http_requests_total{status=~"5.."}[5m]))'
```

### 3. Resource Investigation (CPU/Memory)

```bash
# CPU usage
python query_prometheus.py --query 'avg by (instance) (rate(container_cpu_usage_seconds_total{pod=~"api-.*"}[5m]))'

# Memory usage percentage
python query_prometheus.py --query 'container_memory_usage_bytes{pod=~"api-.*"} / container_spec_memory_limit_bytes{pod=~"api-.*"}'
```

---

## Quick Commands Reference

| Goal | Command |
|------|---------|
| Request rate | `query_prometheus.py --query "sum(rate(http_requests_total[5m]))"` |
| Error rate | `query_prometheus.py --query "sum(rate(http_requests_total{status=~'5..'}[5m]))"` |
| P95 latency | `query_prometheus.py --query "histogram_quantile(0.95, ...)"` |
| CPU usage | `query_prometheus.py --query "rate(container_cpu_usage_seconds_total[5m])"` |
| Find dashboards | `list_dashboards.py --query "api"` |
| Check alerts | `get_alerts.py --state alerting` |

---

## Common Metric Patterns

### Request Metrics
```promql
http_requests_total                    # Counter
http_request_duration_seconds_bucket   # Histogram
http_requests_in_flight               # Gauge
```

### Kubernetes Metrics
```promql
container_cpu_usage_seconds_total
container_memory_usage_bytes
kube_pod_container_status_restarts_total
kube_pod_status_phase
```

---

## Anti-Patterns to Avoid

1. ❌ **Using `rate()` without range vector** - Always include `[5m]` or similar
2. ❌ **Comparing counters directly** - Use `rate()` or `increase()` first
3. ❌ **Wrong quantile math** - `histogram_quantile` requires `_bucket` metrics
4. ❌ **Missing label filters** - Queries without filters return all series
5. ❌ **Too-short time ranges** - Use at least 2x your scrape interval for `rate()`
