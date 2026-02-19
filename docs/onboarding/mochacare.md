# MochaCare Onboarding Runbook

**Customer**: MochaCare
**Deal**: $60/month, monthly billing
**Demo**: Friday Feb 21st, 5PM at 3388 Bill Street
**Goal**: 10-15 min integration meeting. Walk in, set everything up, walk out.

---

## Pre-Demo Checklist (do this BEFORE the meeting)

### 1. Grafana Cloud Setup

- [ ] Sign up for Grafana Cloud (free tier works)
- [ ] Create stack: `mochacare` in us-west-2 region
- [ ] Note the Grafana URL (e.g., `https://mochacare.grafana.net`)
- [ ] Create a Service Account with Editor role
- [ ] Generate an API key for the service account
- [ ] Set up Loki data source (included in Grafana Cloud)
- [ ] Get the Loki push URL and auth credentials for Vercel log drain

### 2. Vercel Log Drain

- [ ] In Vercel dashboard: Settings > Log Drains
- [ ] Add a new log drain pointing to Grafana Cloud Loki endpoint
- [ ] Format: JSON, delivery: NDJSON
- [ ] Verify logs are flowing (may take a few minutes)

### 3. Create Dashboard

From sre-agent sandbox or local dev:

```bash
# Set env vars
export GRAFANA_URL=https://mochacare.grafana.net
export GRAFANA_API_KEY=<service-account-key>

# Create the dashboard from template
python sre-agent/.claude/skills/observability-grafana/scripts/create_dashboard.py \
  --title "MochaCare Overview" \
  --template sre-agent/.claude/skills/observability-grafana/templates/vercel-overview.json
```

- [ ] Verify dashboard appears in Grafana
- [ ] Check that log panels show data from Vercel log drain
- [ ] Customize datasource UIDs if needed (template uses `${DS_LOKI}` variables)

### 4. Seed Config

```bash
cd config_service

# Set required env vars
export MOCHACARE_ORG_ID=mochacare
export MOCHACARE_SLACK_CHANNEL_ID=<their-slack-channel-id>
export MOCHACARE_GITHUB_REPO=<their-org>/<their-repo>    # optional
export MOCHACARE_GRAFANA_URL=https://mochacare.grafana.net
export MOCHACARE_TIMEZONE=America/Los_Angeles

# Run seed script
poetry run python scripts/seed_mochacare.py
```

- [ ] Verify org/team created: `GET /api/v1/config/me/effective` with team token
- [ ] Verify scheduled jobs: `GET /api/v1/config/me/scheduled-jobs`
- [ ] Verify output config has Slack destination

### 5. Credential Setup

In config-service (or AWS Secrets Manager for production):

- [ ] Set Grafana credentials for `mochacare` org:
  - `grafana.domain` = Grafana Cloud URL
  - `grafana.api_key` = Service account API key
- [ ] Verify credential-proxy can resolve: `GET /api/integrations` with sandbox JWT

### 6. Deploy

- [ ] Deploy config-service (has new scheduled_jobs table + API)
- [ ] Deploy orchestrator (has scheduler loop)
- [ ] Deploy sre-agent (has Grafana dashboard creation skill)
- [ ] Verify orchestrator logs show `scheduler_started`

### 7. Test

- [ ] Trigger a test agent run via Slack: ask the bot about system health
- [ ] Create a test scheduled job with `"* * * * *"` schedule (every minute)
- [ ] Verify it fires and posts to Slack
- [ ] Delete the test job, confirm real 8AM/8PM jobs are active

---

## Demo Day Script (Feb 21st, 5PM)

**Total time target: 10-15 minutes**

### Minute 0-2: Setup

1. Open laptop, connect to their wifi
2. Open browser tabs:
   - Grafana dashboard (pre-loaded)
   - Slack channel (pre-joined)

### Minute 2-4: Show Grafana Dashboard

> "This is your monitoring dashboard. It shows error rates, logs, and system health in real-time."

- Show the 4 panels: Error Count, Error Rate, Log Stream, Request Summary
- Point out that logs are flowing from Vercel automatically
- Show how to filter logs by level (error, warning)

### Minute 4-6: Show Slack Bot

> "You can ask the bot anything about your system. It reads your logs and metrics."

- In their Slack channel, type: `@IncidentFox how's the system looking right now?`
- Wait for the agent to respond with a status summary
- Show that it references actual Grafana data

### Minute 6-8: Show Scheduled Reports

> "You'll get automatic status reports at 8AM and 8PM every day."

- Show example report format (bring a screenshot of a test report)
- Explain: morning report covers overnight, evening report covers the workday
- Show the Slack channel where reports will appear

### Minute 8-10: Show Proactive Alerts

> "If something breaks, you'll know immediately — no need to check dashboards."

- Explain: if error rate spikes or new error types appear, the bot alerts automatically
- Show example alert in Slack (bring a screenshot)

### Minute 10-12: (Optional) Claude Code Telemetry Scan

If time permits and they're interested:

1. Open Claude Code on their laptop (or yours with their repo cloned)
2. Run the prepared prompt:

```
Scan this codebase and identify the top 3-4 places where we should add error
tracking and telemetry events. Focus on:
- AI agent invocation points (where agents are called and could fail)
- API route handlers (where errors should be logged)
- Background job/task entry points
For each location, suggest a specific tracking event with properties.
```

3. Review the suggestions together
4. Optionally apply 1-2 tracking events live

### Minute 12-15: Wrap Up

- Confirm Slack channel is set up
- Confirm they'll start receiving reports at 8PM today (or 8AM tomorrow)
- Leave them with:
  - Grafana URL + bookmark
  - Knowledge that the Slack bot is always available
  - Our contact for any issues

---

## Post-Demo Steps

- [ ] Verify first scheduled report fires (8AM or 8PM, whichever comes first)
- [ ] Check Slack for the report and confirm it looks good
- [ ] Monitor for the first week — check that reports are consistent
- [ ] Follow up in 3 days to see if they have questions
- [ ] Add any custom Grafana panels they request

---

## Troubleshooting

**Logs not showing in Grafana?**
- Check Vercel log drain is active and pointing to correct Loki endpoint
- Verify Loki data source in Grafana is configured correctly
- Check log drain format is NDJSON

**Scheduled reports not firing?**
- Check orchestrator logs: `scheduler_poll_error` or `scheduler_found_due_jobs`
- Verify `next_run_at` is set: `GET /api/v1/config/me/scheduled-jobs`
- Check config-service internal API: `GET /api/v1/internal/scheduled-jobs/due`

**Bot not responding in Slack?**
- Verify slack-bot is connected (Socket Mode)
- Check routing config has correct `slack_channel_ids`
- Check credential-proxy has valid Anthropic API key

**Dashboard panels showing "No data"?**
- Verify datasource UID matches (may need to update from template defaults)
- Check time range — Vercel logs may take a few minutes to appear
- Try a wider time range (last 24h) to confirm data exists
