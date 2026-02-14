---
name: datadog-analysis
description: Datadog log and metrics analysis. Use when querying Datadog logs, metrics, or APM data. Provides scripts and query syntax reference.
category: observability
required_integrations:
  - datadog
allowed-tools: Bash(python *)
---

# Datadog Analysis

## Authentication

**IMPORTANT**: Credentials are injected automatically by a proxy layer. Do NOT check for `DATADOG_API_KEY` or `DATADOG_APP_KEY` in environment variables - they won't be visible to you. Just run the scripts directly; authentication is handled transparently.

Configuration environment variables you CAN check (non-secret):
- `DATADOG_SITE` - Datadog site (e.g., `us5.datadoghq.com`, `datadoghq.eu`)

---

## MANDATORY: Statistics-First Investigation

**NEVER dump raw logs.** Always follow this pattern:

```
STATISTICS → SAMPLE → PATTERNS → CORRELATE
```

1. **Statistics First** - Know volume, error rate, and top patterns before sampling
2. **Strategic Sampling** - Choose the right strategy based on statistics
3. **Pattern Extraction** - Cluster similar errors to find root causes
4. **Context Correlation** - Investigate around anomaly timestamps

## Available Scripts

All scripts are in `.claude/skills/observability-datadog/scripts/`

### PRIMARY INVESTIGATION SCRIPTS

#### get_statistics.py - ALWAYS START HERE
Comprehensive statistics with pattern extraction.
```bash
python .claude/skills/observability-datadog/scripts/get_statistics.py [--service SERVICE] [--time-range MINUTES]

# Examples:
python .claude/skills/observability-datadog/scripts/get_statistics.py --time-range 60
python .claude/skills/observability-datadog/scripts/get_statistics.py --service payment
```

Output includes:
- Total count, error count, error rate percentage
- Status distribution (info, warn, error)
- Top services by log volume
- **Top error patterns** (crucial for quick triage)
- Actionable recommendation

#### sample_logs.py - Strategic Sampling
Choose the right sampling strategy based on statistics.
```bash
python .claude/skills/observability-datadog/scripts/sample_logs.py --strategy STRATEGY [--service SERVICE] [--limit N]

# Strategies:
#   errors_only   - Only error logs (default for incidents)
#   warnings_up   - Warning and error logs
#   around_time   - Logs around a specific timestamp
#   all           - All log levels

# Examples:
python .claude/skills/observability-datadog/scripts/sample_logs.py --strategy errors_only --service payment
python .claude/skills/observability-datadog/scripts/sample_logs.py --strategy around_time --timestamp "2026-01-27T05:00:00Z" --window 5
```

---

## Datadog Query Language (DQL)

### Basic Filters
```
# Service filter
service:payment

# Status filter
status:error
status:warn

# Host filter
host:web-server-01

# Combine with AND (space) or OR
service:payment status:error
service:payment OR service:checkout
```

### Facet Filters
```
# Tag filter
env:production
version:1.2.3

# Attribute filter
@http.status_code:>=500
@duration:>1000

# Wildcard
service:payment-*
```

### Time Ranges
```
# Relative
@timestamp:[now-1h TO now]

# Absolute
@timestamp:[2026-01-27T00:00:00Z TO 2026-01-27T12:00:00Z]
```

### Common Patterns
```
# All errors in last hour
status:error

# Errors for specific service
service:api-gateway status:error

# Slow requests (>1s)
@duration:>1000000

# HTTP 5xx errors
@http.status_code:>=500

# Exceptions
*exception* OR *error* OR *failed*
```

---

## Investigation Workflow

### Standard Incident Investigation

```
┌─────────────────────────────────────────────────────────────┐
│ 1. STATISTICS FIRST (mandatory)                              │
│    python get_statistics.py --service <service>              │
│    → Know volume, error rate, top patterns                   │
└─────────────────────────────────────────────────────────────┘
                             │
                             ▼
                     High Error Rate?
               ┌─────────────┴─────────────┐
               │                           │
       YES (>5%)                           NO
               │                           │
               ▼                           ▼
┌─────────────────────────────┐  ┌───────────────────────────────────────────┐
│ 2. FAST PATH                │  │ 2. TARGETED INVESTIGATION                 │
│    Sample errors directly   │  │    Filter by specific criteria            │
│    python sample_logs.py    │  │    python sample_logs.py --strategy all   │
│    --strategy errors_only   │  │    → Look for anomalies                   │
└─────────────────────────────┘  └───────────────────────────────────────────┘
```

### Quick Commands Reference

| Goal | Command |
|------|---------|
| Start investigation | `get_statistics.py --service X` |
| Sample errors only | `sample_logs.py --strategy errors_only --service X` |
| Investigate spike | `sample_logs.py --strategy around_time --timestamp T` |
| All logs | `sample_logs.py --strategy all --service X --limit 20` |

---

## Metrics Query Syntax

### Basic Structure
```
aggregation:metric_name{tag_filters}
```

### Aggregations
```
avg:   - Average across series
sum:   - Sum across series
min:   - Minimum value
max:   - Maximum value
p50:   - 50th percentile (APM)
p95:   - 95th percentile (APM)
p99:   - 99th percentile (APM)
```

### Common Metrics
```
# System
avg:system.cpu.user{service:X}
avg:system.mem.used{service:X}

# APM (traces)
sum:trace.http.request.hits{service:X}.as_rate()
sum:trace.http.request.errors{service:X}.as_rate()
p95:trace.http.request.duration{service:X}
```

---

## Anti-Patterns to Avoid

1. ❌ **NEVER skip statistics** - `get_statistics.py` is MANDATORY first step
2. ❌ **Unbounded queries** - Always specify time ranges and limits
3. ❌ **Fetching all logs** - Use sampling strategies, not unbounded searches
4. ❌ **Ignoring error rate** - High error rate means immediate investigation
5. ❌ **Missing service filter** - For multi-service apps, always filter by service
