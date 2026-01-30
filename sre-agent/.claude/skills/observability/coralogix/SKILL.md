---
name: coralogix-analysis
description: Coralogix log analysis with DataPrime query language. Use when querying Coralogix logs, metrics, or traces. Provides syntax reference and intelligent investigation scripts.
---

# Coralogix Analysis

## Authentication

**IMPORTANT**: Credentials are injected automatically by a proxy layer. Do NOT check for `CORALOGIX_API_KEY` or other API keys in environment variables - they won't be visible to you. Just run the scripts directly; authentication is handled transparently.

Configuration environment variables you CAN check (non-secret):
- `CORALOGIX_DOMAIN` - Team hostname (e.g., `myteam.app.cx498.coralogix.com`)
- `CORALOGIX_REGION` - Region code (e.g., `us2`, `eu1`) - fallback if domain not set

**Region mapping** (the scripts auto-detect based on domain):
- US1: `*.app.coralogix.us` → `api.us1.coralogix.com`
- US2: `*.app.cx498.coralogix.com` → `api.us2.coralogix.com`
- EU1: `*.coralogix.com` → `api.eu1.coralogix.com`
- EU2: `*.app.eu2.coralogix.com` → `api.eu2.coralogix.com`
- AP1: `*.app.coralogix.in` → `api.ap1.coralogix.com`
- AP2: `*.app.coralogixsg.com` → `api.ap2.coralogix.com`

---

## MANDATORY: Statistics-First Investigation

**NEVER dump raw logs.** Always follow this pattern:

```
STATISTICS → SAMPLE → SIGNATURES → CORRELATE
```

1. **Statistics First** - Know volume, error rate, and top patterns before sampling
2. **Strategic Sampling** - Choose the right strategy based on statistics
3. **Pattern Extraction** - Cluster similar errors to find root causes
4. **Context Correlation** - Investigate around anomaly timestamps

## Available Scripts

All scripts are in `.claude/skills/observability/coralogix/scripts/`

### PRIMARY INVESTIGATION SCRIPTS

#### get_statistics.py - ALWAYS START HERE
Comprehensive statistics with pattern extraction and anomaly detection.
```bash
python .claude/skills/observability/coralogix/scripts/get_statistics.py [--service SERVICE] [--app APP] [--time-range MINUTES]

# Examples:
python .claude/skills/observability/coralogix/scripts/get_statistics.py --time-range 60
python .claude/skills/observability/coralogix/scripts/get_statistics.py --service payment --app otel-demo
```

Output includes:
- Total count, error count, error rate percentage
- Severity distribution
- **Top error patterns** (crucial for quick triage)
- Time bucket anomalies (spike/drop detection via z-score)
- Top services by log volume
- Actionable recommendation

#### sample_logs.py - Strategic Sampling
Choose the right sampling strategy based on statistics.
```bash
python .claude/skills/observability/coralogix/scripts/sample_logs.py --strategy STRATEGY [--service SERVICE] [--app APP]

# Strategies:
#   errors_only   - Only ERROR/CRITICAL logs (default for incidents)
#   around_anomaly - Logs within time window of specific timestamp
#   first_last    - First N/2 + last N/2 logs (timeline view)
#   random        - Random sample across time range
#   all           - All severity levels (use sparingly)

# Examples:
python .claude/skills/observability/coralogix/scripts/sample_logs.py --strategy errors_only --service payment
python .claude/skills/observability/coralogix/scripts/sample_logs.py --strategy around_anomaly --timestamp "2026-01-27T05:00:00Z" --window 60
python .claude/skills/observability/coralogix/scripts/sample_logs.py --strategy first_last --service checkout --limit 50
```

#### extract_signatures.py - Pattern Clustering
Normalize and cluster log messages to see unique issue patterns.
```bash
python .claude/skills/observability/coralogix/scripts/extract_signatures.py --service SERVICE [--severity SEVERITY] [--max-signatures N]

# Examples:
python .claude/skills/observability/coralogix/scripts/extract_signatures.py --service payment --severity ERROR
python .claude/skills/observability/coralogix/scripts/extract_signatures.py --app otel-demo --max-signatures 30
```

Normalizes variable parts (UUIDs, IPs, timestamps, numbers) to find:
- Dominant error patterns (> 50% = single root cause likely)
- Diverse errors (many patterns = multiple issues)
- Affected services per pattern

### UTILITY SCRIPTS

#### list_services.py - Service Discovery
```bash
python .claude/skills/observability/coralogix/scripts/list_services.py [--time-range MINUTES]
```

#### get_health.py - Quick Health Check
```bash
python .claude/skills/observability/coralogix/scripts/get_health.py <service> [--time-range MINUTES]
```

#### get_errors.py - Quick Error Fetch
```bash
python .claude/skills/observability/coralogix/scripts/get_errors.py <service> [--app APPLICATION] [--time-range MINUTES]
```

