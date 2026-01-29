# IncidentFox Integrations

Complete setup guides for all IncidentFox integrations. Connect your observability stack, collaboration tools, and infrastructure to enable AI-powered incident investigation.

---

## Table of Contents

- [Slack Bot](#slack-bot-primary-interface)
- [GitHub Bot](#github-bot)
- [PagerDuty](#pagerduty-auto-investigation)
- [A2A Protocol](#a2a-protocol-agent-to-agent)
- [REST API](#rest-api)
- [Environment Variables](#environment-variables)

---

## Slack Bot (Primary Interface)

The Slack bot is the primary way to interact with IncidentFox. Mention the bot in any channel to start an investigation.

### Usage

```
@incidentfox why is the payments service slow?
@incidentfox investigate pod nginx-abc123 crashing
@incidentfox help me debug this error: [paste error]
```

The bot will respond with a rich, progressively updated investigation with findings, evidence, and recommendations.

### Setup

#### 1. Create a Slack App

1. Go to https://api.slack.com/apps
2. Click **"Create New App"** → **"From scratch"**
3. Name it (e.g., "IncidentFox") and select your workspace

#### 2. Configure Bot Token Scopes

Navigate to **OAuth & Permissions** in the left sidebar, then scroll to **Bot Token Scopes** and add:

- `app_mentions:read` - Listen for @mentions
- `chat:write` - Send messages
- `channels:history` - Read channel messages (for thread context)
- `channels:read` - View channel list
- `groups:history` - Read private channel messages
- `im:history` - Read direct messages
- `mpim:history` - Read group direct messages

#### 3. Enable Socket Mode (for self-hosted)

1. Go to **Settings** → **Socket Mode** in the left sidebar
2. Toggle **Enable Socket Mode** to ON
3. You'll be prompted to create an app-level token:
   - Name: `socket` (or any name)
   - Add scope: `connections:write`
   - Click **Generate**
4. **Copy the token** (starts with `xapp-`) - this is your `SLACK_APP_TOKEN`

**Note:** Socket Mode is required for self-hosted deployments. For cloud deployments, use Event Subscriptions with webhook URL instead.

#### 4. Install to Workspace

1. Go to **OAuth & Permissions**
2. Click **"Install to Workspace"**
3. Review permissions and click **"Allow"**
4. **Copy the "Bot User OAuth Token"** (starts with `xoxb-`) - this is your `SLACK_BOT_TOKEN`

#### 5. Enable Event Subscriptions

Navigate to **Event Subscriptions** in the left sidebar:

1. Toggle **Enable Events** to ON
2. If using Socket Mode (self-hosted), you're done
3. If using webhooks (cloud deployment):
   - Set **Request URL** to: `https://your-domain/api/slack/events`
   - Slack will verify the URL is reachable

#### 6. Subscribe to Bot Events

Scroll down to **Subscribe to bot events** and add:

- `app_mention` - When someone @mentions the bot
- `message.channels` - Messages in public channels (if bot is member)
- `message.groups` - Messages in private channels (if bot is member)
- `message.im` - Direct messages to the bot
- `message.mpim` - Group direct messages

Click **Save Changes**

#### 7. Configure Environment Variables

Add to your `.env` file:

```bash
# Required for Socket Mode (self-hosted)
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_APP_TOKEN=xapp-your-app-token

# Required for webhooks (cloud deployment)
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_SIGNING_SECRET=your-signing-secret
```

**Where to find `SLACK_SIGNING_SECRET`:**
- Go to **Basic Information** → **App Credentials**
- Copy the **Signing Secret**

#### 8. Restart Services

```bash
docker-compose restart slack-bot
# or for Kubernetes
kubectl rollout restart deployment/slack-bot -n incidentfox
```

#### 9. Test It

In Slack:
1. Invite the bot to a channel: `/invite @IncidentFox`
2. Mention it: `@IncidentFox what's 2+2?`
3. You should see a streaming response!

### Troubleshooting

**Bot doesn't respond:**
- Check logs: `docker-compose logs slack-bot`
- Verify bot is invited to channel: `/invite @IncidentFox`
- Verify Socket Mode is enabled (for self-hosted)
- Check bot token has correct scopes
- Check services are running: `docker-compose ps`

**Agent errors:**
- Check agent logs: `docker-compose logs sre-agent`
- Verify `ANTHROPIC_API_KEY` is valid and has credits
- Restart services: `docker-compose restart`

**Permission errors:**
- Re-install the app to workspace to refresh scopes
- Verify bot is added to the channel

**Connection issues:**
- For Socket Mode: Check `SLACK_APP_TOKEN` is correct and has `connections:write` scope
- For webhooks: Verify request URL is publicly accessible and returns 200 OK

**Performance issues:**
- Check resource usage: `docker stats`
- Increase limits in `docker-compose.yml`:
  ```yaml
  sre-agent:
    mem_limit: 4g  # Default is 2g
    cpus: 4        # Default is 2
  ```

**Common Commands:**
```bash
# View logs
docker-compose logs -f            # All services
docker-compose logs -f slack-bot  # Just Slack bot
docker-compose logs -f sre-agent  # Just SRE agent

# Restart services
docker-compose restart

# Stop everything
docker-compose down

# Update and restart
git pull
docker-compose up -d --build
```

---

## GitHub Bot

Comment on issues or PRs to trigger investigation. Useful for CI/CD debugging, code review, and security analysis.

### Usage

Comment on any issue or PR:

```
@incidentfox investigate why this test is failing
/investigate the authentication changes in this PR
/analyze potential security issues
```

The bot will comment with investigation results, including:
- Root cause analysis
- Code references
- Suggested fixes
- Related PRs/issues

### Setup

#### 1. Create a GitHub Personal Access Token

1. Go to https://github.com/settings/tokens
2. Click **"Generate new token"** → **"Generate new token (classic)"**
3. Name it (e.g., "IncidentFox Bot")
4. Select scopes:
   - `repo` - Full control of private repositories
   - `write:discussion` - Read and write discussions
5. Click **"Generate token"**
6. **Copy the token** (starts with `ghp_`) - you won't see it again!

#### 2. Set Environment Variables

Add to your `.env` file:

```bash
GITHUB_TOKEN=ghp_your_personal_access_token
GITHUB_WEBHOOK_SECRET=your-random-secret-string
```

**Generate a random webhook secret:**
```bash
openssl rand -hex 32
```

#### 3. Configure Webhook in Repository

For each repository you want to enable:

1. Go to **Settings** → **Webhooks** → **Add webhook**
2. Set **Payload URL**: `https://your-domain/api/github/webhook`
3. Set **Content type**: `application/json`
4. Set **Secret**: Same as `GITHUB_WEBHOOK_SECRET` from step 2
5. Select **"Let me select individual events"**:
   - ✅ Issue comments
   - ✅ Pull request review comments
   - ✅ Pull requests (optional - for auto-analysis)
6. Ensure **Active** is checked
7. Click **Add webhook**

#### 4. Restart Services

```bash
docker-compose restart orchestrator
# or for Kubernetes
kubectl rollout restart deployment/orchestrator -n incidentfox
```

#### 5. Test It

1. Create a test issue or PR
2. Comment: `@incidentfox hello`
3. The bot should reply within a few seconds

### Troubleshooting

**Bot doesn't respond:**
- Check webhook delivery in GitHub Settings → Webhooks → Recent Deliveries
- Verify webhook URL is publicly accessible
- Check logs: `docker-compose logs orchestrator`

**Authentication errors:**
- Verify `GITHUB_TOKEN` has correct scopes
- Token might be expired - generate a new one

**Webhook signature errors:**
- Verify `GITHUB_WEBHOOK_SECRET` matches in both GitHub and `.env`

---

## PagerDuty (Auto-Investigation)

Automatically investigate when alerts fire. IncidentFox starts an investigation and posts findings to Slack.

### Usage

When a PagerDuty incident triggers:
1. IncidentFox receives the webhook
2. Starts investigation automatically with alert context
3. Posts findings to configured Slack channel
4. Includes service name, urgency, and priority

No manual intervention required.

### Setup

#### 1. Get Webhook URL

Your webhook URL will be: `https://your-domain/api/pagerduty/webhook`

#### 2. Configure PagerDuty Webhook

1. Go to PagerDuty → **Services** → Select your service
2. Navigate to **Integrations** tab
3. Click **"Add another integration"**
4. Select **"Generic Webhooks (v3)"**
5. Set **Webhook URL**: `https://your-domain/api/pagerduty/webhook`
6. Click **"Add"**
7. **Copy the integration key** (optional, for future reference)

#### 3. Get Signing Secret (optional for validation)

1. In the webhook configuration, find the **Signing Secret**
2. Copy it to your `.env` file:

```bash
PAGERDUTY_WEBHOOK_SECRET=your-signing-secret
```

**Note:** If not provided, webhook signature validation will be skipped (less secure).

#### 4. Configure Slack Channel for Notifications

Set the Slack channel where investigation results should be posted:

```bash
PAGERDUTY_SLACK_CHANNEL=incidents  # or #incidents
```

#### 5. Restart Services

```bash
docker-compose restart orchestrator
# or for Kubernetes
kubectl rollout restart deployment/orchestrator -n incidentfox
```

#### 6. Test It

1. Trigger a test incident in PagerDuty
2. Check your configured Slack channel for investigation results
3. Verify the investigation includes alert context

### Troubleshooting

**No investigation triggered:**
- Check PagerDuty webhook status (should show recent deliveries)
- Verify webhook URL is publicly accessible
- Check logs: `docker-compose logs orchestrator`

**Investigation posted to wrong channel:**
- Verify `PAGERDUTY_SLACK_CHANNEL` is set correctly
- Ensure bot is invited to that channel

---

## A2A Protocol (Agent-to-Agent)

Allow other AI agents to call IncidentFox using Google's Agent-to-Agent protocol. Useful for building multi-agent workflows.

### Usage

Other agents can send tasks to IncidentFox:

```json
POST /api/a2a
Content-Type: application/json
Authorization: Bearer YOUR_API_TOKEN

{
  "method": "tasks/send",
  "params": {
    "message": {
      "role": "user",
      "parts": [{"text": "Investigate high latency in payments service"}]
    }
  }
}
```

### Supported Methods

| Method | Description |
|--------|-------------|
| `tasks/send` | Start a new investigation |
| `tasks/get` | Retrieve investigation status and results |
| `tasks/cancel` | Cancel an in-progress investigation |
| `agent/authenticatedExtendedCard` | Get agent capabilities and authentication info |

### Setup

#### 1. Generate API Token

```bash
# In the web UI: Settings → API → Generate Token
# Or via CLI:
curl -X POST https://your-domain/api/admin/tokens \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d '{"name": "A2A Integration", "scopes": ["agent:invoke"]}'
```

#### 2. Configure Calling Agent

In the calling agent's configuration, add IncidentFox as an A2A tool:

```json
{
  "tools": [
    {
      "type": "a2a",
      "name": "incidentfox",
      "endpoint": "https://your-domain/api/a2a",
      "auth": {
        "type": "bearer",
        "token": "YOUR_API_TOKEN"
      }
    }
  ]
}
```

#### 3. Test Connection

```bash
curl -X POST https://your-domain/api/a2a \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  -d '{
    "method": "agent/authenticatedExtendedCard"
  }'
```

Should return agent capabilities.

### Example: Multi-Agent Workflow

```
Orchestrator Agent
    │
    ├─> IncidentFox (via A2A): "Investigate API latency"
    │   └─> Returns: Root cause is database query
    │
    └─> DBA Agent (via A2A): "Optimize query X"
        └─> Returns: Added index, latency reduced 90%
```

**Full documentation:** [../agent/docs/A2A_PROTOCOL.md](../agent/docs/A2A_PROTOCOL.md)

---

## REST API

Direct programmatic access to IncidentFox. Useful for custom integrations, automation scripts, and internal tools.

### Authentication

All API requests require an API token:

```bash
Authorization: Bearer YOUR_API_TOKEN
```

**Generate a token:**
- Web UI: Settings → API → Generate Token
- Or use admin token from deployment

### Start Investigation

```bash
curl -X POST https://your-domain/api/orchestrator/agents/run \
  -H "Authorization: Bearer $API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "org_id": "org-1",
    "team_node_id": "team-platform",
    "agent_name": "investigation",
    "message": "Investigate pod crash in production"
  }'
```

**Response:**
```json
{
  "run_id": "run_abc123",
  "status": "in_progress",
  "created_at": "2024-01-15T10:30:00Z"
}
```

### Get Investigation Results

```bash
curl https://your-domain/api/orchestrator/runs/run_abc123 \
  -H "Authorization: Bearer $API_TOKEN"
```

**Response:**
```json
{
  "run_id": "run_abc123",
  "status": "completed",
  "agent_name": "investigation",
  "transcript": [...],
  "findings": {
    "root_cause": "...",
    "recommendations": [...]
  }
}
```

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/orchestrator/agents/run` | POST | Start investigation |
| `/api/orchestrator/runs/{id}` | GET | Get run status/results |
| `/api/orchestrator/runs/{id}/cancel` | POST | Cancel investigation |
| `/api/config/teams/{id}/prompts` | GET/PUT | Manage team prompts |
| `/api/config/teams/{id}/mcps` | GET/POST | Manage MCP servers |

**Full API reference:** [API.md](API.md) (coming soon)

---

## Environment Variables

Complete reference of all integration-related environment variables.

### Core

```bash
# Required
OPENAI_API_KEY=sk-...              # OpenAI API key
OPENAI_MODEL=gpt-4o                # Model to use (gpt-4o, gpt-4-turbo)

# Optional
ANTHROPIC_API_KEY=sk-ant-...       # For Claude agents
```

### Slack

```bash
# For Socket Mode (self-hosted)
SLACK_BOT_TOKEN=xoxb-...           # Bot User OAuth Token
SLACK_APP_TOKEN=xapp-...           # App-Level Token with connections:write

# For Webhooks (cloud deployment)
SLACK_BOT_TOKEN=xoxb-...           # Bot User OAuth Token
SLACK_SIGNING_SECRET=...           # From Basic Information → App Credentials
```

### GitHub

```bash
GITHUB_TOKEN=ghp_...               # Personal access token with repo scope
GITHUB_WEBHOOK_SECRET=...          # Random string for webhook validation
```

### PagerDuty

```bash
PAGERDUTY_WEBHOOK_SECRET=...       # Signing secret from PagerDuty
PAGERDUTY_SLACK_CHANNEL=incidents  # Slack channel for auto-investigation results
```

### AWS

```bash
AWS_REGION=us-west-2               # Default AWS region
AWS_ACCESS_KEY_ID=...              # For CloudWatch, EC2, ECS tools
AWS_SECRET_ACCESS_KEY=...
```

### Grafana

```bash
GRAFANA_URL=https://grafana.example.com
GRAFANA_API_KEY=...                # Service account token or API key
```

### Datadog

```bash
DATADOG_API_KEY=...                # API key from Datadog
DATADOG_APP_KEY=...                # Application key from Datadog
DATADOG_SITE=datadoghq.com         # Or datadoghq.eu, ddog-gov.com, etc.
```

### New Relic

```bash
NEW_RELIC_API_KEY=...              # User API key
NEW_RELIC_ACCOUNT_ID=...           # Account ID for NRQL queries
```

### Elasticsearch

```bash
ELASTICSEARCH_URL=https://elastic.example.com:9200
ELASTICSEARCH_USERNAME=...
ELASTICSEARCH_PASSWORD=...
# Or
ELASTICSEARCH_API_KEY=...          # Base64 encoded API key
```

### Database

```bash
DATABASE_URL=postgresql://user:pass@host:5432/incidentfox
```

### Admin & Auth

```bash
ADMIN_TOKEN=...                    # Admin API token (generate secure random string)
TOKEN_PEPPER=...                   # 32+ char random string for token encryption
```

### Optional Observability

```bash
# Tracing
LMNR_PROJECT_API_KEY=...           # Laminar AI tracing (optional)

# Additional logging
CORALOGIX_API_KEY=...              # If using Coralogix
CORALOGIX_DOMAIN=...               # Your Coralogix domain
```

---

## What's Next?

- **[FEATURES.md](FEATURES.md)** - Learn about advanced capabilities
- **[DEPLOYMENT.md](DEPLOYMENT.md)** - Deploy for your organization (Docker Compose, Kubernetes, Production)
- **[ARCHITECTURE.md](ARCHITECTURE.md)** - Understand the system design
