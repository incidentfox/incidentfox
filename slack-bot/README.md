# IncidentFox Slack Bot

Slack bot for IncidentFox AI SRE agent using [Bolt framework](https://slack.dev/bolt-python/).

## Quick Start

```bash
cd slack-bot

# First time setup
make setup
source .venv/bin/activate
make install

# Configure
cp env.example .env
# Edit .env with your SLACK_BOT_TOKEN, SLACK_APP_TOKEN, SLACK_SIGNING_SECRET

# Run
make run
```

Or manually:

```bash
uv venv && source .venv/bin/activate
uv pip install -e .
cp env.example .env  # Edit with your tokens
python app.py
```

## Slack App Setup

1. Go to [api.slack.com/apps](https://api.slack.com/apps)
2. Create new app → From scratch
3. Enable **Socket Mode** (Settings → Socket Mode → Enable)
4. Generate App-Level Token with `connections:write` scope → save as `SLACK_APP_TOKEN`
5. Add Bot Token Scopes (OAuth & Permissions):
   - `app_mentions:read`
   - `chat:write`
   - `channels:history` (for message listener)
6. Install to workspace → save Bot Token as `SLACK_BOT_TOKEN`
7. Subscribe to events (Event Subscriptions → Subscribe to bot events):
   - `app_mention`
   - `message.channels`

## Socket Mode vs HTTP Mode

| Feature | Socket Mode (Dev) | HTTP Mode (Production) |
|---------|------------------|----------------------|
| Public URL needed? | ❌ No | ✅ Yes |
| Signature verification | ❌ Skipped | ✅ Automatic (via Bolt) |
| Slack Marketplace | ❌ Not allowed | ✅ Required |
| Setup complexity | ✅ Simple | ⚠️ Moderate |

**Current mode: Socket Mode** (good for local dev)

Bolt automatically handles:
- ✅ Signature verification (when `signing_secret` provided in HTTP mode)
- ✅ URL verification challenges
- ✅ Request validation
- ✅ Retry logic

No manual checks needed - Orchestrator's manual verification is only needed if you're building webhooks from scratch!

## Current Features

- Responds to @mentions
- Responds to messages containing "hello"
- Button interaction example

## Architecture

```
Slack User
    │
    │ @mention
    ▼
Slack Bot (Socket Mode)
    │
    │ POST /investigate
    │ {"prompt": "...", "thread_id": "slack-{channel}-{thread}"}
    ▼
SRE Agent (http://localhost:8000)
    │
    │ Streaming response
    ▼
Slack User (with feedback buttons)
```

## Features

✅ **Streaming responses** - Real-time AI output using Slack's `chat_stream` API
✅ **Thread-based context** - Follow-up questions reuse the same sandbox
✅ **Feedback buttons** - Thumbs up/down on responses
✅ **Simple integration** - Just calls sre-agent's HTTP API

## Usage

1. **Start sre-agent** (in another terminal):
   ```bash
   cd sre-agent
   # For standalone (no K8s):
   source .venv/bin/activate
   python server.py
   
   # Or with K8s sandboxes:
   make dev
   ```

2. **Mention the bot in Slack**:
   ```
   @IncidentFox what pods are running in the default namespace?
   ```

3. **Follow-up in the same thread**:
   ```
   show me logs for the first pod
   ```

The bot will:
- Stream the response in real-time
- Reuse the same sandbox for follow-ups in the thread
- Add feedback buttons when done

## Production Deployment

### Prerequisites

1. Slack App must be configured for HTTP mode (Event Subscriptions enabled)
2. ECR repository created (done automatically via `../sre-agent/scripts/setup-prod.sh`)
3. EKS cluster running with sre-agent deployed

### Deploy to Production

```bash
cd slack-bot
./scripts/deploy-prod.sh
```

This will:
1. Build multi-platform Docker image (amd64/arm64)
2. Push to ECR
3. Deploy to EKS with LoadBalancer
4. Output the public webhook URL

### Configure Slack App for Production

After deployment, configure your Slack app:

1. Go to [api.slack.com/apps](https://api.slack.com/apps)
2. Select your app
3. **Disable Socket Mode** (Settings → Socket Mode → Toggle OFF)
4. **Enable Event Subscriptions**:
   - Toggle ON
   - Request URL: `http://<LOADBALANCER_URL>/slack/events`
   - Subscribe to bot events: `app_mention`, `message.channels`
5. **OAuth & Permissions**: Ensure bot scopes are configured:
   - `app_mentions:read`
   - `chat:write`
   - `channels:history`
   - `files:write`
6. Reinstall app to workspace if needed

### Architecture (Production)

```
Slack User
    │
    │ @mention (HTTP webhook)
    ▼
Slack Bot (EKS LoadBalancer)
    │
    │ POST /investigate
    │ {"prompt": "...", "thread_id": "slack-{channel}-{thread}"}
    ▼
SRE Agent (internal K8s service)
    │
    │ Streaming response
    ▼
Slack User (with feedback buttons)
```

### Environment Variables

Production deployment sets:
- `SLACK_APP_MODE=http` - Enables HTTP mode (Flask)
- `PORT=3000` - HTTP server port
- `SRE_AGENT_URL=http://incidentfox-server-svc.incidentfox-prod.svc.cluster.local:8000` - Internal K8s service URL

### Monitoring

```bash
# Check deployment status
kubectl get pods -n incidentfox-prod -l app=slack-bot

# View logs
kubectl logs -n incidentfox-prod -l app=slack-bot --tail=50 -f

# Get public URL
kubectl get svc slack-bot-svc -n incidentfox-prod -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'
```

### Secrets Management

Required secrets (stored in `slack-bot-secrets`):
- `SLACK_SIGNING_SECRET` - From Slack App settings
- `SLACK_CLIENT_ID` - OAuth client ID
- `SLACK_CLIENT_SECRET` - OAuth client secret

OAuth credentials and integrations are managed via config-service.

## Next Steps

- [ ] Add interrupt button (stop current investigation)
- [ ] Add loading states with fun messages
- [x] Switch to HTTP mode for production

