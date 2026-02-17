---
name: incidentio-integration
description: Incident.io incident management and analytics. Use for listing, searching, and analyzing incidents. Supports MTTR calculations, severity analysis, and alert fatigue detection via alert route analytics.
allowed-tools: Bash(python *)
---

# Incident.io Integration

## Authentication

**IMPORTANT**: Credentials are injected automatically by a proxy layer. Do NOT check for `INCIDENTIO_API_KEY` in environment variables - they won't be visible to you. Just run the scripts directly; authentication is handled transparently.

Configuration environment variables you CAN check (non-secret):
- `INCIDENTIO_BASE_URL` - Proxy base URL (set automatically in production)

---

## Available Scripts

All scripts are in `.claude/skills/incident-incidentio/scripts/`

### list_incidents.py - List Incidents
```bash
python .claude/skills/incident-incidentio/scripts/list_incidents.py [--status STATUS] [--severity-id ID] [--max-results N]

# Examples:
python .claude/skills/incident-incidentio/scripts/list_incidents.py --status active
python .claude/skills/incident-incidentio/scripts/list_incidents.py --status resolved --max-results 20
```

### get_incident.py - Get Incident Details
```bash
python .claude/skills/incident-incidentio/scripts/get_incident.py --incident-id INCIDENT_ID
```

### get_incident_updates.py - Get Timeline Updates
```bash
python .claude/skills/incident-incidentio/scripts/get_incident_updates.py --incident-id INCIDENT_ID [--max-results 50]
```

### list_incidents_by_date_range.py - Historical Incidents with MTTR
```bash
python .claude/skills/incident-incidentio/scripts/list_incidents_by_date_range.py --since "2024-01-01T00:00:00Z" --until "2024-01-31T23:59:59Z" [--status STATUS] [--max-results N]
```

### list_severities.py - List Severity Levels
```bash
python .claude/skills/incident-incidentio/scripts/list_severities.py
```

### list_incident_types.py - List Incident Types
```bash
python .claude/skills/incident-incidentio/scripts/list_incident_types.py
```

### get_alert_analytics.py - Alert Fatigue Analysis
```bash
python .claude/skills/incident-incidentio/scripts/get_alert_analytics.py --since "2024-01-01T00:00:00Z" --until "2024-01-31T23:59:59Z"
```

### calculate_mttr.py - MTTR Statistics
```bash
python .claude/skills/incident-incidentio/scripts/calculate_mttr.py [--severity-id ID] [--days 30]
```

---

## Investigation Workflow

### Incident Analysis
```
1. List recent incidents:
   list_incidents.py --status active

2. Get incident details:
   get_incident.py --incident-id <id>

3. Review timeline:
   get_incident_updates.py --incident-id <id>

4. Compute MTTR for severity assessment:
   calculate_mttr.py --days 30
```

### Alert Fatigue Analysis
```
1. Get alert analytics for the period:
   get_alert_analytics.py --since "2024-01-01T00:00:00Z" --until "2024-01-31T23:59:59Z"

2. Review noisy routes (high fire count, low ack rate)

3. Check historical MTTR by severity:
   calculate_mttr.py --severity-id <sev_id>
```
