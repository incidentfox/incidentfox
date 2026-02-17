---
name: newrelic-observability
description: New Relic APM and monitoring. Use when running NRQL queries, checking application performance, error rates, or throughput via New Relic.
allowed-tools: Bash(python *)
---

# New Relic Observability

## Authentication

**IMPORTANT**: Credentials are injected automatically by a proxy layer. Do NOT check for `NEWRELIC_API_KEY` in environment variables - it won't be visible to you. Just run the scripts directly; authentication is handled transparently.

Configuration environment variables you CAN check (non-secret):
- `NEWRELIC_ACCOUNT_ID` - New Relic account ID
- `NEWRELIC_BASE_URL` - API base URL (proxy mode)

---

## Available Scripts

All scripts are in `.claude/skills/observability-newrelic/scripts/`

### query_nrql.py - Run NRQL Queries (START HERE)
```bash
python .claude/skills/observability-newrelic/scripts/query_nrql.py --account-id ACCOUNT_ID --query "SELECT average(duration) FROM Transaction SINCE 1 hour ago"
```

### get_apm_summary.py - APM Summary
```bash
python .claude/skills/observability-newrelic/scripts/get_apm_summary.py --account-id ACCOUNT_ID --app-name MyApp [--time-range 30m]
```

---

## NRQL Query Reference

```sql
-- Response time
SELECT average(duration) FROM Transaction WHERE appName = 'MyApp' SINCE 1 hour ago

-- Throughput
SELECT count(*) FROM Transaction WHERE appName = 'MyApp' SINCE 1 hour ago TIMESERIES 5 minutes

-- Error rate
SELECT percentage(count(*), WHERE error = true) FROM Transaction WHERE appName = 'MyApp' SINCE 1 hour ago

-- Apdex score
SELECT apdex(duration, t: 0.5) FROM Transaction WHERE appName = 'MyApp' SINCE 1 hour ago

-- Slowest transactions
SELECT average(duration), count(*) FROM Transaction WHERE appName = 'MyApp' SINCE 1 hour ago FACET name LIMIT 10

-- Database query time
SELECT average(databaseDuration) FROM Transaction WHERE appName = 'MyApp' SINCE 1 hour ago TIMESERIES

-- External service calls
SELECT average(externalDuration), count(*) FROM Transaction WHERE appName = 'MyApp' SINCE 1 hour ago FACET externalTransactionName
```

---

## Investigation Workflow

### Application Performance Issue
```
1. get_apm_summary.py --account-id <id> --app-name <app> (overview)
2. query_nrql.py --query "SELECT average(duration) FROM Transaction WHERE appName = '<app>' SINCE 1 hour ago TIMESERIES 5 minutes"
3. query_nrql.py --query "SELECT percentage(count(*), WHERE error = true) FROM Transaction WHERE appName = '<app>' SINCE 1 hour ago TIMESERIES 5 minutes"
```
