---
name: alerting-context
description: Pull incident context from alerting platforms (PagerDuty). Use when investigating who's on-call, incident history, alert patterns, or MTTR metrics.
category: incident
required_integrations:
  - pagerduty
allowed-tools: Bash(python *)
---

# Alerting Context

## Authentication

**IMPORTANT**: Credentials are injected automatically by a proxy layer. Do NOT check for `PAGERDUTY_API_KEY` in environment variables - it won't be visible to you. Just run the scripts directly; authentication is handled transparently.

---

## Why Alerting Context Matters

Before diving into logs and metrics, understand:
- **Has this happened before?** Check similar past incidents
- **Who's responding?** Know who's on-call and assigned
- **What else is alerting?** Correlated alerts reveal scope
- **How long do similar issues take?** MTTR sets expectations

## Available Scripts

All scripts are in `.claude/skills/alerting-context/scripts/`

### get_incident.py - Get Incident Details
```bash
python .claude/skills/alerting-context/scripts/get_incident.py --id INCIDENT_ID [--timeline]

# Examples:
python .claude/skills/alerting-context/scripts/get_incident.py --id P123ABC
python .claude/skills/alerting-context/scripts/get_incident.py --id P123ABC --timeline
```

### list_incidents.py - List Incidents with Filters
```bash
python .claude/skills/alerting-context/scripts/list_incidents.py [--status STATUS] [--days N] [--limit N]

# Examples:
python .claude/skills/alerting-context/scripts/list_incidents.py
python .claude/skills/alerting-context/scripts/list_incidents.py --status triggered
python .claude/skills/alerting-context/scripts/list_incidents.py --status acknowledged --limit 10
python .claude/skills/alerting-context/scripts/list_incidents.py --days 30
```

### calculate_mttr.py - Calculate Mean Time To Resolve
```bash
python .claude/skills/alerting-context/scripts/calculate_mttr.py [--service SERVICE_ID] [--days N]

# Examples:
python .claude/skills/alerting-context/scripts/calculate_mttr.py
python .claude/skills/alerting-context/scripts/calculate_mttr.py --days 30
python .claude/skills/alerting-context/scripts/calculate_mttr.py --service PSERVICE123 --days 90
```

---

## Investigation Workflow

### Step 1: Get Current Incident Context

```bash
# Get details of the current incident
python get_incident.py --id P123ABC --timeline
```

**Returns:**
- Incident title, status, urgency
- Service affected
- Who acknowledged, when
- Timeline of actions taken

### Step 2: Find Similar Past Incidents

```bash
# Get incidents from the last 30 days
python list_incidents.py --days 30 --status resolved

# Check for patterns in a specific service
python list_incidents.py --service PSERVICE123 --days 90
```

**Look for:**
- Same alert title recurring → Known issue or flapping
- Cluster of alerts → Systemic problem
- Low ack rate → Possible alert fatigue

### Step 3: Check Historical MTTR

```bash
# Get MTTR for this service
python calculate_mttr.py --service PSERVICE123 --days 30
```

**Returns:**
- Average MTTR (minutes/hours)
- Median MTTR
- 95th percentile
- Fastest/slowest resolution

---

## Quick Commands Reference

| Goal | Command |
|------|---------|
| Get incident | `get_incident.py --id P123ABC` |
| With timeline | `get_incident.py --id P123ABC --timeline` |
| Active incidents | `list_incidents.py --status triggered` |
| Acknowledged | `list_incidents.py --status acknowledged` |
| Last 30 days | `list_incidents.py --days 30` |
| Calculate MTTR | `calculate_mttr.py --service X --days 30` |

---

## Common Patterns

### Pattern 1: "Is this a known issue?"

```bash
# Search for similar alerts in last 30 days
python list_incidents.py --days 30

# Check the output for recurring alert titles
# Look for same service, similar patterns
```

### Pattern 2: "Escalation Investigation"

```bash
# Get full incident details with timeline
python get_incident.py --id P123ABC --timeline

# Check 'assignments' and 'acknowledgements' in output
# Timeline shows escalation events
```

### Pattern 3: "SLA/MTTR Tracking"

```bash
# Get MTTR for incident comparison
python calculate_mttr.py --service PSERVICE123 --days 30

# Compare current incident duration to historical average
# If current > p95, this is an unusually long incident
```

---

## Output Format

```markdown
## Alerting Context Summary

### Current Incident
- **ID**: [incident_id]
- **Title**: [title]
- **Status**: [triggered/acknowledged/resolved]
- **Service**: [service_name]
- **Urgency**: [high/low]
- **Created**: [timestamp]
- **Duration**: [how long since created]

### On-Call
- **Primary**: [name] ([email])
- **Secondary**: [name] ([email])
- **Escalation Policy**: [policy_name]

### Historical Context
- **Similar incidents (30d)**: N incidents with same/similar title
- **Average MTTR for this service**: X minutes
- **This alert fires**: Z times/week on average

### Recommendations
- [If recurring] Review runbook for this alert
- [If long duration] Consider escalating
- [If noisy] Consider tuning alert threshold
```

---

## Anti-Patterns to Avoid

1. ❌ **Ignoring past incidents** - Always check if it's a known issue
2. ❌ **Not checking on-call** - Know who's responding before investigating
3. ❌ **Missing correlated alerts** - One incident might mask the real issue
4. ❌ **Forgetting MTTR context** - Know what "normal" resolution looks like
5. ❌ **Unbounded queries** - Always use time ranges to avoid timeout
