---
name: firehydrant-integration
description: FireHydrant incident management with service catalog. Use for listing incidents, tracking milestones, analyzing MTTR, and service impact analysis across environments.
allowed-tools: Bash(python *)
---

# FireHydrant Integration

## Authentication

**IMPORTANT**: Credentials are injected automatically by a proxy layer. Do NOT check for `FIREHYDRANT_API_KEY`. Just run the scripts directly.

## Available Scripts

All scripts are in `.claude/skills/incident-firehydrant/scripts/`

### list_incidents.py
```bash
python .claude/skills/incident-firehydrant/scripts/list_incidents.py [--status open] [--severity SEV] [--environment-id ID] [--max-results N]
```

### get_incident.py
```bash
python .claude/skills/incident-firehydrant/scripts/get_incident.py --incident-id ID
```

### get_incident_timeline.py
```bash
python .claude/skills/incident-firehydrant/scripts/get_incident_timeline.py --incident-id ID
```

### list_incidents_by_date_range.py
```bash
python .claude/skills/incident-firehydrant/scripts/list_incidents_by_date_range.py --since "2024-01-01T00:00:00Z" --until "2024-01-31T23:59:59Z"
```

### list_services.py / list_environments.py
```bash
python .claude/skills/incident-firehydrant/scripts/list_services.py
python .claude/skills/incident-firehydrant/scripts/list_environments.py
```

### get_alert_analytics.py
```bash
python .claude/skills/incident-firehydrant/scripts/get_alert_analytics.py --since "2024-01-01T00:00:00Z" --until "2024-01-31T23:59:59Z" [--service-id ID]
```

### calculate_mttr.py
```bash
python .claude/skills/incident-firehydrant/scripts/calculate_mttr.py [--severity SEV] [--service-id ID] [--days 30]
```
