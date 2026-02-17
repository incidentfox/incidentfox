---
name: opsgenie-integration
description: Opsgenie alert management and on-call scheduling. Use for listing alerts, checking on-call, computing MTTA/MTTR, and alert fatigue analysis. Supports team and priority filtering.
allowed-tools: Bash(python *)
---

# Opsgenie Integration

## Authentication

**IMPORTANT**: Credentials are injected automatically by a proxy layer. Do NOT check for `OPSGENIE_API_KEY` in environment variables - they won't be visible to you. Just run the scripts directly; authentication is handled transparently.

Configuration environment variables you CAN check (non-secret):
- `OPSGENIE_BASE_URL` - Proxy base URL (set automatically in production)
- `OPSGENIE_API_URL` - Custom API URL (default: https://api.opsgenie.com)

---

## Available Scripts

All scripts are in `.claude/skills/alerting-opsgenie/scripts/`

### list_alerts.py - List Alerts
```bash
python .claude/skills/alerting-opsgenie/scripts/list_alerts.py [--status open] [--priority P1] [--query QUERY] [--max-results N]
```

### get_alert.py - Get Alert Details
```bash
python .claude/skills/alerting-opsgenie/scripts/get_alert.py --alert-id ALERT_ID
```

### get_alert_logs.py - Alert Timeline
```bash
python .claude/skills/alerting-opsgenie/scripts/get_alert_logs.py --alert-id ALERT_ID [--max-results 50]
```

### list_alerts_by_date_range.py - Historical Alerts with MTTA/MTTR
```bash
python .claude/skills/alerting-opsgenie/scripts/list_alerts_by_date_range.py --since "2024-01-01T00:00:00Z" --until "2024-01-31T23:59:59Z" [--query QUERY]
```

### list_services.py - List Services
```bash
python .claude/skills/alerting-opsgenie/scripts/list_services.py
```

### list_teams.py - List Teams
```bash
python .claude/skills/alerting-opsgenie/scripts/list_teams.py
```

### get_on_call.py - On-Call Schedule
```bash
python .claude/skills/alerting-opsgenie/scripts/get_on_call.py [--schedule-id ID] [--team-id ID]
```

### get_alert_analytics.py - Alert Fatigue Analysis
```bash
python .claude/skills/alerting-opsgenie/scripts/get_alert_analytics.py --since "2024-01-01T00:00:00Z" --until "2024-01-31T23:59:59Z" [--team-id ID]
```

### calculate_mttr.py - MTTR Statistics
```bash
python .claude/skills/alerting-opsgenie/scripts/calculate_mttr.py [--team-id ID] [--priority P1] [--days 30]
```

---

## Investigation Workflow

### On-Call & Alert Triage
```
1. Check who's on call:
   get_on_call.py

2. List open alerts:
   list_alerts.py --status open

3. Get alert details:
   get_alert.py --alert-id <id>

4. Review alert timeline:
   get_alert_logs.py --alert-id <id>
```

### Alert Fatigue Analysis
```
1. Get alert analytics:
   get_alert_analytics.py --since "2024-01-01T00:00:00Z" --until "2024-01-31T23:59:59Z"

2. Review noisy alerts (high fire count, low ack rate)
3. Review flapping alerts (quick auto-resolve)

4. MTTR by priority:
   calculate_mttr.py --priority P1 --days 30
```
