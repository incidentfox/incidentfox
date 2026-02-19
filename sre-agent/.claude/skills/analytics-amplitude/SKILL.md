---
name: analytics-amplitude
description: Amplitude product analytics. Use when querying user events, funnels, retention, or product usage data. Provides event segmentation, user activity lookup, and annotation queries.
allowed-tools: Bash(python *)
---

# Amplitude Analytics

## Authentication

**IMPORTANT**: Credentials are injected automatically by a proxy layer. Do NOT check for `AMPLITUDE_API_KEY` or `AMPLITUDE_SECRET_KEY` in environment variables — they won't be visible to you. Just run the scripts directly; authentication is handled transparently.

Configuration environment variables you CAN check (non-secret):
- `AMPLITUDE_REGION` — Region: `US` (default) or `EU`

---

## Available Scripts

All scripts are in `.claude/skills/analytics-amplitude/scripts/`

### query_events.py — Event Segmentation

Query event counts, uniques, averages over time. This is the primary analytics query.

```bash
# Basic: count unique users who triggered an event
python .claude/skills/analytics-amplitude/scripts/query_events.py \
  --event "Button Clicked" --start 2026-02-10 --end 2026-02-17

# Group by property
python .claude/skills/analytics-amplitude/scripts/query_events.py \
  --event "Page Viewed" --start 2026-02-10 --end 2026-02-17 \
  --group-by "platform"

# Daily interval with totals metric
python .claude/skills/analytics-amplitude/scripts/query_events.py \
  --event "Error Occurred" --start 2026-02-10 --end 2026-02-17 \
  --interval daily --metric totals

# With filters
python .claude/skills/analytics-amplitude/scripts/query_events.py \
  --event "Purchase Completed" --start 2026-02-10 --end 2026-02-17 \
  --filters '[{"subprop_type": "event", "subprop_key": "platform", "subprop_op": "is", "subprop_value": ["iOS"]}]'
```

**Arguments:**
- `--event` (required): Event name exactly as tracked
- `--start` / `--end` (required): Date range (YYYYMMDD or YYYY-MM-DD)
- `--interval`: `realtime`, `hourly`, `daily` (default: realtime)
- `--metric`: `uniques`, `totals`, `avg`, `pct_dau` (default: uniques)
- `--group-by`: Event property to segment by
- `--filters`: JSON array of property filters
- `--raw`: Output full JSON response

### get_user_activity.py — User Activity Stream

Look up a specific user's event stream. Useful for debugging user-reported issues.

```bash
# By user ID
python .claude/skills/analytics-amplitude/scripts/get_user_activity.py --user "12345"

# By email
python .claude/skills/analytics-amplitude/scripts/get_user_activity.py --user "user@example.com"

# With pagination
python .claude/skills/analytics-amplitude/scripts/get_user_activity.py --user "12345" --offset 100 --limit 50
```

**Arguments:**
- `--user` (required): Amplitude user ID or email
- `--offset`: Pagination offset (default: 0)
- `--limit`: Max events (default: 100)
- `--raw`: Output full JSON response

### get_chart_annotations.py — Annotations

List chart annotations (deploy markers, releases, feature flags).

```bash
python .claude/skills/analytics-amplitude/scripts/get_chart_annotations.py
```

---

## Investigation Workflow

```
1. What happened?
   └─→ query_events.py --event "Error Occurred" --interval daily
       (see error trend over time)

2. Who was affected?
   └─→ query_events.py --event "Error Occurred" --group-by "user_id"
       (find impacted users)

3. What did the user see?
   └─→ get_user_activity.py --user "<user_id>"
       (trace the user's full event stream)

4. Was there a deploy?
   └─→ get_chart_annotations.py
       (check if a deploy correlates with the error spike)
```

---

## Tips

- Event names are **case-sensitive** and must match exactly as tracked in Amplitude
- Date format: `YYYYMMDD` or `YYYY-MM-DD` (both work)
- The `--raw` flag on any script gives you the full API response for deeper analysis
- For time-series analysis, use `--interval daily` or `--interval hourly`
- `uniques` counts distinct users; `totals` counts total event firings
