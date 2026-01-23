---
name: log-analysis
description: Partition-first log analysis methodology. Use for log searches, error analysis, pattern finding across Datadog, CloudWatch, or Kubernetes logs.
---

# Log Analysis Methodology

## Core Philosophy: Partition-First

**NEVER start by reading raw log samples.**

Logs can be overwhelming. The partition-first approach prevents:
- Missing the forest for the trees
- Wasting time on irrelevant data
- Overwhelming context with noise

## The 4-Step Process

### Step 1: Get Statistics

Before ANY log search, understand the landscape:

**CloudWatch Insights**:
```
# How many errors?
filter @message like /ERROR/
| stats count(*) as total

# Error rate over time
filter @message like /ERROR/
| stats count(*) by bin(5m)

# What types of errors?
filter @message like /ERROR/
| parse @message /(?<error_type>[\w.]+Exception)/
| stats count(*) by error_type
| sort count desc
```

**Datadog**:
```
# Error distribution by service
service:* status:error | stats count by service

# Error types
service:myapp status:error | stats count by @error.kind
```

**Questions to answer**:
- What's the total error volume?
- Is it increasing, stable, or decreasing?
- What are the unique error types?
- Which services/hosts are affected?

### Step 2: Identify Patterns

Look for correlations:

**Temporal patterns**:
- Did errors start at a specific time?
- Is there periodicity (every hour, every day)?
- Correlation with deployments or traffic spikes?

**Service patterns**:
- Is one service the source?
- Is the error propagating across services?

**Error patterns**:
- What's the most frequent error?
- Are errors clustered or distributed?

### Step 3: Sample Strategically

Only NOW read actual log samples:

**Sample from anomalies**:
- Get logs from the peak error time
- Get logs from normal time for comparison

**Sample by error type**:
- Get examples of each distinct error type
- Limit to 5-10 per type

**Sample around events**:
- Logs before/after a deployment
- Logs around a specific incident timestamp

### Step 4: Correlate with Events

Connect logs to system changes:

```
# Use git_log to find recent deployments
git_log --since="2 hours ago"

# Use get_deployment_history for K8s
get_deployment_history deployment=api-server

# Compare log patterns before/after changes
```

## Platform-Specific Tips

### CloudWatch Insights

**Best practices**:
```
# Always include time filter
filter @timestamp > ago(1h)

# Use parse for structured extraction
parse @message /status=(?<status>\d+)/

# Aggregate before displaying
stats count(*) by status | sort count desc | limit 10
```

**Common queries**:
```
# Latency distribution
filter @type = "REPORT"
| stats avg(@duration) as avg,
        pct(@duration, 95) as p95,
        pct(@duration, 99) as p99

# Error messages with context
filter @message like /ERROR/
| fields @timestamp, @message
| sort @timestamp desc
| limit 20
```

### Datadog Logs

**Query syntax**:
```
# Filter by service and status
service:api-gateway status:error

# Field queries
@http.status_code:>=500

# Wildcard
@error.message:*timeout*

# Time comparison
service:api (now-1h TO now) vs (now-25h TO now-24h)
```

### Kubernetes Logs

**Use get_pod_logs wisely**:
- Always specify `tail_lines` (default: 100)
- Filter to specific containers in multi-container pods
- Use `get_pod_events` first for crashes/restarts

## Anti-Patterns to Avoid

1. **Dumping all logs** - Never request unbounded log queries
2. **Starting with samples** - Always get statistics first
3. **Ignoring time windows** - Narrow to incident window
4. **Missing correlation** - Always connect to deployments/changes
5. **Single-service focus** - Check upstream/downstream services

## Investigation Template

```
## Log Analysis Report

### Statistics
- Time window: [start] to [end]
- Total log volume: X events
- Error count: Y events (Z%)
- Error rate trend: [increasing/stable/decreasing]

### Top Error Types
1. [ErrorType1]: N occurrences - [description]
2. [ErrorType2]: M occurrences - [description]

### Temporal Pattern
- Errors started at: [timestamp]
- Correlation: [deployment X / traffic spike / external event]

### Sample Errors
[Quote 2-3 representative error messages]

### Root Cause Hypothesis
[Based on patterns, what's the likely cause?]
```
