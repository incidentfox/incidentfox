# MochaCare E2E Testing Plan

**Test bed repo**: [incidentfox/aws-playground](https://github.com/incidentfox/aws-playground)
(OpenTelemetry Astronomy Shop demo — Next.js 16 frontend, microservices, OTel collector, Prometheus, Grafana)

**Goal**: Validate every IncidentFox flow end-to-end with real data before the Feb 21st demo.

---

## Overview

| Phase | What | Time | Needs Deploy? |
|-------|------|------|---------------|
| **0** | Deploy all code to staging | 10 min | Yes |
| **1** | Seed real data into Grafana + Amplitude | 10 min | No |
| **2** | Test credential-proxy routes | 5 min | No |
| **3** | Test agent skills via Slack bot | 10 min | No |
| **4** | Test cron job → Slack report | 5 min | No |
| **5** | Test GitHub webhook → PR review | 10 min | No |
| **6** | (Optional) Full live data pipeline | 30 min | No |

---

## Phase 0: Deploy All Services to Staging

All code is on branch `longyi-07/mochacare-review`. Deploy everything:

```bash
# Trigger deploy via GitHub Actions
# Services: config-service, orchestrator, sre-agent, slack-bot, credential-proxy
# Environment: staging (incidentfox-demo cluster)
```

Verify after deploy:
- [ ] config-service pod running
- [ ] orchestrator logs show `scheduler_started`
- [ ] sre-agent pod running
- [ ] credential-proxy pod running
- [ ] slack-bot connected (Socket Mode)

---

## Phase 1: Seed Real Data

### 1a. Push test logs to Grafana Cloud Loki

Push synthetic Vercel-like logs directly to the Loki push API. No Vercel log drain needed — we fake the data.

```bash
# Loki push endpoint (get these from Grafana Cloud → mochacare stack → Loki section)
LOKI_URL="https://logs-prod-XXX.grafana.net/loki/api/v1/push"
LOKI_USER="<loki-user-id>"
LOKI_KEY="<loki-api-key>"

# Push a batch of realistic logs
NOW=$(date +%s)000000000

curl -X POST "$LOKI_URL" \
  -u "$LOKI_USER:$LOKI_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "streams": [
      {
        "stream": {"source": "vercel", "app": "mochacare", "level": "info"},
        "values": [
          ["'"$NOW"'", "POST /api/agent/invoke 200 - 1234ms"],
          ["'"$((NOW+1000000))"'", "POST /api/agent/invoke 200 - 892ms"],
          ["'"$((NOW+2000000))"'", "GET /api/health 200 - 12ms"],
          ["'"$((NOW+3000000))"'", "POST /api/agent/invoke 200 - 2103ms"],
          ["'"$((NOW+4000000))"'", "GET /api/agents/list 200 - 45ms"]
        ]
      },
      {
        "stream": {"source": "vercel", "app": "mochacare", "level": "error"},
        "values": [
          ["'"$((NOW+5000000))"'", "POST /api/agent/invoke 500 - AgentTimeoutError: Agent exceeded 30s timeout limit"],
          ["'"$((NOW+6000000))"'", "POST /api/agent/invoke 500 - Error: OpenAI API rate limit exceeded"],
          ["'"$((NOW+7000000))"'", "POST /api/webhook/callback 502 - Error: upstream connect error"]
        ]
      },
      {
        "stream": {"source": "vercel", "app": "mochacare", "level": "warn"},
        "values": [
          ["'"$((NOW+8000000))"'", "Agent response latency above threshold: 5200ms (threshold: 3000ms)"],
          ["'"$((NOW+9000000))"'", "Retry attempt 2/3 for agent invoke - previous attempt timed out"]
        ]
      }
    ]
  }'
```

Verify:
- [ ] Go to https://mochacare.grafana.net → Explore → select Loki datasource
- [ ] Query: `{source="vercel"}` — should show logs
- [ ] MochaCare Overview dashboard should show data in panels

### 1b. Push test events to Amplitude

Send synthetic product events via Amplitude's HTTP V2 API:

```bash
AMPLITUDE_API_KEY="<amplitude-api-key>"

curl -X POST "https://api2.amplitude.com/2/httpapi" \
  -H "Content-Type: application/json" \
  -d '{
    "api_key": "'"$AMPLITUDE_API_KEY"'",
    "events": [
      {
        "user_id": "user_001",
        "event_type": "Agent Started",
        "time": '"$(date +%s)000"',
        "event_properties": {"agent_id": "agent-abc", "agent_type": "customer-support"}
      },
      {
        "user_id": "user_001",
        "event_type": "Agent Completed",
        "time": '"$(( $(date +%s) + 5 ))000"',
        "event_properties": {"agent_id": "agent-abc", "duration_ms": 4823, "tokens_used": 1250}
      },
      {
        "user_id": "user_002",
        "event_type": "Agent Started",
        "time": '"$(( $(date +%s) + 10 ))000"',
        "event_properties": {"agent_id": "agent-def", "agent_type": "data-analysis"}
      },
      {
        "user_id": "user_002",
        "event_type": "Agent Failed",
        "time": '"$(( $(date +%s) + 40 ))000"',
        "event_properties": {"agent_id": "agent-def", "error_type": "TimeoutError", "error_message": "Agent exceeded 30s limit", "duration_ms": 30000}
      },
      {
        "user_id": "user_003",
        "event_type": "Agent Started",
        "time": '"$(( $(date +%s) + 60 ))000"',
        "event_properties": {"agent_id": "agent-ghi", "agent_type": "customer-support"}
      },
      {
        "user_id": "user_003",
        "event_type": "Agent Completed",
        "time": '"$(( $(date +%s) + 63 ))000"',
        "event_properties": {"agent_id": "agent-ghi", "duration_ms": 2100, "tokens_used": 800}
      },
      {
        "user_id": "user_001",
        "event_type": "API Error",
        "time": '"$(( $(date +%s) + 120 ))000"',
        "event_properties": {"endpoint": "/api/agent/invoke", "status_code": 500, "error_type": "RateLimitError"}
      }
    ]
  }'
```

Verify:
- [ ] Go to https://app.amplitude.com → select project
- [ ] Check "User Look-Up" for user_001 — should see Agent Started → Agent Completed events
- [ ] Check "Event Segmentation" → "Agent Failed" events should appear

### 1c. Seed more data over time (optional)

For realistic dashboard data, run the above commands on a cron locally to simulate ongoing traffic:

```bash
# Add to crontab: push logs every 5 minutes
*/5 * * * * /path/to/seed_test_logs.sh
*/10 * * * * /path/to/seed_test_events.sh
```

This gives us 12 hours of data by demo day.

---

## Phase 2: Test Credential-Proxy Routes

Exec into the credential-proxy pod and test each integration directly.

### 2a. Grafana proxy

```bash
# Get credential-proxy pod
kubectl exec -n incidentfox <cred-proxy-pod> -- \
  curl -s http://localhost:8002/grafana/api/search \
    -H "X-Tenant-Id: mochacare" \
    -H "X-Team-Id: mochacare-sre"
```

Expected: 200, JSON array with "MochaCare Overview" dashboard.

### 2b. Amplitude proxy

```bash
kubectl exec -n incidentfox <cred-proxy-pod> -- \
  curl -s "http://localhost:8002/amplitude/events/segmentation" \
    -H "X-Tenant-Id: mochacare" \
    -H "X-Team-Id: mochacare-sre" \
    -G -d 'e={"event_type":"Agent Started"}' \
    -d 'start=20260217' \
    -d 'end=20260219'
```

Expected: 200, JSON with event counts (should have data if Phase 1b ran).

### 2c. Check integration status

```bash
kubectl exec -n incidentfox <cred-proxy-pod> -- \
  curl -s http://localhost:8002/api/integrations \
    -H "X-Tenant-Id: mochacare" \
    -H "X-Team-Id: mochacare-sre"
```

Expected: `grafana: configured`, `amplitude: configured`.

---

## Phase 3: Test Agent Skills via Slack

These tests validate the full path: Slack → slack-bot → sre-agent → sandbox → credential-proxy → external API → response back to Slack.

### 3a. Grafana skill test

In Slack channel `C0ADZHLL76V`:
```
@IncidentFox list all Grafana dashboards for our team
```

Expected: Agent uses `list_dashboards.py`, responds with dashboard list including "MochaCare Overview".

### 3b. Grafana dashboard query

```
@IncidentFox check the MochaCare Overview dashboard and tell me about recent errors
```

Expected: Agent uses `get_dashboard.py` to get panel info, may use `query_prometheus.py` or Loki queries to pull data, reports on the error logs we seeded.

### 3c. Amplitude skill test

```
@IncidentFox query Amplitude for "Agent Failed" events in the last 24 hours
```

Expected: Agent uses `query_events.py`, returns the Agent Failed events we seeded (user_002, TimeoutError).

### 3d. Amplitude user lookup

```
@IncidentFox look up user_001 activity in Amplitude
```

Expected: Agent uses `get_user_activity.py`, returns event stream (Agent Started → Agent Completed → API Error).

### 3e. Combined status check

```
@IncidentFox give me a full status report — check both Grafana and Amplitude
```

Expected: Agent checks Grafana dashboards (error logs), queries Amplitude (agent failure rate), produces a combined summary.

---

## Phase 4: Test Cron Job → Slack Report

### 4a. Create a test job that fires immediately

```bash
kubectl exec -n incidentfox <config-service-pod> -- \
  curl -s -X POST http://localhost:8080/api/v1/config/me/scheduled-jobs \
    -H "Content-Type: application/json" \
    -H "X-Org-Id: mochacare" \
    -H "X-Team-Node-Id: mochacare-sre" \
    -H "X-Internal-Service: e2e-test" \
    -d '{
      "name": "E2E Test Report",
      "schedule": "* * * * *",
      "timezone": "UTC",
      "config": {
        "prompt": "Generate a brief status report. Check Grafana dashboards for any errors and query Amplitude for agent failure events in the last hour. Keep it short.",
        "agent_name": "planner",
        "max_turns": 10,
        "output_destinations": [{"type": "slack", "channel_id": "C0ADZHLL76V"}]
      }
    }'
```

### 4b. Watch it fire

```bash
# Watch orchestrator logs for job claim
kubectl logs -f -n incidentfox <orchestrator-pod> | grep -E "scheduled_jobs|agent_run"
```

Expected within 60 seconds:
1. Orchestrator claims the job
2. Orchestrator calls sre-agent `/investigate`
3. Agent runs, queries Grafana + Amplitude
4. Report appears in Slack channel

### 4c. Clean up test job

```bash
# Delete the test job (get job ID from creation response)
kubectl exec -n incidentfox <config-service-pod> -- \
  curl -s -X DELETE http://localhost:8080/api/v1/config/me/scheduled-jobs/<job-id> \
    -H "X-Org-Id: mochacare" \
    -H "X-Team-Node-Id: mochacare-sre" \
    -H "X-Internal-Service: e2e-test"
```

### 4d. Verify real jobs still exist

```bash
kubectl exec -n incidentfox <config-service-pod> -- \
  curl -s http://localhost:8080/api/v1/config/me/scheduled-jobs \
    -H "X-Org-Id: mochacare" \
    -H "X-Team-Node-Id: mochacare-sre" \
    -H "X-Internal-Service: e2e-test"
```

Expected: 2 jobs remain — "Morning Status Report" (8AM PT) and "Evening Status Report" (8PM PT).

---

## Phase 5: Test GitHub Webhook → PR Review

Uses `incidentfox/aws-playground` as the test repo.

### 5a. Update MochaCare routing config

Add `aws-playground` to MochaCare's routing:

```bash
kubectl exec -n incidentfox <config-service-pod> -- \
  curl -s -X PATCH http://localhost:8080/api/v1/config/me \
    -H "Content-Type: application/json" \
    -H "X-Org-Id: mochacare" \
    -H "X-Team-Node-Id: mochacare-sre" \
    -H "X-Internal-Service: e2e-test" \
    -d '{"config": {"routing": {"github_repos": ["incidentfox/aws-playground"]}}}'
```

### 5b. Install GitHub App on the repo

1. Navigate to the IncidentFox GitHub App installation page
2. Select `incidentfox` org → `aws-playground` repo
3. Authorize
4. Verify installation stored in config-service:
   ```bash
   kubectl exec -n incidentfox <config-service-pod> -- \
     curl -s http://localhost:8080/api/v1/github/installations \
       -H "X-Internal-Service: e2e-test"
   ```

### 5c. Configure webhook on the repo

If not auto-configured by the GitHub App, add manually:

```bash
gh api repos/incidentfox/aws-playground/hooks \
  --method POST \
  -f 'config[url]=https://<orchestrator-url>/webhooks/github' \
  -f 'config[content_type]=json' \
  -f 'config[secret]=<GITHUB_WEBHOOK_SECRET>' \
  -f 'events[]=pull_request' \
  -f 'events[]=push' \
  -f 'events[]=issue_comment' \
  -f 'active=true'
```

### 5d. Update system prompt for PR review

The current planner prompt only covers SRE monitoring. Add PR review instructions:

```bash
# Add PR review guidance to the system prompt
# This is a PATCH merge — it won't overwrite the existing SRE prompt,
# just needs to be appended to it.
```

Suggested addition to system prompt:
```
## FOR GITHUB PR REVIEWS

When you receive a GitHub Pull Request event:
1. Read the diff carefully and understand what changed
2. Check for error handling — are failures caught and logged?
3. Check for observability — are key operations tracked with events?
4. If Amplitude event tracking is missing at important points (API calls,
   agent invocations, error paths), suggest adding it with specific code
5. Check for common issues: unhandled promises, missing try/catch, hardcoded values
6. Post your review as a concise, actionable GitHub comment
```

### 5e. Create a test PR

Create a branch on aws-playground with a small change, open a PR:

```bash
cd /tmp && git clone git@github.com:incidentfox/aws-playground.git && cd aws-playground
git checkout -b test/e2e-incidentfox-review
# Make a small code change (e.g., add a new API route without error handling)
git push -u origin test/e2e-incidentfox-review
gh pr create --title "test: Add agent status endpoint" --body "Testing IncidentFox PR review"
```

### 5f. Verify

1. Orchestrator logs show GitHub webhook received
2. Agent runs against the PR
3. Comment appears on the PR within 1-2 minutes
4. Comment is relevant and mentions error handling / event tracking

### 5g. Clean up

```bash
gh pr close <pr-number> --repo incidentfox/aws-playground
git push origin --delete test/e2e-incidentfox-review
```

---

## Phase 6: (Optional) Full Live Data Pipeline

For the most realistic test, add real instrumentation to aws-playground's frontend.

### 6a. Add Amplitude SDK to frontend

In `aws-playground/src/frontend/`:

```bash
npm install @amplitude/analytics-node
```

Create `src/frontend/utils/telemetry/amplitude.ts`:
```typescript
import { init, track } from '@amplitude/analytics-node';

const AMPLITUDE_API_KEY = process.env.NEXT_PUBLIC_AMPLITUDE_API_KEY || '';

let initialized = false;

export function initAmplitude() {
  if (!initialized && AMPLITUDE_API_KEY) {
    init(AMPLITUDE_API_KEY);
    initialized = true;
  }
}

export function trackEvent(eventName: string, properties?: Record<string, any>) {
  if (!initialized) initAmplitude();
  if (AMPLITUDE_API_KEY) {
    track(eventName, undefined, properties);
  }
}
```

### 6b. Add tracking to key routes

In checkout, cart, and product catalog service handlers, add:
```typescript
import { trackEvent } from '../utils/telemetry/amplitude';

// In route handler:
trackEvent('Checkout Started', { cart_size: items.length, total: cartTotal });
// On success:
trackEvent('Checkout Completed', { order_id: orderId, duration_ms: elapsed });
// On error:
trackEvent('Checkout Failed', { error_type: err.name, error_message: err.message });
```

### 6c. Configure Vercel log drain (if deploying to Vercel)

OR configure the OTel collector to export to Grafana Cloud Loki:

In `docker-compose.yml`, add Loki exporter to otel-collector config:
```yaml
exporters:
  loki:
    endpoint: "https://<loki-user-id>:<loki-key>@logs-prod-XXX.grafana.net/loki/api/v1/push"
```

### 6d. Run and generate traffic

```bash
docker compose up -d
# The load-generator service automatically generates traffic
# Logs flow to Grafana Cloud, events flow to Amplitude
```

---

## Validation Checklist

After all phases, verify each end-to-end flow:

### Infrastructure
- [ ] All pods running on staging
- [ ] Orchestrator scheduler polling every 30s
- [ ] No crash loops or OOM errors

### Credential-Proxy
- [ ] Grafana proxy returns dashboard data
- [ ] Amplitude proxy returns event data
- [ ] JWT-based tenant isolation works (wrong tenant returns empty/403)

### Grafana
- [ ] MochaCare Overview dashboard shows data in all 4 panels
- [ ] Agent can list dashboards via skill
- [ ] Agent can query dashboard data and summarize

### Amplitude
- [ ] Events visible in Amplitude web UI
- [ ] Agent can query event segmentation via skill
- [ ] Agent can look up user activity via skill

### Cron Jobs
- [ ] Test job fires within 60 seconds
- [ ] Agent produces a report mentioning both Grafana and Amplitude data
- [ ] Report posts to correct Slack channel
- [ ] Real jobs (8AM/8PM) have correct `next_run_at` values

### GitHub
- [ ] Webhook reaches orchestrator
- [ ] Orchestrator routes to correct team (mochacare-sre)
- [ ] Agent reviews PR and posts comment
- [ ] Comment is relevant and actionable

### Slack Bot
- [ ] Bot responds to @mention in the channel
- [ ] Bot can query Grafana on demand
- [ ] Bot can query Amplitude on demand
- [ ] Bot produces combined status reports

---

## Troubleshooting

### "No data" in Grafana dashboard
- Check Loki datasource UID — template uses `grafanacloud-logs`, your instance might differ
- Run in Grafana Explore: `{source="vercel"}` to verify data exists
- Dashboard time range may not cover the seeded data — expand to "Last 24h"

### Amplitude skill returns errors
- Verify API key is correct: `curl -u "API_KEY:SECRET_KEY" https://amplitude.com/api/2/events/segmentation?e=...`
- Amplitude data has ~1 min ingestion delay — wait and retry
- Check credential-proxy logs for auth header construction

### Cron job doesn't fire
- Check `next_run_at`: `GET /api/v1/config/me/scheduled-jobs`
- Check orchestrator logs: look for `scheduler_poll` events
- Verify config-service internal API: `GET /api/v1/internal/scheduled-jobs/due`
- The scheduler claims jobs with `FOR UPDATE SKIP LOCKED` — check for stuck claims

### GitHub webhook not received
- Check webhook delivery status: `gh api repos/incidentfox/aws-playground/hooks/<id>/deliveries`
- Verify orchestrator is publicly accessible (needs ingress or port-forward)
- Check webhook signature: `GITHUB_WEBHOOK_SECRET` must match between repo and orchestrator

### Agent sandbox fails to start
- Check sre-agent logs for sandbox creation errors
- Verify `AMPLITUDE_BASE_URL` and `GRAFANA_BASE_URL` env vars in sandbox spec
- Check credential-resolver service is reachable from sandbox namespace
