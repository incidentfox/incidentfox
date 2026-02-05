---
name: observability
description: Log, metric, and trace analysis methodology. Use when analyzing logs, investigating errors, querying metrics, or correlating signals across observability backends (Coralogix, Datadog, CloudWatch).
---

# Observability Analysis

## Core Principle: Statistics Before Samples

**NEVER start by reading raw logs.** Always begin with aggregated statistics:

1. **Volume**: How many logs in the time window?
2. **Distribution**: Which services/levels/error types?
3. **Trends**: Is it increasing, stable, or decreasing?
4. **THEN sample**: Get specific entries after understanding the landscape

## Available Backends

**IMPORTANT**: Credentials are injected automatically by a proxy layer. Do NOT check for API keys in environment variables - they won't be there. Just use the backend scripts directly; authentication is handled transparently.

Available backends (invoke with `/skill-name`):
- **Coralogix** (DataPrime) - `/observability-coralogix`
- **Datadog** - `/observability-datadog`
- **Honeycomb** - `/observability-honeycomb`
- **Splunk** (SPL) - `/observability-splunk`
- **Elasticsearch/OpenSearch** - `/observability-elasticsearch`
- **Jaeger** (Tracing) - `/observability-jaeger`

To check if a backend is working, try a simple query rather than checking env vars.

### Backend-Specific Skills
- **Coralogix**: `/observability-coralogix` - DataPrime syntax, log/trace analysis
- **Datadog**: `/observability-datadog` - DQL syntax, metrics and APM
- **Honeycomb**: `/observability-honeycomb` - High-cardinality analysis, distributed tracing
- **Splunk**: `/observability-splunk` - SPL syntax, saved searches
- **Elasticsearch**: `/observability-elasticsearch` - Lucene/Query DSL
- **Jaeger**: `/observability-jaeger` - Distributed tracing, latency analysis

## Analysis Framework

### Step 1: Get the Big Picture
- Total log volume
- Error rate and distribution
- Which services are most affected

### Step 2: Identify Patterns
- Error clustering (many errors in short time)
- Temporal patterns (started at X time)
- Service correlation (Service A errors → Service B errors)

### Step 3: Sample Strategically
- Sample from error peaks
- Get examples of each distinct error type
- Compare against baseline period

## Output Format

When reporting observability findings, use this structure:

```
## Log Analysis Summary

### Time Window
- Start: [timestamp]
- End: [timestamp]
- Duration: X hours

### Statistics
- Total logs: X events
- Error count: Y events (Z%)
- Services affected: N services
- Error rate trend: [increasing/stable/decreasing]

### Top Error Services
1. [service1]: N errors
2. [service2]: M errors

### Error Patterns
- Primary error type: [description]
- First occurrence: [timestamp]
- Correlation: [deployment/traffic/external event]

### Sample Errors
[Quote 2-3 representative error messages with context]

### Root Cause Hypothesis
[Based on patterns observed]

### Confidence Level
[High/Medium/Low with explanation]
```
