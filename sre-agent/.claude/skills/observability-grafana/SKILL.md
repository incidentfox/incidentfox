---
name: grafana-dashboards
description: Grafana dashboard and metrics analysis. Use when querying dashboards, panels, Prometheus metrics via Grafana, checking datasources, reviewing alerts, or creating dashboards from templates.
allowed-tools: Bash(python *)
---

# Grafana Dashboard Analysis

## Authentication

**IMPORTANT**: Credentials are injected automatically by a proxy layer. Do NOT check for `GRAFANA_API_KEY` in environment variables - it won't be visible to you. Just run the scripts directly; authentication is handled transparently.

Configuration environment variables you CAN check (non-secret):
- `GRAFANA_URL` - Grafana instance URL (e.g., `https://grafana.company.com`)

---

## Available Scripts

All scripts are in `.claude/skills/observability-grafana/scripts/`

### list_dashboards.py - Search/List Dashboards
```bash
python .claude/skills/observability-grafana/scripts/list_dashboards.py [--query "kubernetes"]
```

### get_dashboard.py - Get Dashboard Details
```bash
python .claude/skills/observability-grafana/scripts/get_dashboard.py --uid DASHBOARD_UID
```

### query_prometheus.py - Query Prometheus via Grafana
```bash
python .claude/skills/observability-grafana/scripts/query_prometheus.py --query "PROMQL" [--time-range 60] [--step 1m]

# Examples:
python .claude/skills/observability-grafana/scripts/query_prometheus.py --query "rate(http_requests_total[5m])"
python .claude/skills/observability-grafana/scripts/query_prometheus.py --query "up{job='api'}" --time-range 120
```

### list_datasources.py - List Configured Datasources
```bash
python .claude/skills/observability-grafana/scripts/list_datasources.py
```

### get_alerts.py - Get Active Alerts
```bash
python .claude/skills/observability-grafana/scripts/get_alerts.py
```

### create_dashboard.py - Create Dashboard from Template
```bash
python .claude/skills/observability-grafana/scripts/create_dashboard.py \
  --title "My Dashboard" \
  --template .claude/skills/observability-grafana/templates/vercel-overview.json

# With folder:
python .claude/skills/observability-grafana/scripts/create_dashboard.py \
  --title "My Dashboard" \
  --template .claude/skills/observability-grafana/templates/vercel-overview.json \
  --folder-uid FOLDER_UID

# Overwrite existing:
python .claude/skills/observability-grafana/scripts/create_dashboard.py \
  --title "My Dashboard" \
  --template .claude/skills/observability-grafana/templates/vercel-overview.json \
  --overwrite
```

---

## Dashboard Templates

Pre-built templates are in `.claude/skills/observability-grafana/templates/`:

| Template | Description |
|----------|-------------|
| `vercel-overview.json` | 4-panel Vercel monitoring: error count, error rate, log stream, request summary |

---

## PromQL Quick Reference

```promql
# Request rate
rate(http_requests_total{service="api"}[5m])

# Error rate %
sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m])) * 100

# P95 latency
histogram_quantile(0.95, rate(http_duration_seconds_bucket{service="api"}[5m]))

# CPU usage
rate(process_cpu_seconds_total{service="api"}[5m])
```

---

## Investigation Workflow

```
1. list_dashboards.py --query "api"
2. get_dashboard.py --uid <uid>
3. query_prometheus.py --query "rate(http_requests_total{service='api',status=~'5..'}[5m])"
4. get_alerts.py
```
