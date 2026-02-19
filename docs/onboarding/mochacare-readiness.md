# MochaCare — Integration Readiness Status

**Last updated**: Feb 17, 2026
**Demo**: Friday Feb 21st, 5PM at 3388 Bill Street

---

## Summary

| Integration | Our Platform | Credentials | Customer Side | Status |
|-------------|-------------|-------------|---------------|--------|
| **Cron Job (Status Reports)** | ✅ Ready | N/A | N/A | **Live on staging** |
| **Slack Bot** | ✅ Ready | ✅ Connected | ✅ Channel exists | **Live** |
| **Grafana Cloud** | ✅ Skill + template ready | ❌ Not created yet | ❌ No metrics, no log drain | **Blocked — needs on-site setup** |
| **Amplitude** | ✅ Skill + proxy ready | ✅ Keys stored | ❌ No events tracked yet | **Blocked — customer needs to instrument code** |
| **GitHub Bot** | ✅ Webhook infra ready | ❌ No GitHub App installed | ❌ No repo connected | **Blocked — needs on-site setup** |

---

## 1. Cron Job (Scheduled Status Reports) — ✅ Ready

**What's done:**
- `scheduled_jobs` table created (migration ran on staging RDS)
- 2 jobs seeded: Morning (8AM PT) + Evening (8PM PT)
- Orchestrator scheduler running, polling every 30s
- Output configured to post to Slack channel `C0ADZHLL76V`

**What the agent does at 8AM/8PM:**
1. Query Grafana dashboards for error rates, logs, latency
2. Query Amplitude for event trends (agent failures, error spikes)
3. Generate a formatted status report
4. Post to Slack

**What's missing:**
- The agent will run, but Grafana has no data yet → report will say "no data found"
- Amplitude has no events yet → that section will also be empty
- Once Grafana + Amplitude have data, the reports will be meaningful automatically

---

## 2. Grafana Cloud — ❌ Needs On-Site Setup

### What we've built (our side):
- Grafana skill with 6 scripts (list dashboards, query prometheus, get alerts, create dashboard, etc.)
- Vercel overview dashboard template (`vercel-overview.json`) — 4 panels: Error Count, Error Rate, Log Stream, Request Summary
- `create_dashboard.py` — one-click dashboard creation from template
- Credential-proxy support for Grafana API keys
- Loki data source queries built into dashboard template

### What needs to happen (before or during demo):

#### Step 1: Create Grafana Cloud account (us, pre-demo)
- Sign up at grafana.com (free tier is fine)
- Create stack in us-west-2
- Note the Grafana URL (e.g., `https://mochacare.grafana.net`)
- Create Service Account with Editor role → generate API key
- **Save credentials to config-service** (same way we saved Amplitude)

#### Step 2: Set up Vercel Log Drain (on-site, needs customer's Vercel access)
- Vercel dashboard → Settings → Log Drains
- Add new drain → point to Grafana Cloud Loki push endpoint
- Format: JSON, delivery: NDJSON
- Requires: Loki push URL + basic auth from Grafana Cloud stack

**Why this needs customer involvement:**
MochaCare's Vercel project is under their account. Only they (or someone with admin access) can configure log drains. We need to sit with them and:
1. Open their Vercel dashboard
2. Navigate to Settings → Log Drains
3. Paste in the Grafana Cloud Loki endpoint URL + credentials
4. Save and verify logs are flowing

#### Step 3: Create dashboard (us, after log drain is confirmed)
```bash
python create_dashboard.py \
  --title "MochaCare Overview" \
  --template vercel-overview.json
```

#### Step 4: Verify
- Logs should appear in Grafana within 2-3 minutes
- Dashboard panels should start showing data
- If panels show "No data" → check datasource UID mapping

### What the customer does NOT need to do:
- No code changes needed for Grafana
- No SDK to install
- Vercel already produces logs — we just route them to Grafana

### What the customer DOES need to do:
- Give us Vercel admin access (or do the log drain config themselves with our guidance)
- That's it

---

## 3. Amplitude — ❌ Customer Needs to Instrument Code

### What we've built (our side):
- Amplitude skill with 3 scripts:
  - `query_events.py` — event counts over time, group by properties, filter by segments
  - `get_user_activity.py` — look up a specific user's event stream
  - `get_chart_annotations.py` — deployment markers and release notes