#### query_logs.py - Raw DataPrime Queries
For custom queries not covered by other scripts.
```bash
python .claude/skills/observability/coralogix/scripts/query_logs.py "<dataprime_query>" [--time-range MINUTES] [--limit N]
```

## DataPrime Syntax Quick Reference

### Filters
```dataprime
# Equality (use == not =)
$l.subsystemname == 'api-server'

# Severity - use ENUM values (no quotes!)
# Valid: VERBOSE, DEBUG, INFO, WARNING, ERROR, CRITICAL
$m.severity == ERROR
$m.severity == WARNING || $m.severity == ERROR

# Text search (case-insensitive) - use ~~ not 'contains'
$d ~~ 'timeout'
$d ~~ 'connection refused'

# Combine filters with &&
$l.subsystemname == 'payment' && $m.severity == ERROR
```

### Aggregations
```dataprime
# Count
| aggregate count() as total

# Group by field
| groupby $l.subsystemname aggregate count() as cnt

# Time bucketing
| timebucket 5m aggregate count() as cnt

# Multiple aggregations
| groupby $l.subsystemname aggregate count() as cnt, avg($d.duration) as avg_duration

# Order and limit
| orderby cnt desc | limit 20
```

### Common Fields
- `$l.applicationname` - Application/environment name (e.g., "otel-demo")
- `$l.subsystemname` - Service name (e.g., "payment", "checkout")
- `$m.severity` - Log level enum: VERBOSE, DEBUG, INFO, WARNING, ERROR, CRITICAL
- `$m.timestamp` - Event timestamp
- `$d` - Log message/data (use ~~ for text search)

## Common Query Patterns

### 1. List all services with log counts
```dataprime
source logs | groupby $l.subsystemname aggregate count() as cnt | orderby cnt desc | limit 30
```

### 2. Error count by service
```dataprime
source logs | filter $m.severity == ERROR | groupby $l.subsystemname aggregate count() as errors | orderby errors desc
```

### 3. Error rate over time
```dataprime
source logs | filter $m.severity == ERROR | groupby $m.timestamp / 5m as bucket aggregate count() as errors | orderby bucket asc
```

### 4. Errors for specific service
```dataprime
source logs | filter $l.subsystemname == 'payment' | filter $m.severity == ERROR | limit 50
```

### 5. Search for specific error message
```dataprime
source logs | filter $d ~~ 'connection refused' | limit 20
```

## Advanced DataPrime Patterns

### Bracket Notation for Special Fields
K8s fields often have dots in names. Use bracket notation:
```dataprime
# Wrong - treats as nested path
$d.kubernetes.namespace

# Correct - literal field name with dot
$d['kubernetes.namespace']
$d['resource.attributes.k8s_pod_name']
```

### Time-Based Comparisons
Compare logs before/after a time threshold:
```dataprime
# Count logs in last hour vs older
source logs | countby if($m.timestamp > now() - 1h, 'last_hour', 'older')

# Find logs older than 5 minutes
source logs | filter $m.timestamp < now() - 5m
```

### K8s Container Restarts
Find unstable containers:
```dataprime
source logs
| choose resource.attributes.k8s_container_restart_count:number as restarts,
         resource.attributes.k8s_container_name as container,
         resource.attributes.k8s_deployment_name as deployment
| filter restarts > 0
| groupby deployment aggregate max(restarts) as max_restarts
| orderby max_restarts desc
```

### Peak Error Window
Find the 10-minute window with most errors:
```dataprime
source logs
| filter $m.severity == ERROR
| groupby $m.timestamp / 10m as bucket aggregate count() as cnt
| orderby cnt desc
| limit 5
```

### Fuzzy Search All Fields
When you don't know which field contains the value:
```dataprime
# Search all fields for text
source logs | filter $d ~~ 'connection refused'

# Or use wildfind
source logs | wildfind 'timeout'
```

## Anti-Patterns to Avoid

1. ❌ **NEVER skip statistics** - `get_statistics.py` is MANDATORY first step
2. ❌ **Unbounded queries** - Always specify time ranges and limits
3. ❌ **Quoting severity values** - Use enum: `ERROR` not `'ERROR'`
4. ❌ **Using 'contains'** - Use ~~ operator for text search
5. ❌ **Missing application filter** - For multi-tenant, filter by $l.applicationname
6. ❌ **Fetching all logs** - Use sampling strategies, not `limit 10000`
7. ❌ **Ignoring anomaly timestamps** - Use `around_anomaly` to investigate spikes
8. ❌ **Reading logs without patterns** - Always extract signatures for RCA
9. ❌ **Dot notation for K8s fields** - Use bracket notation: `$d['k8s.pod.name']`

## Investigation Workflow

### Standard Incident Investigation

