---
name: splunk-analysis
description: Splunk log analysis using SPL (Search Processing Language). Use when investigating issues via Splunk logs, saved searches, or alerts.
allowed-tools: Bash(python *)
---

# Splunk Analysis

## Authentication

**IMPORTANT**: Credentials are injected automatically by a proxy layer. Do NOT check for `SPLUNK_HOST`, `SPLUNK_TOKEN`, or other credentials in environment variables - they won't be visible to you. Just run the scripts directly; authentication is handled transparently.

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

All scripts are in `.claude/skills/observability/splunk/scripts/`

### PRIMARY INVESTIGATION SCRIPTS

#### get_statistics.py - ALWAYS START HERE
Comprehensive statistics with pattern extraction.
```bash
python .claude/skills/observability/splunk/scripts/get_statistics.py [--index INDEX] [--sourcetype SOURCETYPE] [--time-range MINUTES]

# Examples:
python .claude/skills/observability/splunk/scripts/get_statistics.py --time-range 60
python .claude/skills/observability/splunk/scripts/get_statistics.py --index main
python .claude/skills/observability/splunk/scripts/get_statistics.py --sourcetype access_combined
```

Output includes:
- Total count, error count, error rate percentage
- Status distribution (info, warn, error)
- Top sourcetypes and hosts by log volume
- **Top error patterns** (crucial for quick triage)
- Actionable recommendation

#### sample_logs.py - Strategic Sampling
Choose the right sampling strategy based on statistics.
```bash
python .claude/skills/observability/splunk/scripts/sample_logs.py --strategy STRATEGY [--index INDEX] [--sourcetype SOURCETYPE] [--limit N]

# Strategies:
#   errors_only   - Only error logs (default for incidents)
#   warnings_up   - Warning and error logs
#   around_time   - Logs around a specific timestamp
#   all           - All log levels

# Examples:
python .claude/skills/observability/splunk/scripts/sample_logs.py --strategy errors_only --index main
python .claude/skills/observability/splunk/scripts/sample_logs.py --strategy around_time --timestamp "2026-01-27T05:00:00" --window 5
python .claude/skills/observability/splunk/scripts/sample_logs.py --strategy all --sourcetype access_combined --limit 20
```

---

## SPL (Search Processing Language)

### Basic Search

```spl
# Simple keyword search
error

# Index specific search (ALWAYS specify index for performance)
index=main error

# Multiple keywords (implicit AND)
index=main error connection

# Exact phrase
index=main "connection refused"
```

### Field Searches

```spl
# Exact field match
index=main host=web-01

# Wildcard
index=main host=web-*

# Numeric comparison
index=main status>=400

# NOT operator
index=main NOT status=200

# OR operator
index=main (status=500 OR status=503)
```

### Time Range

```spl
# Relative time (in tool call)
earliest=-15m latest=now

# Absolute time
earliest="01/15/2024:10:00:00" latest="01/15/2024:11:00:00"

# Natural time modifiers
earliest=-1h@h  # 1 hour ago, rounded to hour
earliest=-1d@d  # 1 day ago, rounded to day
```

---

## Investigation Workflow

### Standard Incident Investigation

```
┌─────────────────────────────────────────────────────────────┐
│ 1. STATISTICS FIRST (mandatory)                              │
│    python get_statistics.py --index <index>                  │
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
| Start investigation | `get_statistics.py --index X` |
| Sample errors only | `sample_logs.py --strategy errors_only --index X` |
| Investigate spike | `sample_logs.py --strategy around_time --timestamp T` |
| All logs | `sample_logs.py --strategy all --index X --limit 20` |

---

## SPL Commands Reference

### Filtering Commands

| Command | Purpose | Example |
|---------|---------|---------|
| `search` | Filter events | `search error` |
| `where` | Filter with expressions | `where status > 400` |
| `dedup` | Remove duplicates | `dedup host` |
| `head` | First N results | `head 10` |
| `tail` | Last N results | `tail 10` |

### Transformation Commands

| Command | Purpose | Example |
|---------|---------|---------|
| `stats` | Aggregate statistics | `stats count by host` |
| `timechart` | Time-based aggregation | `timechart span=5m count` |
| `chart` | Pivot table | `chart count by status, host` |
| `top` | Top values | `top 10 host` |
| `rare` | Rare values | `rare message` |
| `table` | Select fields | `table _time, host, message` |

### Field Operations

| Command | Purpose | Example |
|---------|---------|---------|
| `eval` | Calculate fields | `eval duration_sec=duration/1000` |
| `rex` | Regex extraction | `rex field=message "error: (?<error_type>\w+)"` |
| `rename` | Rename fields | `rename src_ip as source_ip` |
| `fields` | Include/exclude fields | `fields host, message` |

---

## Common Query Patterns

### Error Rate Analysis

```spl
# Error count per 5 minutes
index=main | timechart span=5m count(eval(level="ERROR")) as errors, count as total

# Error percentage over time
index=main
| timechart span=5m count(eval(level="ERROR")) as errors, count as total
| eval error_rate=errors/total*100
```

### Top Errors by Service

```spl
index=main level=ERROR
| stats count by service, message
| sort -count
| head 20
```

### Response Time Analysis

```spl
index=main sourcetype=access_combined
| stats avg(response_time) as avg_rt,
        p95(response_time) as p95_rt,
        max(response_time) as max_rt
    by uri_path
| sort -avg_rt
```

### Anomaly Detection

```spl
# Sudden spike detection
index=main
| timechart span=5m count as events
| eventstats avg(events) as avg_events, stdev(events) as stdev_events
| eval anomaly=if(events > avg_events + 2*stdev_events, 1, 0)
| where anomaly=1
```

---

## Anti-Patterns to Avoid

1. ❌ **NEVER skip statistics** - `get_statistics.py` is MANDATORY first step
2. ❌ **No index specified** - Always use `index=X` for performance
3. ❌ **Unbounded time range** - Always specify time ranges
4. ❌ **Fetching all logs** - Use sampling strategies, not unbounded searches
5. ❌ **Ignoring error rate** - High error rate means immediate investigation
6. ❌ **Complex rex on all events** - Filter first, then extract