- Credential-proxy support (HTTP Basic auth, US/EU region)
- Credentials already stored in config-service: API key `ff805f...`, Secret key `ff9bc4...`

### What Amplitude IS:
Amplitude is a **product analytics** platform. It tracks user behavior — button clicks, page views, feature usage, errors. Think of it as:
- **Grafana** = infrastructure monitoring (logs, CPU, memory, error rates)
- **Amplitude** = product/user analytics (what are users doing, what's failing for them)

For MochaCare (AI agents as a service), the interesting Amplitude events are:
- Agent invocations (started, completed, failed, timed out)
- Error occurrences by type
- API request latency
- User-facing failures

### What needs to happen (customer must do this):

#### The gap: MochaCare has ZERO events in Amplitude right now

Amplitude is a **pull** model — data only exists if the customer's code sends it. Unlike Grafana (where we just route existing Vercel logs), Amplitude requires the customer to **add tracking code** to their application.

#### What MochaCare needs to add to their codebase:

1. **Install Amplitude SDK**
   ```bash
   npm install @amplitude/analytics-node
   ```

2. **Initialize in their app**
   ```javascript
   import { init, track } from '@amplitude/analytics-node';
   init('ff805fecaf5033fdd417fe3b03aa5eb1'); // their API key
   ```

3. **Track key events** — we recommend these for an AI agent platform:

   | Event Name | When to Fire | Key Properties |
   |-----------|-------------|----------------|
   | `Agent Started` | Agent invocation begins | `agent_id`, `user_id`, `agent_type` |
   | `Agent Completed` | Agent finishes successfully | `agent_id`, `duration_ms`, `tokens_used` |
   | `Agent Failed` | Agent errors/crashes | `agent_id`, `error_type`, `error_message` |
   | `Agent Timeout` | Agent exceeds time limit | `agent_id`, `duration_ms`, `timeout_limit` |
   | `API Error` | Any API route returns 4xx/5xx | `endpoint`, `status_code`, `error_type` |

4. **Example implementation:**
   ```javascript
   // In their agent invocation handler
   import { track } from '@amplitude/analytics-node';

   async function runAgent(agentId, userId) {
     const start = Date.now();
     track('Agent Started', { agent_id: agentId, user_id: userId });

     try {
       const result = await executeAgent(agentId);
       track('Agent Completed', {
         agent_id: agentId,
         user_id: userId,
         duration_ms: Date.now() - start,
       });
       return result;
     } catch (err) {
       track('Agent Failed', {
         agent_id: agentId,
         user_id: userId,
         duration_ms: Date.now() - start,
         error_type: err.name,
         error_message: err.message,
       });
       throw err;
     }
   }
   ```

### Demo day approach for Amplitude:

Since MochaCare likely has zero instrumentation today, there are two options:

**Option A: Skip Amplitude in first demo, add later**
- Focus demo on Grafana (logs) + Slack bot + scheduled reports
- Tell MochaCare: "once you add event tracking, the agent will automatically incorporate it into reports"
- Follow up in week 2 to help them instrument

**Option B: Live instrumentation during demo (the "Claude Code Telemetry Scan")**
- Already in the onboarding doc as an optional step (Minute 10-12)
- Open their repo, use Claude Code to scan for agent invocation points
- Add 2-3 tracking events live, deploy, show data flowing into Amplitude within minutes
- More impressive but risky if their codebase is complex

**Recommendation: Option A for demo day, Option B as follow-up.**
The demo is only 10-15 minutes. Grafana + Slack + scheduled reports are enough to show value. Amplitude can be the "Phase 2" hook.

### What the customer does NOT need to do:
- No Amplitude account setup (we already created it and stored keys)
- No credential management (credential-proxy handles auth)
- No query writing (our agent does that automatically)

### What the customer DOES need to do:
- Add ~20 lines of tracking code to their app
- Deploy the instrumented version
- Wait for events to flow in (takes seconds once code is deployed)

---

## 4. GitHub Bot (PR Review + Auto Event Tracking) — ❌ Needs On-Site Setup

### What we've built (our side):
- GitHub App with OAuth installation flow (`config_service/routes/github.py`)
- Webhook router in orchestrator — receives PR/push/issue events, routes to team's agent
- Context enrichment — fetches PR comments, enriches agent prompt with diff context
- Routing lookup — maps `github_repos` to team config

### What needs to happen (on-site):

#### Step 1: Install GitHub App on customer's org
- Customer navigates to our GitHub App installation URL
- Selects their org/repo → authorizes
- Callback stores `GitHubInstallation` record in our DB
- Links installation to `mochacare` org + `mochacare-sre` team

#### Step 2: Update routing config
We need to PATCH MochaCare's team config to add their repo:
```bash
curl -X PATCH http://config-service/api/v1/config/me \
  -H "X-Org-Id: mochacare" \
  -H "X-Team-Node-Id: mochacare-sre" \
  -d '{"config": {"routing": {"github_repos": ["mochacare/their-repo"]}}}'
```

#### Step 3: Update system prompt
The current planner system prompt only covers SRE monitoring / status reports. For GitHub PR review, we need to add instructions like:
```
## FOR GITHUB PR REVIEWS

When you receive a GitHub PR event:
1. Read the diff and understand what changed
2. Check if new API routes or agent invocation points have proper error tracking
3. If Amplitude event tracking is missing, suggest specific tracking events
4. If there are obvious bugs or error handling gaps, flag them
5. Post your review as a GitHub comment
```

This can be done by PATCHing the team config:
```bash
curl -X PATCH http://config-service/api/v1/config/me \
  -d '{"config": {"agents": {"planner": {"prompt": {"system": "...updated prompt..."}}}}}'
```

#### Step 4: Enable coding subagent
Currently `coding` agent is `enabled: false`. For auto-commit event tracking code, we need:
```json
{"config": {"agents": {"coding": {"enabled": true}}}}
```

### What the customer does NOT need to do:
- No webhook configuration (GitHub App handles this automatically)
- No API key management

### What the customer DOES need to do:
- Authorize our GitHub App on their org (one-click)
- Tell us which repo(s) to monitor
- Decide if they want auto-commit (agent pushes code) or review-only (agent comments)

---

## Pre-Demo Action Items

### We do BEFORE demo (no customer involvement):

| # | Task | Blocked by | Priority |
|---|------|-----------|----------|
| 1 | Create Grafana Cloud account + stack | Nothing | **P0** |
| 2 | Generate Grafana API key, save to config-service | Task 1 | **P0** |
| 3 | Deploy Amplitude code changes to staging | Nothing | **P0** |
| 4 | Update system prompt with GitHub PR review instructions | Nothing | P1 |
| 5 | Enable coding subagent in team config | Nothing | P1 |
| 6 | Prepare test report screenshot for demo | Grafana data | P1 |
| 7 | Test a manual agent run via Slack | Deployment | **P0** |

### We do ON-SITE with customer:

| # | Task | Time | Notes |
|---|------|------|-------|
| 1 | Configure Vercel log drain → Grafana Loki | 3 min | Need their Vercel admin access |
| 2 | Run `create_dashboard.py` to create Grafana dashboard | 1 min | After log drain confirmed |
| 3 | Install GitHub App on their org | 1 min | One-click authorization |
| 4 | Update routing config with their repo name | 1 min | We do this via CLI/API |
| 5 | Demo Slack bot, dashboard, scheduled reports | 10 min | The main demo |
| 6 | (Optional) Claude Code telemetry scan | 5 min | If time permits |

### Customer does AFTER demo:

| # | Task | Notes |
|---|------|-------|
| 1 | Add Amplitude SDK + tracking events to their code | We provide the code snippets above |
| 2 | Deploy instrumented version | They handle their own deploys |
| 3 | Verify events in Amplitude dashboard | We can help verify via our skill |

---

## Integration Dependency Graph

```
                    Vercel (already running)
                    ├── produces logs automatically
                    └── hosts MochaCare's app
                         │
            ┌────────────┼────────────────┐
            ▼            ▼                ▼
     Grafana Cloud    Amplitude      GitHub App
     (log drain)     (SDK needed)   (install needed)
            │            │                │
            ▼            ▼                ▼
     Our Dashboard   Our Skill       Our Webhook Router
     (create_dashboard) (query_events)  (PR review)
            │            │                │
            └────────────┼────────────────┘
                         ▼
                    SRE Agent (planner)
                         │
                    ┌────┴────┐
                    ▼         ▼
              Cron Reports  Slack Bot
              (8AM/8PM)    (on-demand)
```

**Key insight**: Grafana is the easiest to get working (just route existing logs, no code changes). Amplitude requires customer code changes. GitHub App requires authorization + config update.
