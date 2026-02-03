---
name: alerting-context
description: Pull incident context from alerting platforms (PagerDuty, Opsgenie, Incident.io). Use when investigating who's on-call, incident history, alert patterns, or MTTR metrics.
---

# Alerting Context

## Why Alerting Context Matters

Before diving into logs and metrics, understand:
- **Has this happened before?** Check similar past incidents
- **Who's responding?** Know who's on-call and assigned
- **What else is alerting?** Correlated alerts reveal scope
- **How long do similar issues take?** MTTR sets expectations

## Supported Platforms

- **PagerDuty** - Full support for incidents, escalations, MTTR
- **Opsgenie** - Alert management and on-call (coming soon)
- **Incident.io** - Incident lifecycle management (coming soon)

---

## PagerDuty

### Step 1: Get Incident Context

```python
# Get details of the current incident
pagerduty_get_incident(incident_id="P123ABC")

# Get incident timeline/log entries
pagerduty_get_incident_log_entries(incident_id="P123ABC")

# List recent incidents (filter by status)
pagerduty_list_incidents(status="triggered", max_results=25)
pagerduty_list_incidents(status="acknowledged")
```

**Returns:**
- Incident title, status, urgency
- Service affected
- Who acknowledged, when
- Timeline of actions taken

### Step 2: Find Similar Past Incidents

```python
# Get incidents from a date range
pagerduty_list_incidents_by_date_range(
    since="2024-01-01T00:00:00Z",
    until="2024-01-31T23:59:59Z",
    service_ids=["PSERVICE123"]
)

# Analyze alert patterns (fire frequency, ack rate, MTTR)
pagerduty_get_alert_analytics(
    since="2024-01-01T00:00:00Z",
    until="2024-01-31T23:59:59Z",
    service_id="PSERVICE123"
)
```

**Look for:**
- Same alert title recurring → Known issue or flapping
- Cluster of alerts → Systemic problem
- Low ack rate → Possible alert fatigue

### Step 3: Check Who's On-Call

```python
# Get current on-call schedule
pagerduty_get_on_call()

# Get escalation policy details
pagerduty_get_escalation_policy(policy_id="PPOLICY123")

# List all services
pagerduty_list_services()
```

### Step 4: Calculate Historical MTTR

```python
# Get MTTR for this service
pagerduty_calculate_mttr(service_id="PSERVICE123", days=30)
```

**Returns:**
- Average MTTR (minutes/hours)
- Median MTTR
- 95th percentile
- Fastest/slowest resolution

---

## Available Tools

### PagerDuty Tools

| Tool | Purpose |
|------|---------|
| `pagerduty_get_incident` | Get incident details |
| `pagerduty_get_incident_log_entries` | Get incident timeline |
| `pagerduty_list_incidents` | List incidents with filters |
| `pagerduty_list_incidents_by_date_range` | Historical incident query |
| `pagerduty_get_alert_analytics` | Alert frequency/pattern analysis |
| `pagerduty_get_escalation_policy` | Who gets paged at each level |
| `pagerduty_get_on_call` | Current on-call users |
| `pagerduty_list_services` | All PagerDuty services |
| `pagerduty_calculate_mttr` | Mean time to resolve stats |

---

## Common Patterns

### Pattern 1: "Is this a known issue?"

```python
# Search for similar alerts in last 30 days
results = pagerduty_list_incidents_by_date_range(
    since="2024-01-01T00:00:00Z",
    until="2024-01-31T23:59:59Z"
)

# Check the 'top_alerts' field for recurring alert titles
# Look at 'by_service' for affected services
```

### Pattern 2: "Alert Fatigue Analysis"

```python
# Get comprehensive alert analytics
analytics = pagerduty_get_alert_analytics(
    since="2024-01-01T00:00:00Z",
    until="2024-01-31T23:59:59Z"
)

# Check for:
# - is_noisy: High frequency, low ack rate
# - is_flapping: Quick auto-resolve pattern
# - off_hours_rate: Alerts waking people up unnecessarily
```

### Pattern 3: "Escalation Investigation"

```python
# Was this escalated?
incident = pagerduty_get_incident(incident_id="P123ABC")
# Check 'assignments' and 'acknowledgements'

# Who was supposed to respond?
policy = pagerduty_get_escalation_policy(policy_id=incident['escalation_policy_id'])
```

### Pattern 4: "SLA/MTTR Tracking"

```python
# Get MTTR for incident comparison
mttr = pagerduty_calculate_mttr(service_id="PSERVICE123", days=30)

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
- **Ack rate**: Y%
- **This alert fires**: Z times/week on average

### Related Alerts
[List any other alerts that fired around the same time]

### Recommendations
- [If recurring] Review runbook for this alert
- [If long duration] Consider escalating
- [If noisy] Consider tuning alert threshold
```

---

## Pro Tips

**Start with the incident, expand outward:**
1. Get the specific incident details first
2. Then check related/similar incidents
3. Then look at service-wide patterns

**Time windows matter:**
- Use specific timestamps, not relative times
- PagerDuty API expects ISO 8601 format: `2024-01-15T14:30:00Z`

**Service IDs:**
- Use `pagerduty_list_services()` to discover service IDs
- Filter by service to reduce noise in queries

**Alert analytics insights:**
- `is_noisy=true`: High frequency, low ack rate → Tune or suppress
- `is_flapping=true`: Quick auto-resolve → Fix underlying issue
- `off_hours_rate > 50%`: Waking people up → Review urgency

---

## Anti-Patterns

1. **Ignoring past incidents** - Always check if it's a known issue
2. **Not checking on-call** - Know who's responding before investigating
3. **Missing correlated alerts** - One incident might mask the real issue
4. **Forgetting MTTR context** - Know what "normal" resolution looks like
5. **Unbounded queries** - Always use time ranges to avoid timeout