```
┌─────────────────────────────────────────────────────────────┐
│ 1. STATISTICS FIRST (mandatory)                              │
│    python get_statistics.py --service <service>              │
│    → Know volume, error rate, top patterns, anomalies        │
└─────────────────────────────────────────────────────────────┘
                             │
                             ▼
                     Dominant Issue?
               ┌─────────────┴─────────────┐
               │                           │
      YES (>80% one pattern)               NO (mixed errors)
               │                           │
               ▼                           ▼
┌─────────────────────────────┐  ┌───────────────────────────────────────────┐
│ 2. FAST PATH                │  │ 2. DEEP DIVE                              │
│    Sample errors directly   │  │    python extract_signatures.py           │
│    python sample_logs.py    │  │    python sample_logs.py --strategy ...   │
│    → Verify hypothesis      │  │    → Cluster and analyze patterns         │
└─────────────────────────────┘  └───────────────────────────────────────────┘
```

### Example: Payment Service Investigation

```bash
# Step 1: Statistics first - ALWAYS
python .claude/skills/observability/coralogix/scripts/get_statistics.py --service payment --time-range 60
# Output: 15,432 logs, 847 errors (5.5%), top pattern: "Connection timeout to downstream"

# IF dominant pattern found:
# Step 2: Verify with samples
python .claude/skills/observability/coralogix/scripts/sample_logs.py --strategy errors_only --service payment --limit 10
```

### Quick Commands Reference

| Goal | Command |
|------|---------|
| Start investigation | `get_statistics.py --service X` |
| See error variety | `extract_signatures.py --service X` |
| Sample errors only | `sample_logs.py --strategy errors_only --service X` |
| Investigate spike | `sample_logs.py --strategy around_anomaly --timestamp T` |
| Timeline view | `sample_logs.py --strategy first_last --service X` |
| List all services | `list_services.py` |
| Custom query | `query_logs.py "source logs | ..."` |

---

## Trace Investigation

Use traces to understand **request flow** and **latency** across services.

### When to Use Traces vs Logs

| Use Case | Tool |
|----------|------|
| "What errors happened?" | Logs (`get_statistics.py`) |
| "Why is this request slow?" | Traces (`get_slow_spans.py`) |
| "Where did the request fail?" | Traces (`get_traces.py`) |
| "What's the service dependency?" | Traces (operation analysis) |

### Trace Scripts

#### get_traces.py - Find Spans
```bash
# Get spans for a service
python .claude/skills/observability/coralogix/scripts/get_traces.py --service checkout --time-range 30

# Get all spans for a trace ID
python .claude/skills/observability/coralogix/scripts/get_traces.py --trace-id abc123def456

# Filter by operation
python .claude/skills/observability/coralogix/scripts/get_traces.py --operation "/api/checkout" --service checkout
```

#### get_slow_spans.py - Latency Analysis
```bash
# Find spans slower than 500ms
python .claude/skills/observability/coralogix/scripts/get_slow_spans.py --min-duration 500

# Find slow spans in specific service
python .claude/skills/observability/coralogix/scripts/get_slow_spans.py --min-duration 200 --service checkout

# Get latency statistics by service (recommended first step)
python .claude/skills/observability/coralogix/scripts/get_slow_spans.py --stats
```

### DataPrime Spans Syntax

Spans use `source spans` but with **different field names** than logs:

```dataprime
# List spans for a service (use serviceName, not $l.subsystemname)
source spans | filter serviceName == 'checkout' | limit 50

# Find slow spans (duration in MICROSECONDS)
source spans | filter duration > 500000 | orderby duration desc | limit 20

# Get all spans for a trace (use top-level traceID)
source spans | filter traceID == 'abc123def456...' | limit 100

# Latency statistics by service
source spans | groupby serviceName aggregate avg(duration) as avg_dur, max(duration) as max_dur | orderby avg_dur desc
```

### Span Fields Reference (different from logs!)
- `operationName` - Operation name (e.g., `HTTP GET /checkout`)
- `serviceName` - Service name (equivalent to logs' `$l.subsystemname`)
- `applicationName` - Application name
- `duration` - Span duration in **microseconds**
- `traceID` - Trace identifier (32-char hex)
- `spanID` - Span identifier
- `parentId` - Parent span ID (for trace tree)
- `tags` - Span metadata (e.g., `http.status_code`, `rpc.method`)
- `process.tags` - Resource attributes (e.g., `k8s.pod.name`)

### Trace Investigation Workflow

```
┌─────────────────────────────────────────────────────────────┐
│ 1. CHECK LATENCY STATS                                       │
│    python get_slow_spans.py --stats                          │
│    → See which services have high latency                    │
└─────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. FIND SLOW SPANS                                           │
│    python get_slow_spans.py --min-duration 500 --service X   │
│    → Get specific slow spans with trace IDs                  │
└─────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. TRACE FULL REQUEST                                        │
│    python get_traces.py --trace-id <id>                      │
│    → See all spans in the slow request                       │
└─────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. CORRELATE WITH LOGS                                       │
│    python sample_logs.py --strategy around_anomaly           │
│    → Get logs around the same timestamp                      │
└─────────────────────────────────────────────────────────────┘
```
