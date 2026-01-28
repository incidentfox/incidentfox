---
name: coralogix-analysis
description: Expert guidance for analyzing Coralogix logs using partition-first methodology. Use when investigating errors, analyzing log patterns, or troubleshooting services via Coralogix.
---

# Coralogix Log Analysis Methodology

## Core Principle: Statistics Before Samples

**NEVER start by reading raw logs.** Always begin with aggregated statistics to understand the landscape.

## 3-Step Analysis Process

### Step 1: Get the Big Picture

Start every Coralogix investigation with aggregate queries:

**Use DataPrime aggregations:**
```
# How many logs total?
source logs | stats count() as total

# What services are logging?
source logs | groupby $l.subsystemname aggregate count() as cnt | orderby cnt desc

# Error severity breakdown
source logs | groupby $m.severity aggregate count() as cnt

# Error rate over time
source logs | filter $m.severity >= '4' | timebucket 5m aggregate count() as errors
```

**Questions to answer:**
- What's the total log volume in the time window?
- Which services are most active?
- What's the error rate (severity 4-6)?
- Is the error rate increasing, stable, or decreasing?

### Step 2: Identify Error Patterns

Focus on error characteristics:

**Most common errors:**
```
source logs 
| filter $m.severity >= '5' 
| groupby $l.subsystemname aggregate count() as error_count 
| orderby error_count desc 
| limit 10
```

**Error types by service:**
```
source logs 
| filter $l.subsystemname == 'your-service' 
| filter $m.severity >= '5' 
| groupby extract($d.logRecord.body, 'Error|Exception') aggregate count()
```

**Temporal clustering:**
- Did errors start at a specific time?
- Correlation with deployments or traffic changes?
- Is there periodicity (every N minutes)?

### Step 3: Sample Strategically

Only NOW examine actual log content:

**Sample from peaks:**
```
source logs 
| filter $l.subsystemname == 'problematic-service' 
| filter @timestamp >= '2024-01-15T14:30:00' and @timestamp <= '2024-01-15T14:35:00'
| filter $m.severity >= '5' 
| limit 10
```

**Sample by error type:**
- Get 5-10 examples of each distinct error
- Compare against baseline period (normal behavior)

## Available Coralogix Tools

| Tool | When to Use |
|------|-------------|
| `search_coralogix_logs` | Execute any DataPrime query |
| `list_coralogix_services` | Discover active services |
| `get_coralogix_error_logs` | Get errors for a specific service |
| `get_coralogix_service_health` | Overall service health summary |
| `get_coralogix_alerts` | Check firing alerts |
| `search_coralogix_traces` | Distributed trace analysis |

## DataPrime Syntax Quick Reference

**Filters:**
```
# Exact match (note: use == not =)
$l.subsystemname == 'api-server'

# Severity levels: 1=Debug, 2=Verbose, 3=Info, 4=Warning, 5=Error, 6=Critical
$m.severity >= '5'

# Text search (case-insensitive)
$d ~~ 'timeout'

# Combine filters
$l.subsystemname == 'api' && $m.severity >= '4'
```

**Aggregations:**
```
# Count
| aggregate count() as total

# Group by field
| groupby $l.subsystemname aggregate count() as cnt

# Time bucketing
| timebucket 5m aggregate count() as cnt

# Multiple aggregations
| groupby $l.subsystemname aggregate count() as cnt, avg($d.duration) as avg_duration
```

**Common Fields:**
- `$l.applicationname` - Application/environment name
- `$l.subsystemname` - Service name
- `$m.severity` - Log level (1-6)
- `$d.logRecord.body` - Log message content
- `@timestamp` - Log timestamp

## Anti-Patterns to Avoid

1. ❌ **Dumping raw logs first** - Always start with statistics
2. ❌ **Unbounded queries** - Always specify time ranges
3. ❌ **Ignoring severity** - Filter by `$m.severity` to focus on errors
4. ❌ **Single service focus** - Check dependencies and upstream services
5. ❌ **Missing temporal context** - Correlate with deployments/changes

## Investigation Template

```markdown
## Coralogix Analysis Summary

### Time Window
- Start: [timestamp]
- End: [timestamp]
- Duration: X hours

### Statistics
- Total logs: X events
- Error count (severity >=5): Y events (Z%)
- Services affected: N services
- Error rate trend: [increasing/stable/decreasing]

### Top Error Services
1. [service1]: N errors
2. [service2]: M errors

### Error Pattern
- Primary error type: [description]
- First occurrence: [timestamp]
- Correlation: [deployment/traffic spike/external event]

### Sample Errors
[Quote 2-3 representative error messages with context]

### Root Cause Hypothesis
[Based on patterns observed in aggregations]
```

## Pro Tips

**Efficient querying:**
- Use `list_coralogix_services` to discover service names before filtering
- Start with 1-hour windows, expand only if needed
- Limit initial results to 20-50 entries

**Pattern recognition:**
- Look for error clusters (many errors in short time)
- Check if errors are distributed or focused on one service
- Compare error types before/after a specific timestamp

**Trace correlation:**
- Use `search_coralogix_traces` to connect logs to distributed traces
- Filter traces by `min_duration_ms` to find slow requests
- Correlate high-latency traces with error spikes
