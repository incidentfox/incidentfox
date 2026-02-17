---
name: blameless-integration
description: Blameless incident management and retrospectives. Use for listing incidents, analyzing MTTR, reviewing post-incident retrospectives with contributing factors, action items, and lessons learned.
allowed-tools: Bash(python *)
---

# Blameless Integration

## Authentication

**IMPORTANT**: Credentials are injected automatically by a proxy layer. Do NOT check for `BLAMELESS_API_KEY` in environment variables. Just run the scripts directly.

Configuration environment variables you CAN check (non-secret):
- `BLAMELESS_BASE_URL` - Proxy base URL (set automatically in production)
- `BLAMELESS_INSTANCE_URL` - Custom instance URL (default: https://api.blameless.io)

---

## Available Scripts

All scripts are in `.claude/skills/incident-blameless/scripts/`

### list_incidents.py - List Incidents
```bash
python .claude/skills/incident-blameless/scripts/list_incidents.py [--status resolved] [--severity SEV1] [--max-results N]
```

### get_incident.py - Get Incident Details
```bash
python .claude/skills/incident-blameless/scripts/get_incident.py --incident-id ID
```

### get_incident_timeline.py - Timeline Events
```bash
python .claude/skills/incident-blameless/scripts/get_incident_timeline.py --incident-id ID [--max-results 50]
```

### list_incidents_by_date_range.py - Historical with MTTR
```bash
python .claude/skills/incident-blameless/scripts/list_incidents_by_date_range.py --since "2024-01-01T00:00:00Z" --until "2024-01-31T23:59:59Z"
```

### list_severities.py - Severity Levels
```bash
python .claude/skills/incident-blameless/scripts/list_severities.py
```

### get_retrospective.py - Post-Incident Retrospective
```bash
python .claude/skills/incident-blameless/scripts/get_retrospective.py --incident-id ID
```
Returns contributing factors, action items, root cause, lessons learned.

### get_alert_analytics.py - Incident Pattern Analysis
```bash
python .claude/skills/incident-blameless/scripts/get_alert_analytics.py --since "2024-01-01T00:00:00Z" --until "2024-01-31T23:59:59Z"
```

### calculate_mttr.py - MTTR Statistics
```bash
python .claude/skills/incident-blameless/scripts/calculate_mttr.py [--severity SEV1] [--days 30]
```
