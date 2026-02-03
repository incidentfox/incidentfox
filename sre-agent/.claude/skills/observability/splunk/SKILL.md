---
name: splunk-analysis
description: Splunk log analysis using SPL (Search Processing Language). Use when investigating issues via Splunk logs, saved searches, or alerts.
---

# Splunk Analysis

## Core Principle: Statistics Before Samples

**NEVER start by reading raw logs.** Always begin with aggregated statistics:

1. **Volume**: How many events in the time window?
2. **Distribution**: Which sources/hosts/error types?
3. **Trends**: Is it increasing, stable, or decreasing?
4. **THEN sample**: Get specific entries after understanding the landscape

---

## Available Tools

| Tool | Purpose |
|------|---------|
| `splunk_search` | Execute SPL queries |
| `splunk_list_indexes` | List available indexes |
| `splunk_get_saved_searches` | Get saved searches/reports |
| `splunk_get_alerts` | Get triggered alerts |

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

### Step 1: Get the Big Picture

```python
# Count events by source
splunk_search(
    query='index=main | stats count by source | sort -count | head 10',
    earliest_time="-1h",
    max_results=20
)

# Error count over time
splunk_search(
    query='index=main level=ERROR | timechart span=5m count',
    earliest_time="-1h"
)

# Top error messages
splunk_search(
    query='index=main level=ERROR | stats count by message | sort -count | head 10',
    earliest_time="-1h"
)
```

### Step 2: Focus on Problem Area

```python
# Errors from specific service
splunk_search(
    query='index=main service=api-gateway level=ERROR | stats count by message | sort -count',
    earliest_time="-1h"
)

# Timeline of specific error
splunk_search(
    query='index=main "connection refused" | timechart span=1m count',
    earliest_time="-1h"
)
```

### Step 3: Sample Strategically

```python
# Get sample error events
splunk_search(
    query='index=main service=api-gateway level=ERROR | head 10',
    earliest_time="-1h",
    max_results=10
)

# Get context around a specific time
splunk_search(
    query='index=main service=api-gateway',
    earliest_time="01/15/2024:14:30:00",
    latest_time="01/15/2024:14:35:00",
    max_results=50
)
```

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

### Transaction Analysis (Multi-Event)

```spl
index=main
| transaction request_id maxspan=5m
| stats avg(duration) as avg_duration, count as transaction_count
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

## Working with Indexes and Saved Searches

### Discover Available Data

```python
# List all indexes
splunk_list_indexes()

# Check index sizes and event counts
# Returns: name, total_event_count, current_db_size_mb
```

### Use Saved Searches

```python
# Get existing searches (often have proven queries)
splunk_get_saved_searches()

# Returns: name, search query, schedule, alert_type
```

### Check Triggered Alerts

```python
# Get recent alerts
splunk_get_alerts(earliest_time="-24h")

# Returns: alert_name, trigger_time, severity
```

---

## Output Format

```markdown
## Splunk Analysis Summary

### Time Window
- **Start**: [earliest_time]
- **End**: [latest_time]
- **Duration**: X hours

### Query Statistics
- **Total events**: X events
- **Error count**: Y events (Z%)
- **Sources**: N distinct sources
- **Error rate trend**: [increasing/stable/decreasing]

### Top Error Sources
| Source | Count |
|--------|-------|
| [source1] | N |
| [source2] | M |

### Error Timeline
[Describe when errors started, peaked, etc.]

### Top Error Messages
1. [message]: N occurrences
2. [message]: M occurrences

### Sample Errors
[Quote 2-3 representative error messages]

### Root Cause Hypothesis
[Based on patterns observed]
```

---

## Performance Tips

### Always Specify Index

```spl
# GOOD - fast
index=main error

# BAD - scans all indexes (slow)
error
```

### Use Time Filters

```python
# GOOD - bounded time
splunk_search(query="...", earliest_time="-1h")

# BAD - unbounded (scans everything)
splunk_search(query="...")
```

### Filter Early

```spl
# GOOD - filter before aggregation
index=main level=ERROR | stats count by host

# BAD - stats on all events, then filter
index=main | stats count by host, level | where level="ERROR"
```

### Limit Results

```spl
# Use head/tail to limit before returning
index=main error | stats count by message | sort -count | head 20
```

---

## Anti-Patterns

1. **No index specified** - Always use `index=X` for performance
2. **Unbounded time range** - Always specify `earliest_time`
3. **Returning too many raw events** - Use `stats`, `timechart`, or `head/tail`
4. **Complex rex on all events** - Filter first, then extract
5. **Ignoring saved searches** - Others may have solved your query already

---

## Pro Tips

**Start broad, narrow down:**
1. Get counts first (`| stats count by source`)
2. Identify problematic source
3. Then filter to that source
4. Finally sample events

**Use subsearch for correlation:**
```spl
index=main error [search index=deployments | head 1 | fields version]
```

**Leverage lookups:**
If you have service metadata, join it:
```spl
index=main | lookup services.csv service_id OUTPUT service_name, team
```

**Check field extraction:**
Run `| fieldsummary` to see what fields are available and their coverage.
