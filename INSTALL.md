# Self-Hosted Installation

Get IncidentFox running in your Slack workspace in under 5 minutes.

> **Quick overview?** See the [Quick Start section in README.md](README.md#quick-start) for a condensed version. This guide provides detailed step-by-step instructions.

## Prerequisites

- Docker and Docker Compose
- Slack workspace (you'll create an app)
- Anthropic API key

---

## Step 1: Create Slack App (2 min)

1. **[Click here to create your app](https://api.slack.com/apps?new_app=1)** → Choose "From an app manifest"
2. Select your workspace
3. Copy the entire contents of [`slack-bot/slack-manifest.yaml`](./slack-bot/slack-manifest.yaml)
4. Paste into the YAML field
5. Click "Create" → "Install to Workspace" → "Allow"

---

## Step 2: Get Your Tokens (1 min)

After installation, you'll be on your app's dashboard:

**Bot Token:**
- Click **OAuth & Permissions** (left sidebar)
- Copy "Bot User OAuth Token" (starts with `xoxb-`)

**App Token:**
- Click **Basic Information** → scroll to **App-Level Tokens**
- Click "Generate Token and Scopes"
  - Name: `socket`
  - Add scope: `connections:write`
  - Click "Generate"
- Copy token (starts with `xapp-`)

---

## Step 3: Configure & Run (2 min)

```bash
git clone https://github.com/incidentfox/incidentfox.git
cd incidentfox

# Create your config
cp .env.example .env

# Edit .env and add your tokens:
# - SLACK_BOT_TOKEN=xoxb-...
# - SLACK_APP_TOKEN=xapp-...
# - ANTHROPIC_API_KEY=sk-ant-...

# Start everything
docker-compose up -d
```

That's it! 🎉

---

## Step 4: Test It

In Slack, invite the bot to a channel:
```
/invite @IncidentFox
```

Then try it out:
```
@IncidentFox what's 2+2?
```

You should see a streaming response!

---

## What's Running?

Two services work together:

- **Slack Bot** - Connects to your Slack workspace
- **SRE Agent** - Runs the AI investigations

All services are configured with container isolation and resource limits.

---

## Common Commands

**View logs:**
```bash
# All services
docker-compose logs -f

# Just one service
docker-compose logs -f sre-agent
docker-compose logs -f slack-bot
```

**Restart services:**
```bash
docker-compose restart
```

**Stop everything:**
```bash
docker-compose down
```

**Update and restart:**
```bash
git pull
docker-compose up -d --build
```

---

## Configuration

### Environment Variables

Edit `.env` to customize:

| Variable | Required | Description |
|----------|----------|-------------|
| `SLACK_BOT_TOKEN` | ✅ | Bot token from Slack (xoxb-...) |
| `SLACK_APP_TOKEN` | ✅ | App-level token for Socket Mode (xapp-...) |
| `ANTHROPIC_API_KEY` | ✅ | Your Anthropic API key |
| `LMNR_PROJECT_API_KEY` | Optional | For tracing/debugging |
| `CORALOGIX_API_KEY` | Optional | If using Coralogix integration |
| `CORALOGIX_DOMAIN` | Optional | Your Coralogix domain |

---

## Troubleshooting

**Bot doesn't respond:**
- Check logs: `docker-compose logs slack-bot`
- Verify bot is invited to channel: `/invite @IncidentFox`
- Verify Socket Mode is enabled in Slack app settings

**Agent errors:**
- Check logs: `docker-compose logs sre-agent`
- Verify `ANTHROPIC_API_KEY` is valid
- Check services are running: `docker-compose ps`

**Need more resources:**
Edit `docker-compose.yml` to increase limits:
```yaml
sre-agent:
  mem_limit: 4g  # Default is 2g
  cpus: 4        # Default is 2
```

---

## Scaling Up

### For Production Workloads

The sre-agent includes Kubernetes deployment with stronger isolation:

```bash
cd sre-agent

# First time: Create cluster
make setup-prod

# Deploy
make deploy-prod
```

This provides:
- Auto-scaling
- Enhanced isolation (gVisor)
- Better observability
- Multi-tenant support

See `sre-agent/README.md` for details.

---

## Why Self-Host?

✅ **Simple approval** - No third-party vendor review needed
✅ **Your infrastructure** - Data never leaves your environment
✅ **Fully customizable** - Add your own tools and integrations
✅ **Cost effective** - Pay only for compute + Claude API usage

---

## Need Help?

- **Issues**: [GitHub Issues](https://github.com/incidentfox/incidentfox/issues)
- **Docs**: See [slack-bot/README.md](./slack-bot/README.md) and [sre-agent/README.md](./sre-agent/README.md)
- **Updates**: `git pull && docker-compose up -d --build`

---

Enjoy investigating! 🦊
